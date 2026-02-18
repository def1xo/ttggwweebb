import os
import hashlib
import re
from uuid import uuid4
from pathlib import Path
from typing import Optional, Set, Tuple
from urllib.parse import urlparse

import requests

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


def _filename_stem_hint(raw: str | None) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"[^a-zа-я0-9]+", "-", s, flags=re.IGNORECASE)
    s = s.strip("-")
    return s[:80]


def save_remote_image_to_local(
    url: str,
    folder: str = "products",
    timeout_sec: int = 20,
    filename_hint: str | None = None,
) -> str:
    """Download an image from URL and save to local uploads, return public URL."""
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        raise ValueError("unsupported remote image url")

    try:
        resp = requests.get(u, timeout=timeout_sec, headers={"User-Agent": "defshop-media-fetch/1.0"})
        resp.raise_for_status()
    except Exception as exc:
        raise ValueError(f"failed to download image: {exc}")

    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not ctype.startswith("image/"):
        raise ValueError("remote url is not an image")

    ext_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    url_ext = os.path.splitext(urlparse(u).path)[1].lower()
    ext = ext_map.get(ctype, url_ext if url_ext in ALLOWED_EXTS_IMAGE else ".jpg")

    data = resp.content or b""
    if len(data) == 0:
        raise ValueError("empty image payload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("remote image too large")

    dest_folder = _ensure_folder(folder)

    url_hash = hashlib.sha1(u.encode("utf-8")).hexdigest()[:16]
    for existing in dest_folder.glob(f"*_{url_hash}.*"):
        if existing.is_file():
            return public_url_from_path(existing)

    stem = _filename_stem_hint(filename_hint)
    if not stem:
        parsed_name = os.path.basename(urlparse(u).path).rsplit(".", 1)[0]
        stem = _filename_stem_hint(parsed_name) or f"image-{uuid4().hex[:8]}"
    dest_path = dest_folder / f"{stem}_{url_hash}{ext}"
    with open(dest_path, "wb") as f:
        f.write(data)
    return public_url_from_path(dest_path)
