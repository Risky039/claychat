"""Attachment validation by magic bytes and safe filename normalization."""

import re
import secrets

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB
ATTACHMENT_ID_RE = re.compile(r"^[a-f0-9]{24}$")
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def new_attachment_id():
    return secrets.token_hex(12)


def valid_attachment_id(value):
    return isinstance(value, str) and ATTACHMENT_ID_RE.fullmatch(value) is not None


def clean_filename(name):
    if not isinstance(name, str) or not name.strip():
        return "attachment"
    base = name.replace("\\", "/").split("/")[-1].strip()
    cleaned = SAFE_NAME_RE.sub("_", base).strip("._")
    return (cleaned or "attachment")[:80]


def detect_mime(data, filename=""):
    """Inspect magic bytes; return an allowed MIME string or raise ValueError."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("Uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded file exceeds the 5 MB limit")

    header = bytes(data[:16])
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"%PDF-"):
        return "application/pdf"

    # Allow small UTF-8 plain text files (.txt, .md, .log, .json, .csv) if no NUL bytes
    lower = (filename or "").lower()
    if lower.endswith((".txt", ".md", ".log", ".json", ".csv")) and b"\x00" not in data[:4096]:
        try:
            bytes(data[:4096]).decode("utf-8")
            return "text/plain; charset=utf-8"
        except UnicodeDecodeError:
            pass

    raise ValueError("Unsupported file type (allowed: PNG, JPEG, GIF, WEBP, PDF, or UTF-8 text)")

