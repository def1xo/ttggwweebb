from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.services.importer_notifications import parse_and_save_post

router = APIRouter(tags=["importer"])


class ChannelPostPayload(BaseModel):
    channel_id: Optional[int] = None
    message_id: int
    date: Optional[int] = None
    text: str = ""
    image_urls: List[str] = Field(default_factory=list)


@router.post("/importer/channel_post")
def import_channel_post(payload: ChannelPostPayload, db: Session = Depends(get_db)):
    """Import a Telegram channel post into products/news.

    The Telegraf bot posts here. We parse the text and create/update a Product
    using the existing importer_notifications logic.
    """
    try:
        prod = parse_and_save_post(db, payload.model_dump(), is_draft=False)
        if not prod:
            raise HTTPException(status_code=400, detail="Import failed")
        return {
            "ok": True,
            "product_id": getattr(prod, "id", None),
            "slug": getattr(prod, "slug", None),
            "name": getattr(prod, "name", None),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
