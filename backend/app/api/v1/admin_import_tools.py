from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin_user, get_db
from app.db import models
from app.services.bulk_import import run_csv_import

router = APIRouter(tags=["admin_import_tools"])


class BulkApplyIn(BaseModel):
    supplier_id: int


@router.post("/import/run-csv")
def import_from_csv(
    supplier_id: int,
    force_publish: bool = False,
    file: UploadFile = File(...),
    _admin=Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    csv_text = file.file.read().decode("utf-8")
    job = run_csv_import(db, supplier_id=supplier_id, csv_text=csv_text, force_publish=force_publish)
    return {"job_id": job.id, "status": job.status, "error": job.error_message}


@router.get("/import/history")
def import_history(_admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    rows = db.query(models.ImportJob).order_by(models.ImportJob.id.desc()).limit(200).all()
    return [
        {
            "id": x.id,
            "supplier_id": x.supplier_id,
            "status": x.status,
            "error_message": x.error_message,
            "input_dump_path": x.input_dump_path,
            "created_at": x.created_at,
        }
        for x in rows
    ]


@router.get("/import/review/colors")
def unknown_colors(_admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    rows = db.query(models.Product).filter(models.Product.requires_color_review == True).limit(500).all()  # noqa: E712
    return [{"id": p.id, "title": p.title, "reason": p.review_reason, "images": [im.url for im in p.images]} for p in rows]


@router.get("/import/review/categories")
def unknown_categories(_admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    rows = db.query(models.Product).filter(models.Product.requires_category_review == True).limit(500).all()  # noqa: E712
    return [{"id": p.id, "title": p.title, "reason": p.review_reason} for p in rows]


@router.post("/supplier-category-map/bulk-apply")
def bulk_apply_supplier_map(payload: BulkApplyIn, _admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    maps = db.query(models.SupplierCategoryMap).filter(
        models.SupplierCategoryMap.supplier_id == payload.supplier_id,
        models.SupplierCategoryMap.is_confirmed == True,  # noqa: E712
    ).all()
    if not maps:
        raise HTTPException(status_code=404, detail="no confirmed mappings")

    changed = 0
    for m in maps:
        products = db.query(models.Product).filter(
            models.Product.import_supplier_name == str(payload.supplier_id),
            models.Product.requires_category_review == True,  # noqa: E712
        ).all()
        for p in products:
            p.category_id = m.mapped_category_id
            p.requires_category_review = False
            if not p.requires_color_review:
                p.visible = True
            changed += 1
    db.commit()
    return {"updated": changed}


@router.get("/import/review/dashboard")
def import_review_dashboard(_admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    grouped = (
        db.query(
            models.Product.import_supplier_name,
            func.sum(case((models.Product.requires_color_review == True, 1), else_=0)),  # noqa: E712
            func.sum(case((models.Product.requires_category_review == True, 1), else_=0)),  # noqa: E712
        )
        .group_by(models.Product.import_supplier_name)
        .all()
    )
    return [
        {"supplier": s, "requires_color_review": int(c or 0), "requires_category_review": int(cat or 0)}
        for s, c, cat in grouped
    ]


@router.post("/import/retry/{import_id}")
def retry_import(import_id: int, _admin=Depends(get_current_admin_user), db: Session = Depends(get_db)):
    job = db.query(models.ImportJob).filter(models.ImportJob.id == import_id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="import not found")
    if not job.payload:
        raise HTTPException(status_code=400, detail="import payload missing")
    return {"ok": True, "hint": "re-upload csv with same payload via /import/run-csv", "job": job.id}
