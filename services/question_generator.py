import json
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from config import MAX_QUESTIONS, MAX_RETRIES, OLLAMA_MODEL
from services.paper_patterns import QuestionSlot
from services.validator import DIFFICULTIES, ValidationError, validate_batch


SOURCE_CHAR_BUDGET = 30_000
MIN_RETRY_SOURCE_BUDGET = 8_000


class GenerationError(RuntimeError):
    pass


def _response_schema(type_counts: dict[str, int], difficulty: str, slots: tuple[QuestionSlot, ...]) -> dict:
    count = sum(type_counts.values())
    fields = {
        "type": {"enum": list(type_counts)},
        "difficulty": {"enum": list(DIFFICULTIES) if difficulty == "Mixed" else [difficulty]},
        "question": {"type": "string"},
        "options": {"type": "null"},
        "answer": {"type": "string"},
    }
    if "MCQ" in type_counts:
        options = {
            "type": "object",
            "properties": {letter: {"type": "string"} for letter in "ABCD"},
            "required": list("ABCD"),
            "additionalProperties": False,
        }
        fields["options"] = {"anyOf": [options, {"type": "null"}]} if len(type_counts) > 1 else options
    if slots:
        fields["slot"] = {"enum": [slot.number for slot in slots]}
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": fields,
                    "required": list(fields),
                    "additionalProperties": False,
                },
            },
        },
        "required": ["questions"],
        "additionalProperties": False,
    }


def _request_ollama(prompt: str, model: str, schema: dict) -> tuple[str, str | None]:
    request = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0.3, "num_ctx": 16384},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=300) as response:
            payload = json.load(response)
            return payload["message"]["content"], payload.get("done_reason")
    except HTTPError as exc:
        if exc.code == 404:
            raise GenerationError(f"Ollama could not find {model}. Check `ollama list`.") from exc
        raise GenerationError(f"Ollama returned HTTP {exc.code} while running {model}.") from exc
    except TimeoutError as exc:
        raise GenerationError("Ollama timed out. Try fewer questions or a shorter PDF.") from exc
    except URLError as exc:
        raise GenerationError("Could not reach Ollama. Open Ollama on this computer and try again.") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise GenerationError("Ollama returned an unexpected API response.") from exc


def _source_excerpt(chunks: list[str], budget: int) -> str:
    separator = "\n\n--- NEXT SOURCE SECTION ---\n\n"
    available = max(len(chunks), budget - len(separator) * (len(chunks) - 1))
    excerpts = []
    by_length = sorted(enumerate(chunks), key=lambda item: len(item[1]))
    for index, (original_index, text) in enumerate(by_length):
        allowance = available // (len(chunks) - index)
        excerpt = text[:allowance]
        if len(excerpt) < len(text):
            # Trim at a word boundary when possible so the excerpt ends cleanly.
            excerpt = excerpt.rsplit(maxsplit=1)[0] if len(excerpt.split()) > 1 else excerpt
        excerpts.append((original_index, excerpt))
        available -= len(excerpt)
    return separator.join(excerpt for _, excerpt in sorted(excerpts))


def generate_questions(
    chunks: list[str],
    type_counts: dict[str, int],
    difficulty: str,
    *,
    slots: tuple[QuestionSlot, ...] = (),
    existing_questions: set[str] | None = None,
) -> list[dict]:
    if not chunks or not 1 <= sum(type_counts.values()) <= MAX_QUESTIONS:
        raise GenerationError(f"Provide source text and request 1 to {MAX_QUESTIONS} questions.")

    source_budget = SOURCE_CHAR_BUDGET
    schema = _response_schema(type_counts, difficulty, slots)
    slot_instructions = ""
    if slots:
        slot_lines = "\n".join(
            f"{index}. {slot.number}, {slot.kind}, {slot.marks:g} marks"
            + (f", group: {slot.unit}" if slot.unit else "")
            for index, slot in enumerate(slots, 1)
        )
        slot_instructions = (
            "Write one question per slot in the exact order below. In each object, "
            "include a 'slot' string equal to its question number, such as 'Q1(a)'. Match the depth to "
            "the marks. Do not include slot numbers or marks inside question text.\n"
            f"{slot_lines}\n"
        )
        if any(slot.unit for slot in slots):
            slot_instructions += (
                "For unit groups, use matching unit headings in the source when available. "
                "Otherwise, assign a distinct topic from the source to each unit group. "
                "Both alternatives in a unit must cover that unit's topic.\n"
            )

    last_error = ""
    for _ in range(MAX_RETRIES + 1):
        source = _source_excerpt(chunks, source_budget)
        prompt = (
            "Create educational assessment questions using only the SOURCE TEXT below. "
            "Do not invent facts outside it. Write in English. "
            "Write each question as a standalone exam question. Name the topic directly "
            "and include any context the student needs within the question itself. "
            "Do not refer to the source text, passage, PDF, or document in the question. "
            "Avoid phrases like 'according to the text', 'based on the passage', and "
            "'as mentioned above'. For example, write 'What is the role of chlorophyll "
            "in photosynthesis?' when the source supports that question. "
            "Return a JSON object with one 'questions' array. Each question object needs "
            "'type', 'difficulty', 'question', 'options', and 'answer'. "
            "Use types exactly 'MCQ', 'Short answer', or 'Long answer'. "
            "For MCQ, options is an object with distinct A, B, C, D strings and answer is "
            "the correct letter. For other types, options is null and answer is a concise "
            "model answer grounded in the source. Keep short answers brief and long answers focused "
            "on the main points expected for the marks. Avoid repeated questions.\n\n"
            f"Exact counts by type: {json.dumps(type_counts)}\n"
            f"Difficulty: {difficulty}. If Mixed, vary Easy, Medium, and Hard where possible.\n"
            f"{slot_instructions}"
            f"Previous validation issue to correct: {last_error or 'none'}\n\n"
            f"SOURCE TEXT:\n{source}"
        )
        try:
            response_text, stop_reason = _request_ollama(prompt, OLLAMA_MODEL, schema)
            payload = json.loads(response_text if isinstance(response_text, str) else "")
            questions = validate_batch(payload, type_counts, difficulty, existing_questions or set())
            if slots:
                labels_and_types = [(item.get("slot"), item["type"]) for item in payload["questions"]]
                if labels_and_types != [(slot.number, slot.kind) for slot in slots]:
                    raise ValidationError("Return each slot label and type in the requested order.")
            return questions
        except json.JSONDecodeError:
            last_error = (
                "Qwen reached its output limit before completing the paper."
                if stop_reason == "length"
                else "Qwen did not return complete, valid JSON."
            )
            source_budget = max(MIN_RETRY_SOURCE_BUDGET, source_budget // 2)
        except ValidationError as exc:
            last_error = str(exc)
    raise GenerationError(
        f"Could not create the paper after {MAX_RETRIES + 1} attempts. {last_error} "
        "Try a smaller selection of study material or fewer questions in Standard mode."
    )
