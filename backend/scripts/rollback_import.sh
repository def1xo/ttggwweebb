#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <import_id>"
  exit 1
fi
IMPORT_ID=$1

python - <<PY
from app.db.session import SessionLocal
from app.db import models

db = SessionLocal()
job = db.query(models.ImportJob).filter(models.ImportJob.id == int(${IMPORT_ID})).one_or_none()
if not job:
    print("import job not found")
    raise SystemExit(1)
item_product_ids = [x.product_id for x in db.query(models.ImportItem).filter(models.ImportItem.import_job_id == job.id).all() if x.product_id]
if item_product_ids:
    db.query(models.Product).filter(models.Product.id.in_(item_product_ids)).update({models.Product.visible: False}, synchronize_session=False)
job.status = "rolled_back"
db.commit()
print({"ok": True, "import_id": job.id, "products_unpublished": len(item_product_ids)})
PY
