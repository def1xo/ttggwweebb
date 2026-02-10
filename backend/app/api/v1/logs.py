# backend/app/api/v1/logs.py
from fastapi import APIRouter, Request
import json
import os
from datetime import datetime

router = APIRouter()

@router.post("/client-error")
async def client_error(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": await request.body()}
    try:
        fn = os.environ.get("CLIENT_ERRORS_LOG", "/tmp/client_errors.log")
        with open(fn, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.utcnow().isoformat(), "payload": payload}, ensure_ascii=False) + "\n")
    except Exception as e:
        # не ломаем поведение, просто вернём ok
        print("Failed to write client error log:", e)
    return {"ok": True}
