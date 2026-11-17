"""Check JSON shape and simple question constraints; no factual verification."""

import re
from collections import Counter


QUESTION_TYPES = ("MCQ", "Short answer", "Long answer")
DIFFICULTIES = ("Easy", "Medium", "Hard")


class ValidationError(ValueError):
    pass


def _nonempty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a nonempty string.")
    return value.strip()


def _question_key(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold())


def validate_batch(
    payload: object,
    expected_types: dict[str, int],
    difficulty: str,
    existing_questions: set[str],
) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list):
        raise ValidationError("The response must contain a questions array.")
    questions = payload["questions"]
    if len(questions) != sum(expected_types.values()):
        raise ValidationError("The question count does not match the request.")

    counts: Counter[str] = Counter()
    seen = set(existing_questions)
    normalized: list[dict] = []
    for index, item in enumerate(questions, 1):
        if not isinstance(item, dict):
            raise ValidationError(f"Question {index} must be an object.")
        kind = _nonempty(item.get("type"), f"Question {index} type")
        if kind not in QUESTION_TYPES or kind not in expected_types:
            raise ValidationError(f"Question {index} has an unrequested type.")
        level = _nonempty(item.get("difficulty"), f"Question {index} difficulty")
        if level not in DIFFICULTIES or (difficulty != "Mixed" and level != difficulty):
            raise ValidationError(f"Question {index} has an invalid difficulty.")
        prompt = _nonempty(item.get("question"), f"Question {index} text")
        key = _question_key(prompt)
        if len(key) < 8 or key in seen:
            raise ValidationError(f"Question {index} is too short or duplicates another question.")
        seen.add(key)
        answer = _nonempty(item.get("answer"), f"Question {index} answer")
        options = item.get("options")
        if kind == "MCQ":
            if not isinstance(options, dict) or set(options) != {"A", "B", "C", "D"}:
                raise ValidationError(f"Question {index} needs options A through D.")
            options = {letter: _nonempty(options[letter], f"Option {letter}") for letter in "ABCD"}
            if len({value.casefold() for value in options.values()}) != 4:
                raise ValidationError(f"Question {index} has duplicate options.")
            if answer not in options:
                raise ValidationError(f"Question {index} answer must be an option letter.")
        elif options not in (None, {}):
            raise ValidationError(f"Question {index} must not include MCQ options.")
        else:
            options = None

        counts[kind] += 1
        normalized.append({
            "type": kind,
            "difficulty": level,
            "question": prompt,
            "options": options,
            "answer": answer,
        })
    if counts != Counter(expected_types):
        raise ValidationError("The counts for the requested question types do not match.")
    return normalized


def question_keys(questions: list[dict]) -> set[str]:
    return {_question_key(item["question"]) for item in questions}

