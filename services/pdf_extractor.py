"""Validate and extract text from uploaded PDFs with PyMuPDF."""

import pymupdf


class PDFInputError(ValueError):
    """The uploaded PDF cannot be used for text generation."""


class PDFPageLimitError(PDFInputError):
    """The PDF does not fit within the available page budget."""


def extract_pdf_text(data: bytes, max_file_mb: int, max_pages: int) -> tuple[str, int]:
    if not data:
        raise PDFInputError("The uploaded file is empty.")
    if len(data) > max_file_mb * 1024 * 1024:
        raise PDFInputError(f"The PDF exceeds the configured {max_file_mb} MB limit.")
    if not data.startswith(b"%PDF-"):
        raise PDFInputError("Please upload a valid PDF file.")

    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.is_encrypted:
                raise PDFInputError("Password-protected PDFs are not supported.")
            page_count = len(document)
            if page_count == 0:
                raise PDFInputError("The PDF has no pages.")
            if page_count > max_pages:
                raise PDFPageLimitError(f"The PDF exceeds the available {max_pages}-page budget.")
            pages = [page.get_text("text", sort=True) for page in document]
    except PDFInputError:
        raise
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError) as exc:
        raise PDFInputError("The PDF could not be opened or read.") from exc

    text = "\n\n".join(pages).strip()
    if not text:
        raise PDFInputError(
            "No selectable text was found. Scanned or image-only PDFs need OCR, "
            "which is outside this version's scope."
        )
    return text, page_count
