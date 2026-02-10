from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import List, Dict, Any
from pathlib import Path
from uuid import uuid4
import os
import imghdr
import re

router = APIRouter()

# Where to store uploaded files (relative to project /app)
UPLOAD_DIR = Path(os.getenv("UPLOADS_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Config
# Support multiple env names (some compose files use MAX_UPLOAD_SIZE).
def _get_max_upload_bytes() -> int:
    for key in ("MAX_UPLOAD_BYTES", "MAX_UPLOAD_SIZE"):
        v = os.getenv(key)
        if v:
            try:
                n = int(v)
                if n > 0:
                    return n
            except Exception:
                pass
    mb = os.getenv("MAX_UPLOAD_MB", "12")
    try:
        mb_i = int(mb)
    except Exception:
        mb_i = 12
    if mb_i <= 0:
        mb_i = 12
    return mb_i * 1024 * 1024


MAX_UPLOAD_BYTES = _get_max_upload_bytes()
MAX_UPLOAD_MB = max(1, int(MAX_UPLOAD_BYTES / (1024 * 1024)))
ALLOWED_MIMETYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "application/pdf",
    # add others if needed
}
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"}


def _secure_filename(name: str) -> str:
    """Make a reasonably safe filename: strip directory parts and keep extension."""
    name = os.path.basename(name or "")
    if not name:
        return ""
    # keep only safe chars
    keep = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            keep.append(ch)
    s = "".join(keep)
    if not s:
        s = uuid4().hex
    return s


_SUBDIR_PART_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _secure_subdir(subdir: str | None) -> Path:
    """Return a safe subdir (relative) or empty path."""
    if not subdir:
        return Path("")
    raw = str(subdir).strip().replace("\\", "/")
    raw = raw.strip("/")
    if not raw:
        return Path("")
    parts = [p for p in raw.split("/") if p and p not in (".", "..")]
    if len(parts) > 3:
        raise HTTPException(status_code=400, detail="Invalid subdir")
    for p in parts:
        if not _SUBDIR_PART_RE.match(p):
            raise HTTPException(status_code=400, detail="Invalid subdir")
    return Path(*parts)


async def _save_upload(file: UploadFile, subdir: str | None = None) -> Dict[str, Any]:
    # read content
    content = await file.read()
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail=f"File too large. Max {MAX_UPLOAD_MB} MB")

    # verify simple mime/extension
    filename = _secure_filename(file.filename or "")
    ext = Path(filename).suffix.lower()
    # try to infer image type for extra safety
    guessed = None
    try:
        guessed = imghdr.what(None, h=content)
    except Exception:
        guessed = None

    if ext not in ALLOWED_EXT:
        # allow if guessed type present
        if guessed is None:
            raise HTTPException(status_code=400, detail="Unsupported file type")
        # translate imghdr type to extension
        map_ext = {"jpeg": ".jpg", "png": ".png", "gif": ".gif", "webp": ".webp"}
        ext = map_ext.get(guessed, ext)

    # generate unique name
    unique = f"{uuid4().hex}{ext}"
    rel_dir = _secure_subdir(subdir)
    dest_dir = UPLOAD_DIR / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / unique
    try:
        with open(dest, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    url = f"/uploads/{rel_dir.as_posix() + '/' if str(rel_dir) not in ('', '.') else ''}{unique}"
    return {"filename": unique, "url": url, "size": size}


async def _upload_single_impl(file: UploadFile, subdir: str | None = None):
    """
    Upload a single file. Returns JSON with filename and url:
    { "filename": "...", "url": "/uploads/..." }
    """
    try:
        info = await _save_upload(file, subdir=subdir)
        return JSONResponse(status_code=201, content=info)
    finally:
        # ensure underlying file is closed if upload object has .file
        try:
            if hasattr(file, "file") and not file.file.closed:
                file.file.close()
        except Exception:
            pass


# Compatibility:
# - When requests go through nginx, "/api/*" may or may not be stripped.
# - For some deployments, "/api/uploads" becomes "/uploads" on backend.
# Provide BOTH paths to avoid 307 redirects (StaticFiles mount) and make uploads work everywhere.


@router.post("/api/uploads", status_code=201)
async def upload_single_api(file: UploadFile = File(...), subdir: str | None = Form(None)):
    return await _upload_single_impl(file, subdir=subdir)


@router.post("/uploads", status_code=201)
@router.post("/uploads/", status_code=201)
async def upload_single_root(file: UploadFile = File(...), subdir: str | None = Form(None)):
    return await _upload_single_impl(file, subdir=subdir)


async def _upload_multiple_impl(files: List[UploadFile], subdir: str | None = None):
    """
    Upload multiple files in one request. Returns list of uploaded file infos.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    out = []
    for f in files:
        info = await _save_upload(f, subdir=subdir)
        out.append(info)
        try:
            if hasattr(f, "file") and not f.file.closed:
                f.file.close()
        except Exception:
            pass
    return {"files": out}


@router.post("/api/uploads/multiple", status_code=201)
async def upload_multiple_api(files: List[UploadFile] = File(...), subdir: str | None = Form(None)):
    return await _upload_multiple_impl(files, subdir=subdir)


@router.post("/uploads/multiple", status_code=201)
@router.post("/uploads/multiple/", status_code=201)
async def upload_multiple_root(files: List[UploadFile] = File(...), subdir: str | None = Form(None)):
    return await _upload_multiple_impl(files, subdir=subdir)


@router.get("/api/uploads/list")
@router.get("/uploads/list")
@router.get("/uploads/list/")
async def list_uploads(limit: int = 100, prefix: str = "", subdir: str = ""):
    """
    List uploaded files (simple). Returns files in uploads dir.
    """
    files = []
    try:
        base = UPLOAD_DIR / _secure_subdir(subdir)
        base.mkdir(parents=True, exist_ok=True)
        for p in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not p.is_file():
                continue
            name = p.name
            if prefix and not name.startswith(prefix):
                continue
            rel = (Path(subdir) / name).as_posix() if subdir else name
            files.append({"filename": name, "url": f"/uploads/{rel}", "size": p.stat().st_size})
            if len(files) >= limit:
                break
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"count": len(files), "files": files}


@router.post("/api/uploads/presign")
@router.post("/uploads/presign")
async def presign_upload(filename: str):
    """
    Placeholder for S3 presign. If you use S3, fill this with boto3 presign logic
    and return { url: "<presigned-url>", method: "PUT", fields: {} } or similar.
    Currently returns 501 unless S3 env vars configured.
    """
    # quick check: if S3 env provided, you can implement presign here.
    required = os.getenv("AWS_S3_BUCKET") and os.getenv("AWS_REGION") and os.getenv("AWS_ACCESS_KEY_ID")
    if not required:
        raise HTTPException(status_code=501, detail="Presign not configured on server")
    # else: implement boto3 presigning flow (not included here)
    raise HTTPException(status_code=501, detail="Presign endpoint not implemented")


@router.delete("/api/uploads/{filename}")
@router.delete("/uploads/{filename}")
async def delete_upload(filename: str):
    """
    Delete uploaded file by filename. Use with care.
    """
    sanitized = _secure_filename(filename)
    path = UPLOAD_DIR / sanitized
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    try:
        path.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"deleted": sanitized}
