import re
import unicodedata


def extract_text(file_path: str) -> str:
    """Extract raw text from PDF, DOCX, or TXT and return normalised string."""
    ext = file_path.rsplit(".", 1)[-1].lower()
    raw = _read(ext, file_path)
    return _normalise(raw)


def _read(ext: str, path: str) -> str:
    if ext == "txt":
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    if ext == "docx":
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)

    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    raise ValueError(f"Unsupported file type: {ext}")


def _normalise(text: str) -> str:
    # unicode → ASCII-compatible, lowercase
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    # collapse whitespace, strip non-alphanumeric except spaces
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text