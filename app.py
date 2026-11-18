"""Streamlit entry point for the QnaGen PDF-to-question-paper workflow."""

from time import monotonic
from uuid import uuid4

import streamlit as st

import config
import services.pdf_builder as pdf_builder
import services.pdf_extractor as pdf_extractor
from config import (
    CHUNK_CHARS,
    MAX_CHUNKS,
    MAX_FILE_MB,
    MAX_QUESTIONS,
    OLLAMA_MODEL,
)
from services.paper_patterns import PAPER_PATTERNS
from services.question_generator import GenerationError, generate_questions
from services.text_preprocessor import chunk_text, clean_text, select_study_chunks
from services.validator import (
    QUESTION_TYPES,
    ValidationError,
    question_keys,
    validate_batch,
)


st.set_page_config(page_title="QnaGen", page_icon="📄", layout="wide")
st.title("QnaGen", anchor=False, text_alignment="center")
st.caption(
    "Create a practice paper and answer key from your study material.",
    text_alignment="center",
)


@st.cache_data(show_spinner=False, max_entries=32)
def prepare_pdf(data: bytes, remaining_pages: int) -> tuple[str, int, list[str]]:
    extracted, page_count = pdf_extractor.extract_pdf_text(data, MAX_FILE_MB, remaining_pages)
    cleaned = clean_text(extracted)
    if len(cleaned) < 100:
        raise pdf_extractor.PDFInputError("The PDF has too little usable text to generate reliable questions.")
    return cleaned, page_count, chunk_text(cleaned, CHUNK_CHARS)


def clear_output() -> None:
    st.session_state.pop("qnagen_output", None)
    st.session_state.pop("qnagen_draft", None)
    st.session_state.pop("qnagen_notice", None)


def clear_export() -> None:
    st.session_state.pop("qnagen_output", None)


def keep_question_mix_within_total() -> None:
    """Keep the editable type counts valid when the total or MCQ count changes."""
    total = st.session_state["total_questions"]
    st.session_state["mcq_count"] = min(st.session_state["mcq_count"], total)
    st.session_state["short_count"] = min(
        st.session_state["short_count"], total - st.session_state["mcq_count"]
    )
    clear_output()


upload_col, settings_col = st.columns([1, 1.2], gap="large")
with upload_col, st.container(border=True):
    st.subheader("Study material")
    uploads = st.file_uploader(
        "Upload study PDFs", type=["pdf"], accept_multiple_files=True,
        max_upload_size=MAX_FILE_MB,
        on_change=clear_output,
    )
    max_pages = config.MAX_COMBINED_PAGES
    st.caption(f"Combined upload limit: {MAX_FILE_MB} MB and {max_pages} pages")
    st.info(f"**Up to {MAX_QUESTIONS} questions per paper.**")
    documents = []
    source_error = False
    selected = []
    if uploads:
        bytes_per_mb = 1024 * 1024
        total_bytes = sum(upload.size for upload in uploads)
        st.caption(f"Selected: {len(uploads)} · {total_bytes / bytes_per_mb:.2f} / {MAX_FILE_MB} MB")
        if total_bytes > MAX_FILE_MB * bytes_per_mb:
            source_error = True
            st.error(f"The PDFs exceed {MAX_FILE_MB} MB combined. Remove a file to continue.")
        else:
            total_pages = 0
            for upload in uploads:
                try:
                    cleaned, page_count, chunks = prepare_pdf(upload.getvalue(), max_pages - total_pages)
                    documents.append((upload.name, cleaned, page_count, chunks))
                    total_pages += page_count
                except pdf_extractor.PDFPageLimitError:
                    source_error = True
                    st.error(f"The PDFs exceed {max_pages} pages combined. Remove a file to continue.")
                    break
                except pdf_extractor.PDFInputError as exc:
                    source_error = True
                    st.error(f"{upload.name}: {exc}")
        if documents and not source_error:
            st.caption(f"Total pages: {total_pages} / {max_pages}")
            selected, sampled = select_study_chunks(
                [document[3] for document in documents], MAX_CHUNKS, CHUNK_CHARS,
            )
            if sampled:
                st.caption("Generation will use selected excerpts from each PDF.")
        if documents:
            with st.expander("Preview extracted text"):
                preview_index = st.selectbox(
                    "Study PDF", range(len(documents)),
                    format_func=lambda index: f"{index + 1}. {documents[index][0]}",
                )
                _, cleaned, page_count, _ = documents[preview_index]
                st.caption(f"{page_count} pages · {len(cleaned):,} characters extracted")
                st.text_area(
                    "First 5,000 characters", value=cleaned[:5000],
                    height=240, disabled=True,
                )

with settings_col, st.container(border=True):
    st.subheader("Paper setup")
    pattern_col, difficulty_col = st.columns([2, 1])
    pattern_name = pattern_col.selectbox("Paper pattern", ["Standard", *PAPER_PATTERNS], on_change=clear_output)
    difficulty = difficulty_col.selectbox(
        "Difficulty", ["Easy", "Medium", "Hard", "Mixed"], index=3, on_change=clear_output,
    )
    pattern = PAPER_PATTERNS.get(pattern_name)
    if pattern:
        slots = pattern.slots
        total_questions = len(slots)
        type_counts = pattern.type_counts
    else:
        slots = ()
        if "total_questions" not in st.session_state:
            st.session_state["total_questions"] = 6
        if st.session_state["total_questions"] > MAX_QUESTIONS:
            st.session_state["total_questions"] = MAX_QUESTIONS
        st.session_state.setdefault("mcq_count", 2)
        st.session_state.setdefault("short_count", 2)
        if (
            st.session_state["mcq_count"] + st.session_state["short_count"]
            > st.session_state["total_questions"]
        ):
            keep_question_mix_within_total()
        keep_mix = st.columns(3)
        total_questions = keep_mix[0].number_input(
            "Total questions", min_value=1, max_value=MAX_QUESTIONS, step=1,
            key="total_questions", on_change=keep_question_mix_within_total,
        )
        mcq_count = keep_mix[1].number_input(
            "MCQs", min_value=0, max_value=total_questions, step=1,
            key="mcq_count", on_change=keep_question_mix_within_total,
        )
        short_count = keep_mix[2].number_input(
            "Short answer", min_value=0, max_value=total_questions - mcq_count,
            step=1, key="short_count", on_change=clear_output,
        )
        long_count = total_questions - mcq_count - short_count
        st.caption(f"Long answer: {long_count}")
        type_counts = {"MCQ": mcq_count, "Short answer": short_count, "Long answer": long_count}
    exam_header = None
    with st.expander("Paper options"):
        if pattern:
            paper_title = pattern.exam_title
            code_col, subject_col = st.columns([1, 2])
            exam_header = pdf_builder.ExamHeader(
                paper_code=code_col.text_input(
                    "Paper code", max_chars=24, key="ipu_paper_code", on_change=clear_export,
                ).strip(),
                subject=subject_col.text_input(
                    "Subject", max_chars=95, key="ipu_subject", on_change=clear_export,
                ).strip(),
                session=st.text_input(
                    "Semester / exam session", max_chars=80, placeholder="e.g. 2nd Semester, April 2024",
                    key="ipu_session", on_change=clear_export,
                ).strip(),
            )
            st.caption("Leave these fields empty to print blank lines.")
        else:
            paper_title = st.text_input(
                "Paper title", value="Question Paper", max_chars=100,
                on_change=clear_export,
            )
        instructions = st.text_area(
            "Additional instructions" if pattern else "Instructions",
            value="" if pattern else "Answer all questions.", max_chars=500, height=80,
            key=f"paper_instructions_{pattern_name}",
            on_change=clear_export,
        )
        include_student_fields = not pattern and st.checkbox(
            "Include Name and Date fields", value=False, on_change=clear_export,
        )
    submitted = st.button("Generate questions", type="primary", use_container_width=True)

if submitted:
    clear_output()
    if not uploads:
        st.error("Upload at least one study PDF to continue.")
    elif source_error or not selected:
        st.error("Check the study material messages before generating.")
    elif not 1 <= total_questions <= MAX_QUESTIONS:
        st.error(f"Choose between 1 and {MAX_QUESTIONS} questions in total.")
    else:
        try:
            generation_started = monotonic()
            with st.spinner("Generating questions with local Qwen...", show_time=True):
                questions = generate_questions(
                    selected,
                    {kind: amount for kind, amount in type_counts.items() if amount},
                    difficulty,
                    slots=slots,
                )
                if not pattern:
                    questions.sort(key=lambda item: QUESTION_TYPES.index(item["type"]))
            st.session_state["qnagen_draft"] = {
                "questions": questions,
                "question_ids": [uuid4().hex for _ in questions],
                "draft_id": uuid4().hex,
                "pattern": pattern,
                "slots": slots,
                "model": OLLAMA_MODEL,
                "generation_seconds": monotonic() - generation_started,
                "source_chunks": selected,
            }
        except (GenerationError, ValueError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(f"Could not generate questions: {exc}")

with st.container():
    draft = st.session_state.get("qnagen_draft")
    if draft and draft.get("pattern") and draft["pattern"].label not in PAPER_PATTERNS:
        clear_output()
        draft = None
    if draft and len(draft["questions"]) > MAX_QUESTIONS:
        clear_output()
        draft = None
        st.info("Generate a new draft with up to 15 questions.")
    if draft:
        saved_pattern = draft.get("pattern")
        draft_pattern = PAPER_PATTERNS[saved_pattern.label] if saved_pattern else None
        draft_slots = draft.get("slots", ())
        st.subheader("Review questions")
        model = draft.get("model")
        if model:
            elapsed = draft.get("generation_seconds")
            timing = f" · {elapsed:.1f} seconds for the initial draft" if elapsed is not None else ""
            st.caption(f"Generated with {model} through local Ollama{timing}")
        st.caption(
            "Check each question and answer against your study material. "
            "Save edits before switching questions."
        )
        notice = st.session_state.pop("qnagen_notice", None)
        if notice:
            st.success(notice)

        output = st.session_state.get("qnagen_output")
        if output and output.get("layout_version") != pdf_builder.PDF_LAYOUT_VERSION:
            clear_export()
            output = None
        if output:
            question_count = output.get("question_count", len(output.get("questions", ())))
            st.success(f"Created PDFs with {question_count} reviewed questions.")
            paper_filename = "question_paper.pdf"
            if draft_pattern:
                term = "midterm" if draft_pattern.table_layout else "endterm"
                paper_filename = f"ipu_{term}_question_paper.pdf"
            paper_col, key_col = st.columns(2)
            with paper_col:
                st.download_button(
                    "Download question paper", output["paper"], paper_filename,
                    "application/pdf", use_container_width=True,
                )
            with key_col:
                st.download_button(
                    "Download answer key", output["key"], "answer_key.pdf",
                    "application/pdf", use_container_width=True,
                )

        if not draft["questions"]:
            st.info("No questions remain. Generate a new set to continue.")
        else:
            selection_key = f"review_selection_{draft['draft_id']}"
            next_index = draft.pop("next_review_index", None)
            if next_index is not None:
                st.session_state[selection_key] = next_index
            selected_index = st.selectbox(
                "Question to review", range(len(draft["questions"])),
                format_func=lambda index: (
                    f"{draft_slots[index].label if draft_slots else str(index + 1)} · "
                    f"{draft['questions'][index]['type']} — "
                    f"{draft['questions'][index]['question'][:75]}"
                ),
                key=selection_key,
            )
            current = draft["questions"][selected_index]
            current_slot = draft_slots[selected_index] if draft_slots else None
            question_id = draft["question_ids"][selected_index]
            show_outcomes = draft_pattern is not None and draft_pattern.table_layout
            with st.form(f"review_form_{question_id}"):
                st.caption(
                    f"Question {selected_index + 1} of {len(draft['questions'])} · "
                    f"{current['type']} · {current['difficulty']}"
                )
                edited_question = st.text_area("Question", value=current["question"])
                if current["type"] == "MCQ":
                    option_cols = st.columns(2)
                    edited_options = {}
                    for position, letter in enumerate("ABCD"):
                        with option_cols[position % 2]:
                            edited_options[letter] = st.text_input(
                                f"Option {letter}", value=current["options"][letter]
                            )
                    edited_answer = st.selectbox(
                        "Correct answer", list("ABCD"),
                        index=list("ABCD").index(current["answer"]),
                    )
                else:
                    edited_options = None
                    edited_answer = st.text_area("Model answer", value=current["answer"])
                if show_outcomes:
                    edited_outcomes = st.text_input(
                        "CO(s)", value=current.get("course_outcomes", ""),
                        placeholder="e.g. CO1, CO3", max_chars=40,
                    ).strip()

                save_col, next_col, remove_col, regenerate_col = st.columns(4)
                with save_col:
                    save_clicked = st.form_submit_button("Save changes", use_container_width=True)
                with next_col:
                    next_clicked = st.form_submit_button(
                        "Next question", use_container_width=True,
                        disabled=selected_index + 1 >= len(draft["questions"]),
                        help="Save your edits and open the next question.",
                    )
                with remove_col:
                    remove_clicked = st.form_submit_button(
                        "Remove question", use_container_width=True, disabled=bool(draft_pattern),
                        help="Regenerate to replace a question in a fixed paper pattern." if draft_pattern else None,
                    )
                with regenerate_col:
                    regenerate_clicked = st.form_submit_button(
                        "Regenerate question", use_container_width=True
                    )
                export_clicked = st.form_submit_button(
                    "Create PDFs from reviewed questions", type="primary",
                    use_container_width=True,
                )

            if remove_clicked:
                draft["questions"].pop(selected_index)
                draft["question_ids"].pop(selected_index)
                draft["draft_id"] = uuid4().hex
                st.session_state.pop("qnagen_output", None)
                st.session_state["qnagen_notice"] = "Question removed."
                st.rerun()
            elif regenerate_clicked:
                try:
                    with st.spinner("Regenerating this question...", show_time=True):
                        replacement = generate_questions(
                            draft["source_chunks"], {current["type"]: 1},
                            current["difficulty"],
                            slots=(current_slot,) if current_slot else (),
                            existing_questions=question_keys(draft["questions"]),
                        )
                    if show_outcomes:
                        replacement[0]["course_outcomes"] = current.get("course_outcomes", "")
                    draft["questions"][selected_index] = replacement[0]
                    draft["question_ids"][selected_index] = uuid4().hex
                    st.session_state.pop("qnagen_output", None)
                    st.session_state["qnagen_notice"] = "Question regenerated. Review it before export."
                    st.rerun()
                except (GenerationError, ValueError) as exc:
                    st.error(str(exc))
            elif export_clicked and not paper_title.strip():
                st.error("Enter a paper title in Paper options before creating the PDFs.")
            elif save_clicked or export_clicked or next_clicked:
                edited = {
                    **current,
                    "question": edited_question,
                    "options": edited_options,
                    "answer": edited_answer,
                }
                other_questions = [
                    question for index, question in enumerate(draft["questions"])
                    if index != selected_index
                ]
                try:
                    validated = validate_batch(
                        {"questions": [edited]}, {current["type"]: 1}, "Mixed",
                        question_keys(other_questions),
                    )[0]
                    if show_outcomes and edited_outcomes:
                        validated["course_outcomes"] = edited_outcomes
                    draft["questions"][selected_index] = validated
                    if validated != current:
                        clear_export()
                    if export_clicked:
                        counts = {
                            kind: sum(q["type"] == kind for q in draft["questions"])
                            for kind in QUESTION_TYPES
                        }
                        reviewed = validate_batch(
                            {"questions": draft["questions"]},
                            {kind: count for kind, count in counts.items() if count},
                            "Mixed", set(),
                        )
                        if show_outcomes:
                            for question, saved_question in zip(reviewed, draft["questions"]):
                                question["course_outcomes"] = saved_question.get("course_outcomes", "")
                        paper_pdf, key_pdf = pdf_builder.build_pdfs(
                            reviewed, paper_title.strip(), instructions.strip(),
                            include_student_fields,
                            pattern=draft_pattern,
                            exam_header=exam_header,
                        )
                        st.session_state["qnagen_output"] = {
                            "paper": paper_pdf,
                            "key": key_pdf,
                            "question_count": len(reviewed),
                            "layout_version": pdf_builder.PDF_LAYOUT_VERSION,
                        }
                        st.session_state["qnagen_notice"] = "Reviewed PDFs are ready to download."
                    elif next_clicked:
                        draft["next_review_index"] = selected_index + 1
                    else:
                        st.session_state["qnagen_notice"] = "Question saved."
                    st.rerun()
                except (ValidationError, ValueError) as exc:
                    st.error(f"Check this question before continuing: {exc}")
                except Exception as exc:
                    st.error(f"Could not create the PDFs: {exc}")
