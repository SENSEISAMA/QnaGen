"""Basic text cleanup, paragraph segmentation, and character-bound chunking."""

import re


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\u00ad", "")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n+", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int) -> list[str]:
    if max_chars < 100:
        raise ValueError("Chunk size must be at least 100 characters.")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        for sentence in sentences:
            # Very long sentences are split at character boundaries.
            pieces = [sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars)]
            for piece in pieces:
                candidate = f"{current} {piece}".strip() if current else piece
                if len(candidate) > max_chars:
                    if current:
                        chunks.append(current)
                    current = piece
                else:
                    current = candidate
    if current:
        chunks.append(current)
    return chunks


def select_chunks(chunks: list[str], maximum: int) -> tuple[list[str], bool]:
    """Sample across a long document and disclose when some chunks are skipped."""
    if len(chunks) <= maximum:
        return chunks, False
    if maximum == 1:
        return [chunks[0]], True
    indexes = [round(i * (len(chunks) - 1) / (maximum - 1)) for i in range(maximum)]
    return [chunks[index] for index in indexes], True


def select_study_chunks(
    documents: list[list[str]], maximum: int, chunk_chars: int,
) -> tuple[list[str], bool]:
    """Share the prompt budget across study PDFs."""
    if len(documents) > maximum:
        excerpt_chars = max(1, maximum * chunk_chars // len(documents))
        return [chunks[0][:excerpt_chars] for chunks in documents], True

    allocations = [0] * len(documents)
    remaining = min(maximum, sum(map(len, documents)))
    while remaining:
        for index, chunks in enumerate(documents):
            if allocations[index] < len(chunks):
                allocations[index] += 1
                remaining -= 1
                if not remaining:
                    break

    selected = []
    for chunks, limit in zip(documents, allocations):
        sampled_chunks, _ = select_chunks(chunks, limit)
        selected.extend(sampled_chunks)
    return selected, len(selected) < sum(map(len, documents))

