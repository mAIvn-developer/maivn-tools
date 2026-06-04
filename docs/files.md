# Files and attachments

Agents routinely pull a PDF out of a CRM, drop a CSV into cloud storage, or
hand an image to a vision model — and every provider represents that content
differently. This module gives connectors one provider-agnostic vocabulary
for moving file content around: a single `Attachment` reference, reliable
MIME detection that never guesses wrong by raising, pluggable text
extraction, and progress/outcome objects for bulk transfers. Connectors speak
these primitives so Agents and hosts don't have to special-case every
provider's file model.

## MIME detection

```python
from maivn_tools import classify_kind, detect_mime_type, guess_mime_type

detect_mime_type(b"%PDF-1.4\n...")            # 'application/pdf'
detect_mime_type(b"\x89PNG\r\n\x1a\n...")     # 'image/png'
detect_mime_type(b"", filename="report.docx") # 'application/vnd.openxmlformats-...'
guess_mime_type("notes.md")                   # 'text/markdown' (extension only)
classify_kind("application/pdf")              # 'pdf'
classify_kind("image/png")                    # 'image'
```

The detector inspects the first 64 bytes for magic numbers, sniffs the
central directory of ZIP containers for OOXML markers, and falls back to
`mimetypes.guess_type` based on the filename. It never raises and returns
`application/octet-stream` when nothing matches.

## Attachments

`Attachment` is the canonical reference connector tools return. Exactly one
of `content`, `url`, or `path` is allowed.

```python
from maivn_tools import Attachment, AttachmentSource

inline = Attachment(name="report.pdf", content=pdf_bytes)
remote = Attachment(name="logo.png", url="https://cdn.example.com/logo.png")
local = Attachment(name="data.csv", path="/srv/exports/data.csv")

assert inline.source is AttachmentSource.INLINE
assert inline.kind == "pdf"
print(inline.to_dict())  # safe to log; inline content is omitted
```

For inline attachments, MIME type, size, and SHA-256 checksum are computed
automatically. URL and path attachments use extension hints only — fetching
the content is the consumer's responsibility.

## Text extraction

`TextExtractor` is an abstract base. The core registry always includes a
dependency-free UTF-8 extractor that covers plain text, Markdown, CSV, JSON,
and XML.

Richer extractors ship alongside it but stay optional. `HtmlTextExtractor`
is pure-stdlib; `PdfTextExtractor` and `DocxTextExtractor` load their drivers
(`pypdf` / `python-docx`) lazily inside `extract`, so importing the package
never pulls in heavy dependencies. Activate the bundled extractors in one
call:

```python
from maivn_tools import register_default_extractors

register_default_extractors()  # registers HTML, PDF, and DOCX extractors
```

A driver that is missing raises a clear `RuntimeError` only when that
extractor actually runs — for example, `PdfTextExtractor` tells you to
`pip install maivn-tools[pdf]`. To go beyond what ships, register your own
extractor for any MIME type:

```python
from maivn_tools import extractor_for, register_extractor, TextExtractor, ExtractionResult


class HTMLExtractor(TextExtractor):
    mime_types = ("text/html",)

    def extract(self, data, *, mime_type=None, filename=None):
        text = strip_html(data.decode("utf-8", errors="replace"))
        return ExtractionResult(text=text, mime_type="text/plain")


register_extractor(HTMLExtractor())
result = extractor_for("text/html").extract(b"<p>hello</p>")
print(result.text)  # 'hello'
```

The most recently registered extractor wins on conflicts.

## Bulk transfers

`TransferProgress` tracks an in-flight transfer; `TransferOutcome` wraps the
final result.

```python
from maivn_tools import TransferOutcome, TransferProgress, TransferStatus

progress = TransferProgress(transferred=512, total=1024, items_completed=3, items_total=5)
print(progress.fraction)  # 0.5

outcome = TransferOutcome(
    status=TransferStatus.PARTIAL,
    succeeded=("file-a", "file-b"),
    failed={"file-c": "permission denied"},
    progress=progress,
)
assert outcome.is_terminal
```

Connectors that support resumability can return a `resume_token` callers
plumb back into a follow-up call.
