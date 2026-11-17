# QnaGen

QnaGen is a Streamlit application that extracts text from an educational PDF with PyMuPDF, prepares it in Python, drafts questions using local Qwen through Ollama, and exports a question paper and answer key with ReportLab. Local Qwen and the paper presets are implementation changes from the original synopsis.

## Run locally

Install Python 3.11 or newer first. From this directory in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Keep Ollama running on the same computer. If needed, download the model with `ollama pull qwen3.5:9b`. Generation uses the local Ollama API and requires no key. Upload one or more study PDFs containing selectable text, then choose a paper pattern before generating one combined paper.

| Pattern | Printed prompts | Maximum marks | Attempt rule |
| --- | ---: | ---: | --- |
| Standard | 1–15 | — | Choose your own mix of MCQs, short answers and long answers. |
| IPU Midterm | 11 | 30 | Compulsory Q1 plus any two of Q2–Q4, including both parts of each. |
| IPU End term (adapted) | 13 | 75 | Compulsory Q1 plus one 12.5-mark question per unit. Qwen chooses unit topics from the study material. |

The IPU presets follow the supplied sample papers. Under **Paper options**, enter an optional paper code, subject and semester or exam session. Empty fields print as blank lines on the student paper. The IPU end term preset combines multi-part unit alternatives into single questions to fit the 15-question cap. Review the questions and answers before downloading both PDFs.

## Current implementation

- PDF upload checks: valid PDF headers, configurable combined limits of 20 MB and 600 pages by default, plus empty and password-protected file handling.
- PyMuPDF text extraction, basic cleanup, sentence/paragraph chunking, and configurable sampling across long documents.
- MCQ, short-answer, and long-answer generation with exact counts for each type and Easy, Medium, Hard, or Mixed difficulty requests.
- JSON parsing, exact count/type checks, MCQ option and answer-letter checks, duplicate question-text checks, and up to two regeneration attempts per invalid batch by default.
- One local generation batch for the requested question set, with selected source sections grouped into the request.
- Text preview before generation, so unusable extraction is visible before a model request.
- A review step before PDF creation. Users can edit or regenerate questions, and can remove questions in Standard mode. Fixed paper patterns keep their required slots throughout review.
- Separate question-paper and answer-key PDFs with configurable title, instructions, optional Name/Date fields, sections by question type, and page numbers. Answers and difficulty labels are omitted from the student paper.

The paper cap is 15 questions, counting printed alternatives and subparts. Upload limits and sampling settings can be configured through environment variables.

## Limits

Text extraction may be noisy for complex layouts and cannot read scanned or image-only PDFs without OCR. Long files may be sampled; the interface reports when content is skipped. Difficulty labels are approximate. Structural validation cannot prove factual correctness, answer validity, or educational quality. A teacher should review both PDFs before use. This implementation does not use a database or train a model.

## Project layout

`app.py` handles the Streamlit flow. `config.py` contains app settings. `services/` contains paper patterns, PDF extraction, preprocessing, Ollama generation, validation, and ReportLab output.
