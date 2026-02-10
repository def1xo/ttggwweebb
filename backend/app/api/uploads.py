from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from typing import Dict
from app.services import media_store

router = APIRouter(tags=["uploads"])


@router.post("/api/uploads", summary="Upload file (image)")
async def upload_file(file: UploadFile = File(...), subdir: str = "products") -> Dict[str, str]:
    if not file:
        raise HTTPException(status_code=400, detail="Missing file")
    key, url = await media_store.save_upload_file(file, subdir=subdir)
    return {"key": key, "url": url}
