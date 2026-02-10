import os, sys
from sqlalchemy import create_engine, text

db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("Set DATABASE_URL env or pass one")
    sys.exit(2)
engine = create_engine(db_url)
conn = engine.connect()
print("Deleting demo categories/products/news if exist...")
# WARNING: adjust table names to your schema
conn.execute(text("DELETE FROM product_images WHERE url LIKE '%/public/demo/%'"))
conn.execute(text("DELETE FROM product_images WHERE url LIKE '%demo/%'"))
conn.execute(text("DELETE FROM product_variants WHERE sku LIKE 'demo%'"))
conn.execute(text("DELETE FROM products WHERE name ILIKE '%demo%' OR name ILIKE '%test%'"))
conn.execute(text("DELETE FROM categories WHERE name ILIKE '%demo%' OR name ILIKE '%test%'"))
conn.commit()
print("Done")
