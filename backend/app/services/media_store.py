import os
from uuid import uuid4
from pathlib import Path
from typing import Optional, Set, Tuple

from fastapi import UploadFile

UPLOAD_BASE = Path(os.getenv("UPLOADS_DIR", "uploads"))
UPLOAD_BASE.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS_IMAGE: Set[str] = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIMES_IMAGE: Set[str] = {"image/jpeg", "image/png", "image/webp"}

ALLOWED_EXTS_PDF: Set[str] = {".pdf"}
ALLOWED_MIMES_PDF: Set[str] = {"application/pdf"}

MAX_UPLOAD_BYTES = int(os.getenv('MAX_UPLOAD_BYTES') or os.getenv('MAX_UPLOAD_SIZE') or (8 * 1024 * 1024))


def _ensure_folder(folder: str) -> Path:
    p = UPLOAD_BASE.joinpath(folder)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _make_filename(orig_filename: Optional[str]) -> str:
    ext = "bin"
    if orig_filename and "." in orig_filename:
        ext = orig_filename.rsplit(".", 1)[1].lower()
    return f"{uuid4().hex}.{ext}"


def public_url_from_path(path: Path) -> str:
    try:
        rel = path.relative_to(Path.cwd())
    except Exception:
        rel = path
    return "/" + "/".join(rel.parts)


def _allowed_for_folder(folder: str) -> Tuple[Set[str], Set[str]]:
    """Return allowed extensions and mimes for a given logical folder."""
    folder_l = (folder or "").lower()
    exts = set(ALLOWED_EXTS_IMAGE)
    mimes = set(ALLOWED_MIMES_IMAGE)
    # Allow pdf only for payment proof / payment uploads
    if "payment" in folder_l:
        exts |= ALLOWED_EXTS_PDF
        mimes |= ALLOWED_MIMES_PDF
    return exts, mimes


def save_upload_file_to_local(upload_file: UploadFile, folder: str = "misc") -> str:
    """Save UploadFile to local storage and return a public URL path.

    Performs basic validation (extension, content-type, and size).
    """
    allowed_exts, allowed_mimes = _allowed_for_folder(folder)

    content_type = (upload_file.content_type or "").lower()
    if content_type not in allowed_mimes:
        raise ValueError("unsupported file type")

    filename = upload_file.filename or ""
    _, _, ext = filename.rpartition(".")
    ext = f".{ext.lower()}" if ext else ""
    if ext not in allowed_exts:
        raise ValueError("unsupported file extension")

    data = upload_file.file.read()
    size = len(data)
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("file too large")

    dest_folder = _ensure_folder(folder)
    filename_to_use = _make_filename(upload_file.filename)
    dest_path = dest_folder / filename_to_use
    with open(dest_path, "wb") as f:
        f.write(data)

    try:
        upload_file.file.seek(0)
    except Exception:
        pass

    return public_url_from_path(dest_path)


def upload_uploadfile_to_s3(upload_file: UploadFile, folder: str = "products") -> str:
    # This project currently stores uploads locally.
    return save_upload_file_to_local(upload_file, folder=folder)


def generate_presigned_put_stub(key: str, content_type: str, expires_in: int = 900) -> dict:
    return {"put_url": "", "object_url": f"/{UPLOAD_BASE}/{key}"}
