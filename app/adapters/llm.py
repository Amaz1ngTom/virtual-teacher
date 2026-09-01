from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from openai import BadRequestError, OpenAI

from app.llm_trace import LLMTraceWriter
from app.lessons import LessonConcept
from app.models import EvaluationPlan, ReplyPlan
from app.prompts import (
    build_chat_system_prompt,
    build_concept_system_prompt,
    build_evaluation_system_prompt,
    build_lecture_section_system_prompt,
    build_summary_system_prompt,
    build_dynamic_lecture_system_prompt,
)


class LLMResponseFormatError(RuntimeError):
    """The provider answered, but its structured payload was unusable."""


class LLMProviderError(RuntimeError):
    """The upstream model request failed before a usable answer arrived."""


class TeachingLLM(Protocol):
    def generate(
        self,
        user_text: str,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
        source_context: str = "",
    ) -> ReplyPlan: ...

    def present_concept(
        self,
        *,
        lesson_title: str,
        concept: LessonConcept,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan: ...

    def present_lecture_section(
        self,
        *,
        lesson_title: str,
        concept: LessonConcept,
        section_number: int,
        section_total: int,
        profile: dict[str, Any],
    ) -> ReplyPlan: ...

    def evaluate_answer(
        self,
        *,
        concept: LessonConcept,
        user_text: str,
        attempt_count: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> EvaluationPlan: ...

    def complete_lesson(
        self,
        *,
        lesson_title: str,
        score: int,
        total: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan: ...

    def generate_dynamic_lecture(
        self,
        *,
        topic: str,
        section_number: int,
        section_total: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan: ...


class RuleBasedTeachingLLM:
    """Offline development fallback.

    It makes state, memory, TTS and FLOAT integration testable before an LLM
    account is configured. It is intentionally not presented as the final AI.
    """

    def generate(
        self,
        user_text: str,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
        source_context: str = "",
    ) -> ReplyPlan:
        update: dict[str, Any] = {}
        text = user_text.strip()

        name_match = re.search(r"我叫\s*([\u4e00-\u9fffA-Za-z0-9_-]{1,20})", text)
        if source_context.strip():
            reply = (
                "已检索到与问题相关的教材原文，来源页码会显示在回答下方。"
                "当前是离线规则模式；切换到千问后会依据这些片段组织完整回答。"
            )
        elif name_match:
            update["name"] = name_match.group(1)

        if "慢一点" in text or "说慢" in text or "语速慢" in text:
            update["speech_rate"] = 0.8
        elif "快一点" in text or "说快" in text or "语速快" in text:
            update["speech_rate"] = 1.15

        merged = {**profile, **update}
        rate = float(merged.get("speech_rate", 1.0))
        name = merged.get("name")

        if name_match:
            reply = f"你好，{name}。我已经记住你的名字了。我们可以开始今天的学习。"
        elif ("慢" in text and "语速" in text) or "慢一点" in text:
            reply = "好的，我会放慢语速，并在后续课程中继续使用这个偏好。"
        elif text in {"继续", "继续学习", "接着来"}:
            prefix = f"好的，{name}。" if name else "好的。"
            reply = prefix + "我们继续学习。请告诉我你今天想练习的主题。"
        else:
            prefix = f"{name}，" if name else ""
            reply = f"{prefix}我收到你的内容了：{text}。接下来我会用简短、清晰的方式和你互动。"

        return ReplyPlan(
            reply_text=reply,
            emotion="happy" if name_match else "neutral",
            speech_rate=rate,
            memory_update=update,
        ).normalized()

    def present_concept(
        self,
        *,
        lesson_title: str,
        concept: LessonConcept,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan:
        return ReplyPlan(
            reply_text=f"{concept.explanation}\n\n问题：{concept.question}",
            emotion="neutral",
            speech_rate=profile.get("speech_rate", 1.0),
        ).normalized()

    def present_lecture_section(
        self,
        *,
        lesson_title: str,
        concept: LessonConcept,
        section_number: int,
        section_total: int,
        profile: dict[str, Any],
    ) -> ReplyPlan:
        return ReplyPlan(
            reply_text=(
                f"第{section_number}部分，我们学习{concept.title}。"
                f"{concept.explanation}"
                f"举个例子，{concept.reference_answer}"
            ),
            emotion="neutral",
            speech_rate=profile.get("speech_rate", 1.0),
        ).normalized()

    def evaluate_answer(
        self,
        *,
        concept: LessonConcept,
        user_text: str,
        attempt_count: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> EvaluationPlan:
        normalized = user_text.strip().lower()
        correct = any(answer.lower() in normalized for answer in concept.accepted_answers)
        if correct:
            feedback = f"回答正确。{concept.reference_answer}"
        else:
            feedback = f"这次还不完全正确。请根据讲解再想一想。问题：{concept.question}"
        return EvaluationPlan(
            correct=correct,
            feedback_text=feedback,
            emotion="happy" if correct else "neutral",
            speech_rate=profile.get("speech_rate", 1.0),
        ).normalized()

    def complete_lesson(
        self,
        *,
        lesson_title: str,
        score: int,
        total: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan:
        return ReplyPlan(
            reply_text=f"你已经完成{lesson_title}，掌握了{score}/{total}个知识点。本课学习记录已经保存。",
            emotion="happy",
            speech_rate=profile.get("speech_rate", 1.0),
        ).normalized()

    def generate_dynamic_lecture(
        self,
        *,
        topic: str,
        section_number: int,
        section_total: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan:
        ending = "最后做一个简短总结。" if section_number == section_total else "下面继续展开这个主题。"
        return ReplyPlan(
            reply_text=(
                f"第{section_number}部分，我们继续讲解{topic}。"
                "这一部分会集中说明一个核心知识点，并用一个具体例子帮助理解。"
                f"{ending}"
            ),
            emotion="neutral",
            speech_rate=profile.get("speech_rate", 1.0),
        ).normalized()


class QwenTeachingLLM:
    """Alibaba Cloud Model Studio adapter via its OpenAI-compatible API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 90,
        debug: bool = False,
        log_dir: Path | None = None,
    ):
        if not base_url or not api_key or not model:
            raise ValueError(
                "qwen mode requires VT_QWEN_BASE_URL, VT_QWEN_API_KEY "
                "and VT_QWEN_MODEL"
            )
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.model = model
        self.trace = LLMTraceWriter(
            enabled=debug,
            directory=log_dir or Path.cwd() / "logs",
        )

    @staticmethod
    def _response_record(completion: Any) -> dict[str, Any]:
        choice = completion.choices[0]
        usage = getattr(completion, "usage", None)
        if usage is not None and hasattr(usage, "model_dump"):
            usage = usage.model_dump(mode="json")
        return {
            "id": getattr(completion, "id", None),
            "request_id": getattr(completion, "_request_id", None),
            "model": getattr(completion, "model", None),
            "finish_reason": getattr(choice, "finish_reason", None),
            "content": choice.message.content,
            "usage": usage,
        }

    def _complete_json(
        self,
        *,
        operation: str,
        system_prompt: str,
        recent_messages: list[dict[str, str]],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(recent_messages[-8:])
        request = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "extra_body": {"enable_thinking": False},
        }
        call_id = uuid.uuid4().hex
        started = time.perf_counter()
        used_json_mode = True
        try:
            try:
                completion = self.client.chat.completions.create(**request)
            except BadRequestError:
                used_json_mode = False
                fallback_request = dict(request)
                fallback_request.pop("response_format")
                completion = self.client.chat.completions.create(**fallback_request)
        except Exception as exc:
            self.trace.write(
                {
                    "call_id": call_id,
                    "operation": operation,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "request": request,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            )
            raise LLMProviderError(f"教学模型调用失败: {exc}") from exc

        response = self._response_record(completion)
        self.trace.write(
            {
                "call_id": call_id,
                "operation": operation,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "json_mode": used_json_mode,
                "request": request,
                "response": response,
            }
        )
        content = response["content"]
        if not content:
            raise LLMResponseFormatError("语言模型返回了空响应")
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseFormatError("语言模型没有返回有效的 JSON 对象") from exc
        # Some otherwise valid Qwen responses wrap the requested object in a
        # one-item array. Unwrap locally instead of spending tokens on a retry.
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
            data = data[0]
        if not isinstance(data, dict):
            raise LLMResponseFormatError("语言模型返回的 JSON 顶层必须是对象")
        return data

    def generate(
        self,
        user_text: str,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
        source_context: str = "",
    ) -> ReplyPlan:
        data = self._complete_json(
            operation="chat",
            system_prompt=build_chat_system_prompt(profile, source_context),
            recent_messages=recent_messages,
        )
        reply_text = self._required_text(data, "reply_text")
        allowed_keys = {"name", "speech_rate", "teaching_style", "favorite_topics"}
        raw_update = data.get("memory_update", {})
        if not isinstance(raw_update, dict):
            raise LLMResponseFormatError("memory_update 必须是 JSON 对象")
        memory_update = {
            key: value
            for key, value in raw_update.items()
            if key in allowed_keys
        }
        return ReplyPlan(
            reply_text=reply_text,
            emotion=data.get("emotion", "neutral"),
            speech_rate=data.get("speech_rate", profile.get("speech_rate", 1.0)),
            memory_update=memory_update,
        ).normalized()

    @staticmethod
    def _required_text(data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise LLMResponseFormatError(f"语言模型响应缺少有效字段: {key}")
        return value

    @staticmethod
    def _reply_from_data(
        data: dict[str, Any], profile: dict[str, Any]
    ) -> ReplyPlan:
        return ReplyPlan(
            reply_text=QwenTeachingLLM._required_text(data, "reply_text"),
            emotion=data.get("emotion", "neutral"),
            speech_rate=data.get("speech_rate", profile.get("speech_rate", 1.0)),
            memory_update={},
        ).normalized()

    def present_concept(
        self,
        *,
        lesson_title: str,
        concept: LessonConcept,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan:
        data = self._complete_json(
            operation="present_concept",
            system_prompt=build_concept_system_prompt(
                profile=profile,
                lesson_title=lesson_title,
                concept_title=concept.title,
                objective=concept.objective,
                explanation=concept.explanation,
                question=concept.question,
            ),
            recent_messages=recent_messages,
        )
        return self._reply_from_data(data, profile)

    def present_lecture_section(
        self,
        *,
        lesson_title: str,
        concept: LessonConcept,
        section_number: int,
        section_total: int,
        profile: dict[str, Any],
    ) -> ReplyPlan:
        data = self._complete_json(
            operation="present_lecture_section",
            system_prompt=build_lecture_section_system_prompt(
                profile=profile,
                lesson_title=lesson_title,
                concept_title=concept.title,
                objective=concept.objective,
                explanation=concept.explanation,
                reference_answer=concept.reference_answer,
                section_number=section_number,
                section_total=section_total,
            ),
            recent_messages=[],
        )
        return self._reply_from_data(data, profile)

    def evaluate_answer(
        self,
        *,
        concept: LessonConcept,
        user_text: str,
        attempt_count: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> EvaluationPlan:
        data = self._complete_json(
            operation="evaluate_answer",
            system_prompt=build_evaluation_system_prompt(
                profile=profile,
                concept_title=concept.title,
                question=concept.question,
                reference_answer=concept.reference_answer,
                attempt_count=attempt_count,
            ),
            recent_messages=recent_messages,
            temperature=0.1,
        )
        return EvaluationPlan(
            correct=data.get("correct", False),
            feedback_text=data["feedback_text"],
            emotion=data.get("emotion", "neutral"),
            speech_rate=data.get("speech_rate", profile.get("speech_rate", 1.0)),
        ).normalized()

    def complete_lesson(
        self,
        *,
        lesson_title: str,
        score: int,
        total: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan:
        data = self._complete_json(
            operation="complete_lesson",
            system_prompt=build_summary_system_prompt(
                profile=profile,
                lesson_title=lesson_title,
                score=score,
                total=total,
            ),
            recent_messages=recent_messages,
        )
        return self._reply_from_data(data, profile)

    def generate_dynamic_lecture(
        self,
        *,
        topic: str,
        section_number: int,
        section_total: int,
        profile: dict[str, Any],
        recent_messages: list[dict[str, str]],
    ) -> ReplyPlan:
        section_messages = [*recent_messages]
        section_messages.append(
            {
                "role": "user",
                "content": (
                    f"现在请讲“{topic}”的第{section_number}/{section_total}节。"
                    "严格遵循系统指定的本节侧重点，不要复述上一节。"
                ),
            }
        )
        data = self._complete_json(
            operation="dynamic_lecture",
            system_prompt=build_dynamic_lecture_system_prompt(
                profile=profile,
                topic=topic,
                section_number=section_number,
                section_total=section_total,
            ),
            recent_messages=section_messages,
        )
        return self._reply_from_data(data, profile)
