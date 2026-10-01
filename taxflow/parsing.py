"""Source parsing: split text into pages and numbered lines, and validate uploads."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_CHARS = 20_000
MAX_PAGES = 5

# A page break is a form feed or a line such as "----- page break -----".
_PAGE_BREAK_LINE = re.compile(r"^\s*-{3,}\s*page\s*break\s*-{3,}\s*$", re.IGNORECASE)


class InputError(ValueError):
    """Raised for input the app rejects with a user-facing explanation."""


@dataclass(frozen=True)
class ParsedDocument:
    document_id: str
    name: str
    pages: tuple[tuple[str, ...], ...]  # pages[p-1][l-1] is page p, line l

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def line(self, page: int, line: int) -> str:
        return self.pages[page - 1][line - 1]

    def span_text(self, page: int, start: int, end: int) -> str:
        return "\n".join(self.pages[page - 1][start - 1 : end])

    def has_span(self, page: int, start: int, end: int) -> bool:
        if not (1 <= page <= self.page_count):
            return False
        n = len(self.pages[page - 1])
        return 1 <= start <= end <= n

    def numbered_text(self) -> str:
        """Render for the model: every line prefixed with page and line number."""
        out = []
        for p, lines in enumerate(self.pages, start=1):
            out.append(f"[page {p}]")
            for i, text in enumerate(lines, start=1):
                out.append(f"p{p} L{i:>3} | {text}")
        return "\n".join(out)


def parse_text(text: str, document_id: str, name: str) -> ParsedDocument:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pages: list[list[str]] = [[]]
    for raw in text.split("\n"):
        chunks = raw.split("\f")
        for j, chunk in enumerate(chunks):
            if j > 0:
                pages.append([])
            if _PAGE_BREAK_LINE.match(chunk):
                pages.append([])
                continue
            pages[-1].append(chunk.rstrip())
    # Drop trailing blank lines per page and empty pages.
    cleaned = []
    for lines in pages:
        while lines and not lines[-1].strip():
            lines.pop()
        if any(line.strip() for line in lines):
            cleaned.append(tuple(lines))
    if not cleaned:
        raise InputError("The document is empty.")
    if len(cleaned) > MAX_PAGES:
        raise InputError(f"The document has {len(cleaned)} pages; the limit is {MAX_PAGES}.")
    return ParsedDocument(document_id=document_id, name=name, pages=tuple(cleaned))


def decode_upload(data: bytes, filename: str) -> ParsedDocument:
    """Validate a synthetic TXT upload and parse it. Raises InputError with a clear reason."""
    if not filename.lower().endswith(".txt"):
        raise InputError("Only .txt files are supported in this version.")
    if len(data) == 0:
        raise InputError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InputError("The file is larger than 2 MB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("The file is not valid UTF-8 text.") from None
    if not text.strip():
        raise InputError("The file contains no text.")
    if len(text) > MAX_CHARS:
        raise InputError(f"The file has {len(text):,} characters; the limit is {MAX_CHARS:,}.")
    digest = hashlib.sha256(data).hexdigest()[:12]
    return parse_text(text, document_id=f"upload-{digest}", name=filename)
