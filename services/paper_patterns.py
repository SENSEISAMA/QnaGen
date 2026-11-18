from collections import Counter
from dataclasses import dataclass
from string import ascii_lowercase


@dataclass(frozen=True)
class QuestionSlot:
    number: str
    kind: str
    marks: float
    unit: str = ""

    @property
    def label(self) -> str:
        return f"{self.number} · {self.marks:g} marks"


@dataclass(frozen=True)
class QuestionGroup:
    title: str
    instruction: str
    slots: tuple[QuestionSlot, ...]
    maximum_marks: float


@dataclass(frozen=True)
class PaperPattern:
    label: str
    duration: str
    summary: str
    groups: tuple[QuestionGroup, ...]
    exam_title: str
    table_layout: bool = False

    @property
    def slots(self) -> tuple[QuestionSlot, ...]:
        return tuple(slot for group in self.groups for slot in group.slots)

    @property
    def maximum_marks(self) -> float:
        return sum(group.maximum_marks for group in self.groups)

    @property
    def type_counts(self) -> dict[str, int]:
        return dict(Counter(slot.kind for slot in self.slots))

    def check_questions(self, questions: list[dict]) -> None:
        if [question["type"] for question in questions] != [slot.kind for slot in self.slots]:
            raise ValueError("Question count or order no longer matches the selected paper pattern.")


def _parts(number: int, count: int, kind: str, marks: float) -> tuple[QuestionSlot, ...]:
    return tuple(QuestionSlot(f"Q{number}({letter})", kind, marks) for letter in ascii_lowercase[:count])


def _ipu_end_term() -> PaperPattern:
    units = ("I", "II", "III", "IV")
    groups = [
        QuestionGroup("Question 1", "Answer all five parts.", _parts(1, 5, "Short answer", 5), 25)
    ]
    for index, unit in enumerate(units):
        first = 2 + index * 2
        slots = tuple(QuestionSlot(f"Q{number}", "Long answer", 12.5, f"Unit {unit}")
                      for number in (first, first + 1))
        groups.append(QuestionGroup(f"Unit {unit}", "Attempt either question.", slots, 12.5))
    return PaperPattern(
        "IPU · End term (adapted)", "3 Hrs.",
        "Q1 is compulsory. Choose one question from each of four units. Each unit option is a single 12.5-mark question.",
        tuple(groups),
        exam_title="END TERM EXAMINATION",
    )


PAPER_PATTERNS = {
    "IPU · Midterm": PaperPattern(
        "IPU · Midterm", "1½ Hrs.", "Q1 is compulsory. Attempt any two of Q2, Q3 and Q4.",
        (
            QuestionGroup("Question 1", "Answer all five parts.", _parts(1, 5, "Short answer", 2), 10),
            QuestionGroup(
                "Questions 2–4",
                "Choose any two questions. Answer both parts of each chosen question.",
                tuple(slot for number in range(2, 5) for slot in _parts(number, 2, "Short answer", 5)),
                20,
            ),
        ),
        exam_title="MID TERM EXAMINATION",
        table_layout=True,
    ),
    "IPU · End term (adapted)": _ipu_end_term(),
}
