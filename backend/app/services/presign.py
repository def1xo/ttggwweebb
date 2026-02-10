from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse
import os, datetime, uuid, shutil

router = APIRouter(prefix="/api", tags=["uploads"])

# NOTE: files are saved under project-root/uploads/<yyyyMMdd>/...
BASE_UPLOAD_DIR = "uploads"
os.makedirs(BASE_UPLOAD_DIR, exist_ok=True)

def _make_key(filename: str):
    safe = filename.replace("/", "_").replace("\\","_")
    today = datetime.datetime.utcnow().strftime("%Y%m%d")
    key = f"uploads/{today}/{uuid.uuid4().hex}-{safe}"
    return key

@router.post("/uploads/presign")
def presign_put(filename: str = Form(...), content_type: str = Form(...)):
    """
    Compatibility endpoint. Returns a local server-side PUT endpoint and object URL.
    Client may PUT raw bytes to the returned put_url (relative path).
    """
    key = _make_key(filename)
    put_url = f"/api/uploads/direct_put/{key}"
    object_url = f"/{key}"
    return {"put_url": put_url, "object_url": object_url, "key": key}

@router.put("/uploads/direct_put/{key:path}")
async def direct_put(key: str, request: Request):
    """
    Accept raw body bytes and save to uploads/<key>.
    """
    dest = os.path.join(".", key)
    dest_dir = os.path.dirname(dest)
    os.makedirs(dest_dir, exist_ok=True)
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty body")
    with open(dest, "wb") as f:
        f.write(body)
    return {"url": f"/{key}", "key": key}

@router.post("/uploads")
async def upload_file(file: UploadFile = File(...)):
    """
    Multipart upload (standard). Returns {key, url}
    """
    filename = file.filename or "file"
    key = _make_key(filename)
    dest = os.path.join(".", key)
    dest_dir = os.path.dirname(dest)
    os.makedirs(dest_dir, exist_ok=True)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"key": key, "url": f"/{key}"}
