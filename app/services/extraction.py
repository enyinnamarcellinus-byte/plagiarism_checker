import io
import re
import unicodedata

import nltk

from ..config import settings

try:
    _STOPWORDS = frozenset(nltk.corpus.stopwords.words("english"))
except LookupError:
    nltk.download("stopwords", quiet=True)
    _STOPWORDS = frozenset(nltk.corpus.stopwords.words("english"))


def extract_text(raw_bytes: bytes, ext: str) -> str:
    return _normalise(_read(ext, io.BytesIO(raw_bytes)))


def _read(ext: str, fileobj: io.BytesIO) -> str:
    if ext == "txt":
        return fileobj.read().decode("utf-8", errors="replace")

    if ext == "docx":
        from docx import Document

        return "\n".join(p.text for p in Document(fileobj).paragraphs)

    if ext == "pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(fileobj).pages)

    raise ValueError(f"Unsupported file type: {ext}")


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if settings.filter_stopwords:
        text = " ".join(w for w in text.split() if w not in _STOPWORDS)
    return text
