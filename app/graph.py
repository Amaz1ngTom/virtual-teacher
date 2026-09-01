from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph

from app.adapters.llm import TeachingLLM
from app.lessons import get_lesson
from app.profile_store import SQLiteProfileStore


class TeachingState(MessagesState, total=False):
    user_id: str
    lesson_id: str
    user_text: str
    profile: dict[str, Any]
    response_text: str
    emotion: str
    speech_rate: float
    memory_update: dict[str, Any]
    lesson_phase: str
    concept_index: int
    attempt_count: int
    score: int
    current_question: str
    evaluation_correct: bool
    evaluation_feedback: str
    lesson_action: str
    media_cache_scope: str
    dynamic_topic: str
    dynamic_section_index: int
    retrieval_context: str
    dynamic_section_total: int


def _message_dicts(messages: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        if isinstance(message, dict):
            role = str(message.get("role", "user"))
            content = str(message.get("content", ""))
        else:
            role = getattr(message, "type", "user")
            role = {"human": "user", "ai": "assistant"}.get(role, role)
            content = str(getattr(message, "content", ""))
        normalized.append({"role": role, "content": content})
    return normalized


def _selected_choice(
    user_text: str, choices: tuple[str, ...]
) -> str | None:
    """Resolve explicit ordinal/letter wording without treating bare digits as indices."""

    if not choices:
        return None
    normalized = user_text.strip().lower()
    candidate = re.sub(
        r"^(?:我的)?(?:答案|选择)?(?:是|为)?\s*[:：]?\s*",
        "",
        normalized,
    ).strip(" `\"'。.!！?？")
    compact = re.sub(r"\s+", "", candidate)
    if compact in {"中间那个", "中间一个", "中间项", "中间选项"} and len(choices) == 3:
        return choices[1]
    match = re.fullmatch(
        r"(?:我)?(?:选|选择|选项)?(?:第)?"
        r"([一二三四五六七八九]|[1-9]|[a-z])"
        r"(?:个选项|项|个|号|选项)?",
        compact,
    )
    if match is None:
        return None
    token = match.group(1)
    # A bare number is usually the answer itself (especially in arithmetic),
    # not a choice index. Require wording such as 第2个 for numeric ordinals.
    if token.isdigit() and compact == token:
        return None
    chinese_numbers = "一二三四五六七八九"
    if token in chinese_numbers:
        if compact == token:
            return None
        index = chinese_numbers.index(token)
    elif token.isdigit():
        index = int(token) - 1
    else:
        index = ord(token) - ord("a")
    return choices[index] if 0 <= index < len(choices) else None


def _matches_fixed_answer(
    user_text: str,
    accepted_answers: tuple[str, ...],
    choices: tuple[str, ...] = (),
) -> bool:
    """Match curriculum answers, including explicit choice references."""

    normalized = user_text.strip().lower()
    candidate = re.sub(
        r"^(?:我的)?(?:答案|选择)?(?:是|为)?\s*[:：]?\s*",
        "",
        normalized,
    ).strip(" `\"'。.!！?？")
    selected_choice = _selected_choice(user_text, choices)
    for accepted in accepted_answers:
        answer = accepted.strip().lower()
        if not answer:
            continue
        if selected_choice is not None and selected_choice.strip().lower() == answer:
            return True
        if candidate == answer:
            return True
        if re.fullmatch(r"[a-z0-9_]+", answer):
            if re.search(
                rf"(?<![a-z0-9_]){re.escape(answer)}(?![a-z0-9_])",
                normalized,
            ):
                return True
    return False


class TeachingGraphRuntime:
    def __init__(
        self,
        checkpoint_path: Path,
        profiles: SQLiteProfileStore,
        llm: TeachingLLM,
    ):
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_connection = sqlite3.connect(
            checkpoint_path, check_same_thread=False
        )
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.profiles = profiles
        self.llm = llm
        self.graph = self._build_graph()

    def _build_graph(self):
        def load_profile(state: TeachingState) -> dict[str, Any]:
            profile = self.profiles.get(state["user_id"])
            progress = dict(profile.get("learning_progress", {}))
            changed = False
            for lesson_id, record in progress.items():
                lesson = get_lesson(lesson_id)
                if lesson is None or not isinstance(record, dict):
                    continue
                clamped = min(
                    lesson.assessment_total,
                    max(0, int(record.get("score", 0))),
                )
                if record.get("score") != clamped or record.get("total") != lesson.assessment_total:
                    progress[lesson_id] = {
                        **record,
                        "score": clamped,
                        "total": lesson.assessment_total,
                    }
                    changed = True
            if changed:
                profile = self.profiles.merge(
                    state["user_id"], {"learning_progress": progress}
                )
            return {"profile": profile}

        def chat_reply(state: TeachingState) -> dict[str, Any]:
            plan = self.llm.generate(
                user_text=state["user_text"],
                profile=state.get("profile", {}),
                recent_messages=_message_dicts(state.get("messages", [])),
                source_context=state.get("retrieval_context", ""),
            )
            return {
                "messages": [{"role": "assistant", "content": plan.reply_text}],
                "response_text": plan.reply_text,
                "emotion": plan.emotion,
                "speech_rate": plan.speech_rate,
                "memory_update": plan.memory_update,
                "media_cache_scope": "",
            }

        def dynamic_lecture(state: TeachingState) -> dict[str, Any]:
            action = state.get("lesson_action", "dynamic_start")
            section_total = 5
            if action == "dynamic_start":
                section_index = 0
                topic = state.get("user_text", "").strip()
                if len(topic) < 2 or topic == "请根据当前对话确定主题并开始连续讲授":
                    raise ValueError("请先在输入框中填写一个明确的讲授主题")
            else:
                if state.get("lesson_phase") != "dynamic_lecture" or not state.get(
                    "dynamic_topic"
                ):
                    raise ValueError("动态讲授会话状态已失效，请点击“开始动态连续讲授”重新开始")
                section_index = min(
                    int(state.get("dynamic_section_index", 0)) + 1,
                    section_total - 1,
                )
                topic = state.get("dynamic_topic", "").strip() or "当前对话中的学习主题"
            plan = self.llm.generate_dynamic_lecture(
                topic=topic,
                section_number=section_index + 1,
                section_total=section_total,
                profile=state.get("profile", {}),
                recent_messages=_message_dicts(state.get("messages", [])),
            )
            phase = (
                "dynamic_complete"
                if section_index + 1 >= section_total
                else "dynamic_lecture"
            )
            return {
                "messages": [{"role": "assistant", "content": plan.reply_text}],
                "response_text": plan.reply_text,
                "emotion": plan.emotion,
                "speech_rate": plan.speech_rate,
                "memory_update": {},
                "lesson_phase": phase,
                "dynamic_topic": topic,
                "dynamic_section_index": section_index,
                "dynamic_section_total": section_total,
                "current_question": "",
                # Dynamic content is generated from live context and must never
                # share the deterministic course media cache.
                "media_cache_scope": "",
            }

        def stop_dynamic_lecture(state: TeachingState) -> dict[str, Any]:
            response = "动态连续讲授已暂停。你可以继续提问，也可以稍后从当前主题重新开始讲授。"
            return {
                "messages": [{"role": "assistant", "content": response}],
                "response_text": response,
                "emotion": "neutral",
                "speech_rate": 1.0,
                "memory_update": {},
                "lesson_phase": "dynamic_paused",
                "current_question": "",
                "media_cache_scope": "",
            }

        def present_concept(state: TeachingState) -> dict[str, Any]:
            lesson = get_lesson(state["lesson_id"])
            if lesson is None:
                raise ValueError(f"Unknown lesson: {state['lesson_id']}")
            restarting = state.get("lesson_phase") == "complete"
            concept_index = 0 if restarting else int(state.get("concept_index", 0))
            concept = lesson.concepts[concept_index]
            response = f"{concept.explanation}\n\n问题：{concept.question}"
            return {
                "messages": [{"role": "assistant", "content": response}],
                "response_text": response,
                "emotion": "neutral",
                "speech_rate": 1.0,
                "memory_update": {},
                "lesson_phase": "await_answer",
                "concept_index": concept_index,
                "attempt_count": 0,
                "score": 0 if restarting else int(state.get("score", 0)),
                "current_question": concept.question,
                "media_cache_scope": f"{lesson.lesson_id}/section-1",
            }

        def guided_section(
            state: TeachingState,
            concept_index: int,
            *,
            include_feedback: bool = False,
        ) -> dict[str, Any]:
            lesson = get_lesson(state["lesson_id"])
            if lesson is None or lesson.mode != "guided":
                raise ValueError(f"Unknown guided lesson: {state['lesson_id']}")
            concept = lesson.concepts[concept_index]
            if concept.lecture_script:
                response = concept.lecture_script
                emotion = "neutral"
                # Guided courses are compiled presentation assets. Keep the
                # delivery fixed so every normal run can reuse the same media.
                speech_rate = 1.0
            else:
                plan = self.llm.present_lecture_section(
                    lesson_title=lesson.title,
                    concept=concept,
                    section_number=concept_index + 1,
                    section_total=len(lesson.concepts),
                    profile=state.get("profile", {}),
                )
                response = plan.reply_text
                emotion = plan.emotion
                speech_rate = plan.speech_rate
            if include_feedback and state.get("evaluation_feedback"):
                response = f"{state['evaluation_feedback']}\n\n{response}"
            checkpoint = lesson.is_checkpoint(concept_index)
            if checkpoint:
                response = f"{response}\n\n检查题：{concept.question}"
            restarting = state.get("lesson_phase") == "complete"
            return {
                "messages": [{"role": "assistant", "content": response}],
                "response_text": response,
                "emotion": emotion,
                "speech_rate": speech_rate,
                "memory_update": {},
                "lesson_phase": "await_checkpoint" if checkpoint else "lecture",
                "concept_index": concept_index,
                "attempt_count": 0,
                "score": (
                    0
                    if restarting
                    else int(state.get("score", 0)) + (1 if include_feedback else 0)
                ),
                "current_question": concept.question if checkpoint else "",
                "media_cache_scope": (
                    f"{lesson.lesson_id}/section-{concept_index + 1}"
                    if not include_feedback
                    else (
                        f"{lesson.lesson_id}/section-{concept_index + 1}"
                        "-after-correct"
                    )
                ),
            }

        def present_guided_lesson(state: TeachingState) -> dict[str, Any]:
            return guided_section(state, 0)

        def advance_guided_lesson(state: TeachingState) -> dict[str, Any]:
            next_index = int(state.get("concept_index", 0)) + 1
            return guided_section(
                state,
                next_index,
                include_feedback=bool(state.get("evaluation_correct", False)),
            )

        def evaluate_answer(state: TeachingState) -> dict[str, Any]:
            lesson = get_lesson(state["lesson_id"])
            if lesson is None:
                raise ValueError(f"Unknown lesson: {state['lesson_id']}")
            concept = lesson.concepts[int(state.get("concept_index", 0))]
            if lesson.mode in {"guided", "interactive"}:
                correct = _matches_fixed_answer(
                    state["user_text"], concept.accepted_answers, concept.choices
                )
                if correct:
                    feedback = f"回答正确。{concept.reference_answer}"
                elif lesson.mode == "guided":
                    feedback = (
                        f"这个选项不正确。{concept.explanation}"
                        "请根据规则再选择一次。"
                    )
                elif int(state.get("attempt_count", 0)) == 0:
                    feedback = (
                        f"这次回答还不正确。提示：{concept.explanation}"
                        f"请再试一次：{concept.question}"
                    )
                else:
                    feedback = (
                        f"这道题的参考思路是：{concept.reference_answer}"
                        f"请根据这个思路再回答一次：{concept.question}"
                    )
                emotion = "happy" if correct else "neutral"
                speech_rate = 1.0
            else:
                evaluation = self.llm.evaluate_answer(
                    concept=concept,
                    user_text=state["user_text"],
                    attempt_count=int(state.get("attempt_count", 0)),
                    profile=state.get("profile", {}),
                    recent_messages=_message_dicts(state.get("messages", [])),
                )
                correct = evaluation.correct
                feedback = evaluation.feedback_text
                emotion = evaluation.emotion
                speech_rate = evaluation.speech_rate
            return {
                "evaluation_correct": correct,
                "evaluation_feedback": feedback,
                "emotion": emotion,
                "speech_rate": speech_rate,
                "memory_update": {},
                "media_cache_scope": "",
            }

        def remediate(state: TeachingState) -> dict[str, Any]:
            feedback = state["evaluation_feedback"]
            concept_index = int(state.get("concept_index", 0))
            attempt_tier = min(int(state.get("attempt_count", 0)) + 1, 2)
            return {
                "messages": [{"role": "assistant", "content": feedback}],
                "response_text": feedback,
                "lesson_phase": "await_answer",
                "attempt_count": int(state.get("attempt_count", 0)) + 1,
                "media_cache_scope": (
                    f"{state['lesson_id']}/concept-{concept_index + 1}"
                    f"-wrong-tier-{attempt_tier}"
                ),
            }

        def remediate_guided(state: TeachingState) -> dict[str, Any]:
            feedback = state["evaluation_feedback"]
            concept_index = int(state.get("concept_index", 0))
            answer = state.get("user_text", "").strip().lower()
            return {
                "messages": [{"role": "assistant", "content": feedback}],
                "response_text": feedback,
                "lesson_phase": "await_checkpoint",
                "attempt_count": int(state.get("attempt_count", 0)) + 1,
                "media_cache_scope": (
                    f"{state['lesson_id']}/checkpoint-{concept_index}-wrong-{answer}"
                ),
            }

        def advance_concept(state: TeachingState) -> dict[str, Any]:
            lesson = get_lesson(state["lesson_id"])
            if lesson is None:
                raise ValueError(f"Unknown lesson: {state['lesson_id']}")
            next_index = int(state.get("concept_index", 0)) + 1
            concept = lesson.concepts[next_index]
            response = (
                f"{state['evaluation_feedback']}\n\n"
                f"{concept.explanation}\n\n问题：{concept.question}"
            )
            return {
                "messages": [{"role": "assistant", "content": response}],
                "response_text": response,
                "emotion": "happy",
                "speech_rate": 1.0,
                "lesson_phase": "await_answer",
                "concept_index": next_index,
                "attempt_count": 0,
                "score": int(state.get("score", 0)) + 1,
                "current_question": concept.question,
                "media_cache_scope": (
                    f"{lesson.lesson_id}/section-{next_index + 1}-after-correct"
                ),
            }

        def complete_lesson(state: TeachingState) -> dict[str, Any]:
            lesson = get_lesson(state["lesson_id"])
            if lesson is None:
                raise ValueError(f"Unknown lesson: {state['lesson_id']}")
            final_score = min(
                lesson.assessment_total,
                int(state.get("score", 0)) + 1,
            )
            if lesson.mode == "guided":
                response = (
                    f"{state['evaluation_feedback']}\n\n"
                    f"你已经完成{lesson.title}，"
                    f"全部{lesson.assessment_total}个检查点都回答正确。"
                    "本课学习记录已经保存。"
                )
                emotion = "happy"
                speech_rate = 1.0
            else:
                response = (
                    f"{state['evaluation_feedback']}\n\n"
                    f"你已经完成{lesson.title}，掌握了"
                    f"{final_score}/{lesson.assessment_total}个知识点。"
                    "本课学习记录已经保存。"
                )
                emotion = "happy"
                speech_rate = 1.0
            return {
                "messages": [{"role": "assistant", "content": response}],
                "response_text": response,
                "emotion": emotion,
                "speech_rate": speech_rate,
                "lesson_phase": "complete",
                "attempt_count": 0,
                "score": final_score,
                "current_question": "",
                "media_cache_scope": f"{lesson.lesson_id}/complete",
            }

        def save_profile(state: TeachingState) -> dict[str, Any]:
            update = dict(state.get("memory_update", {}))
            lesson = get_lesson(state["lesson_id"])
            if lesson is not None and state.get("lesson_phase"):
                existing_progress = dict(
                    state.get("profile", {}).get("learning_progress", {})
                )
                concept_index = int(state.get("concept_index", 0))
                existing_progress[lesson.lesson_id] = {
                    "lesson_title": lesson.title,
                    "status": state["lesson_phase"],
                    "score": min(
                        lesson.assessment_total,
                        max(0, int(state.get("score", 0))),
                    ),
                    "total": lesson.assessment_total,
                    "current_concept": (
                        ""
                        if state["lesson_phase"] == "complete"
                        else lesson.concepts[concept_index].title
                    ),
                    "attempt_count": int(state.get("attempt_count", 0)),
                }
                update["learning_progress"] = existing_progress
            profile = self.profiles.merge(state["user_id"], update)
            return {"profile": profile}

        def route_after_profile(state: TeachingState) -> str:
            action = state.get("lesson_action", "user")
            if action in {"dynamic_start", "dynamic_advance"}:
                return "dynamic"
            if action == "dynamic_stop":
                return "dynamic_stop"
            lesson = get_lesson(state["lesson_id"])
            if lesson is None:
                return "chat"
            phase = state.get("lesson_phase", "")
            if lesson.mode == "guided":
                if action == "question":
                    return "chat"
                if not phase or action == "start":
                    return "guided_present"
                if phase == "lecture" and action == "advance":
                    return "guided_advance"
                if phase == "await_checkpoint" and action == "answer":
                    return "evaluate"
                return "chat"
            if action == "question":
                return "chat"
            if not phase or action == "start":
                return "present"
            if phase == "await_answer" and action in {"user", "answer"}:
                return "evaluate"
            if phase == "complete" and state["user_text"].strip() in {
                "重新学习",
                "重新开始",
                "再学一次",
            }:
                return "present"
            return "chat"

        def route_after_evaluation(state: TeachingState) -> str:
            if not state.get("evaluation_correct", False):
                lesson = get_lesson(state["lesson_id"])
                return "guided_remediate" if lesson and lesson.mode == "guided" else "remediate"
            lesson = get_lesson(state["lesson_id"])
            if lesson is None:
                return "remediate"
            if lesson.mode == "guided":
                if int(state.get("concept_index", 0)) + 1 >= len(lesson.concepts):
                    return "complete"
                return "guided_advance"
            if int(state.get("concept_index", 0)) + 1 >= len(lesson.concepts):
                return "complete"
            return "advance"

        builder = StateGraph(TeachingState)
        builder.add_node("load_profile", load_profile)
        builder.add_node("chat_reply", chat_reply)
        builder.add_node("dynamic_lecture", dynamic_lecture)
        builder.add_node("stop_dynamic_lecture", stop_dynamic_lecture)
        builder.add_node("present_concept", present_concept)
        builder.add_node("present_guided_lesson", present_guided_lesson)
        builder.add_node("advance_guided_lesson", advance_guided_lesson)
        builder.add_node("evaluate_answer", evaluate_answer)
        builder.add_node("remediate", remediate)
        builder.add_node("remediate_guided", remediate_guided)
        builder.add_node("advance_concept", advance_concept)
        builder.add_node("complete_lesson", complete_lesson)
        builder.add_node("save_profile", save_profile)
        builder.add_edge(START, "load_profile")
        builder.add_conditional_edges(
            "load_profile",
            route_after_profile,
            {
                "chat": "chat_reply",
                "dynamic": "dynamic_lecture",
                "dynamic_stop": "stop_dynamic_lecture",
                "present": "present_concept",
                "guided_present": "present_guided_lesson",
                "guided_advance": "advance_guided_lesson",
                "evaluate": "evaluate_answer",
            },
        )
        builder.add_conditional_edges(
            "evaluate_answer",
            route_after_evaluation,
            {
                "remediate": "remediate",
                "guided_remediate": "remediate_guided",
                "advance": "advance_concept",
                "guided_advance": "advance_guided_lesson",
                "complete": "complete_lesson",
            },
        )
        builder.add_edge("chat_reply", "save_profile")
        builder.add_edge("dynamic_lecture", "save_profile")
        builder.add_edge("stop_dynamic_lecture", "save_profile")
        builder.add_edge("present_concept", "save_profile")
        builder.add_edge("present_guided_lesson", "save_profile")
        builder.add_edge("advance_guided_lesson", "save_profile")
        builder.add_edge("remediate", "save_profile")
        builder.add_edge("remediate_guided", "save_profile")
        builder.add_edge("advance_concept", "save_profile")
        builder.add_edge("complete_lesson", "save_profile")
        builder.add_edge("save_profile", END)
        return builder.compile(checkpointer=self.checkpointer)

    def invoke(
        self,
        *,
        user_id: str,
        thread_id: str,
        lesson_id: str,
        text: str,
        lesson_action: str = "user",
        retrieval_context: str = "",
    ) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = self.graph.get_state(config)
        existing_user_id = snapshot.values.get("user_id") if snapshot.values else None
        if existing_user_id and existing_user_id != user_id:
            raise ValueError(
                f"thread_id {thread_id!r} already belongs to another user"
            )
        graph_input: dict[str, Any] = {
            "user_id": user_id,
            "lesson_id": lesson_id,
            "user_text": text,
            "lesson_action": lesson_action,
            "retrieval_context": retrieval_context,
        }
        if text and lesson_action not in {
            "start", "advance", "dynamic_advance", "dynamic_stop"
        }:
            graph_input["messages"] = [{"role": "user", "content": text}]
        result = self.graph.invoke(graph_input, config=config)
        return result

    def close(self) -> None:
        self.profiles.close()
        self._checkpoint_connection.close()

    def delete_thread(self, *, user_id: str, thread_id: str) -> bool:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = self.graph.get_state(config)
        existing_user_id = snapshot.values.get("user_id") if snapshot.values else None
        if existing_user_id and existing_user_id != user_id:
            raise ValueError(
                f"thread_id {thread_id!r} already belongs to another user"
            )
        self.checkpointer.delete_thread(thread_id)
        return existing_user_id is not None
