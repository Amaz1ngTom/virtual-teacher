from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LessonConcept:
    title: str
    objective: str
    explanation: str
    question: str
    accepted_answers: tuple[str, ...]
    reference_answer: str
    choices: tuple[str, ...] = ()
    lecture_script: str = ""


@dataclass(frozen=True)
class LessonDefinition:
    lesson_id: str
    title: str
    concepts: tuple[LessonConcept, ...]
    mode: str = "interactive"
    checkpoint_indices: tuple[int, ...] = ()

    def is_checkpoint(self, concept_index: int) -> bool:
        return concept_index in self.checkpoint_indices

    @property
    def assessment_total(self) -> int:
        if self.mode == "guided":
            return len(self.checkpoint_indices)
        return len(self.concepts)


PYTHON_CONCEPTS = (
    LessonConcept(
        title="变量与赋值",
        objective="理解变量保存值以及重新赋值",
        explanation="变量可以理解为带名字的盒子，等号把右侧的值放进左侧变量。重新赋值会更新盒子里的值。",
        question="执行 x = 3，然后执行 x = x + 2，最后 x 等于多少？",
        accepted_answers=("5", "五"),
        reference_answer="x最后等于5，因为先保存3，再用3加2重新赋值。",
        choices=("4", "5", "6"),
        lecture_script=(
            "欢迎学习Python变量基础。变量可以理解为一个带名字的盒子，等号会把右侧的值保存到左侧变量中。"
            "例如执行x等于3，变量x就保存了数字3；再执行x等于x加2，就会先读取3，计算得到5，再把5存回x。"
            "这就是变量赋值和重新赋值的基本过程。"
        ),
    ),
    LessonConcept(
        title="变量命名",
        objective="识别合法且清晰的Python变量名",
        explanation="Python变量名可以包含字母、数字和下划线，但不能以数字开头，也不能使用class等关键字。",
        question="下面哪个是合法的Python变量名：2name、user_name、class？",
        accepted_answers=("user_name",),
        reference_answer="user_name合法；2name以数字开头，class是Python关键字。",
        choices=("2name", "user_name", "class"),
        lecture_script=(
            "接下来学习变量命名。Python变量名可以包含字母、数字和下划线，但不能以数字开头。"
            "此外，class这类Python关键字也不能作为变量名。"
            "例如user_name是合法且含义清晰的变量名，而2name和class都不合法。"
        ),
    ),
    LessonConcept(
        title="变量类型可以变化",
        objective="理解Python变量可以先后引用不同类型的值",
        explanation="Python是动态类型语言，同一个变量可以先保存整数，之后再保存字符串。变量当前的类型由它现在引用的值决定。",
        question='先执行 x = 10，再执行 x = "hello"，此时 type(x).__name__ 是什么？',
        accepted_answers=("str", "字符串", "string"),
        reference_answer="结果是str，因为x当前保存的是字符串hello。",
        choices=("int", "str", "float"),
        lecture_script=(
            "最后学习Python的动态类型。一个变量可以先保存整数，之后再保存字符串，变量当前的类型由它现在引用的值决定。"
            "例如先执行x等于10，再执行x等于hello，此时x保存的是字符串。"
            "因此查看x的类型名称时，结果会是str。"
        ),
    ),
)


PYTHON_BASICS = LessonDefinition(
    lesson_id="python-basics",
    title="Python变量基础互动练习",
    concepts=PYTHON_CONCEPTS,
)


PYTHON_LECTURE = LessonDefinition(
    lesson_id="python-lecture",
    title="Python变量基础课程讲授",
    concepts=PYTHON_CONCEPTS,
    mode="guided",
    # Let the first two sections play continuously, then pause twice at the
    # most useful retrieval-practice points.
    checkpoint_indices=(1, 2),
)


LESSONS = {
    PYTHON_BASICS.lesson_id: PYTHON_BASICS,
    PYTHON_LECTURE.lesson_id: PYTHON_LECTURE,
}

BUILTIN_LESSON_IDS = frozenset(LESSONS)


def lesson_from_blueprint(lesson_id: str, blueprint: dict[str, Any]) -> LessonDefinition:
    """Compile one reviewed course blueprint into a deterministic guided lesson."""
    raw_lessons = blueprint.get("lessons", [])
    concepts: list[LessonConcept] = []
    for raw_lesson in raw_lessons:
        checkpoint = raw_lesson["checkpoint"]
        script = "\n\n".join(
            str(block["script"]).strip()
            for block in raw_lesson.get("teaching_blocks", [])
            if str(block.get("script", "")).strip()
        )
        correct_answer = str(checkpoint["correct_answer"]).strip()
        concepts.append(
            LessonConcept(
                title=str(raw_lesson["title"]).strip(),
                objective=str(raw_lesson["objective"]).strip(),
                explanation=str(checkpoint["explanation"]).strip(),
                question=str(checkpoint["question"]).strip(),
                accepted_answers=(correct_answer,),
                reference_answer=str(checkpoint["explanation"]).strip(),
                choices=tuple(str(choice).strip() for choice in checkpoint["choices"]),
                lecture_script=script,
            )
        )
    if not concepts:
        raise ValueError("Published course has no lessons")
    section_total = len(concepts)
    checkpoint_total = section_total if section_total <= 2 else 2 if section_total <= 4 else 3
    checkpoint_indices = tuple(
        sorted(
            {
                ((step * section_total + checkpoint_total - 1) // checkpoint_total) - 1
                for step in range(1, checkpoint_total + 1)
            }
        )
    )
    return LessonDefinition(
        lesson_id=lesson_id,
        title=str(blueprint["course_title"]).strip(),
        concepts=tuple(concepts),
        mode="guided",
        checkpoint_indices=checkpoint_indices,
    )


def register_lesson(lesson: LessonDefinition) -> None:
    if lesson.lesson_id in BUILTIN_LESSON_IDS:
        raise ValueError("Built-in lessons cannot be replaced")
    LESSONS[lesson.lesson_id] = lesson


def register_published_course(record: dict[str, Any]) -> LessonDefinition:
    lesson = lesson_from_blueprint(
        str(record["lesson_id"]), dict(record["blueprint"])
    )
    register_lesson(lesson)
    return lesson


def unregister_published_course(lesson_id: str) -> bool:
    """Remove one runtime-loaded imported course without touching built-ins."""
    if lesson_id in BUILTIN_LESSON_IDS:
        raise ValueError("Built-in lessons cannot be removed")
    return LESSONS.pop(lesson_id, None) is not None


def list_lessons() -> list[dict[str, Any]]:
    return [
        {
            "lesson_id": lesson.lesson_id,
            "title": lesson.title,
            "mode": lesson.mode,
            "built_in": lesson.lesson_id in BUILTIN_LESSON_IDS,
            "section_total": len(lesson.concepts),
        }
        for lesson in LESSONS.values()
    ]


def get_lesson(lesson_id: str) -> LessonDefinition | None:
    return LESSONS.get(lesson_id)
