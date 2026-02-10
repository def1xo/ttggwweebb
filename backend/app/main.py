import os
from dotenv import load_dotenv
load_dotenv()

import pathlib
import logging
import traceback
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.db.session import engine
from app.core.schema_patch import ensure_schema
from app.db.base import Base
from app.db import models  # noqa: F401  (register models for Base.metadata)

logger = logging.getLogger("tgweb")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logger.addHandler(ch)

try:
    from app.api.dependencies import get_db
except Exception as e:
    logger.exception("Failed to import app.api.dependencies: %s", e)
    def get_db():
        raise RuntimeError("DB dependency not available: check imports")

try:
    from app.routes.recommendations import router as recommendations_router
except Exception as e:
    logger.exception("Failed to import recommendations router: %s", e)
    recommendations_router = None

# import logs router if present
try:
    from app.api.v1 import logs as logs_module
    logs_router = getattr(logs_module, "router", None)
except Exception:
    logger.exception("Failed to import logs router: %s", traceback.format_exc())
    logs_router = None

app = FastAPI(title="TGWeb")


@app.on_event("startup")
def _startup_schema_patch():
    # best-effort patch for running with existing Postgres volume
    try:
        # Create missing tables (project historically ran without alembic migrations)
        Base.metadata.create_all(bind=engine)
        ensure_schema(engine)
        logger.info("Schema patch: ok")
    except Exception:
        logger.exception("Schema patch failed")

origins = []
cors_env = os.getenv("CORS_ORIGINS", "")
if cors_env:
    origins = [o.strip() for o in cors_env.split(",") if o.strip()]

if not origins:
    origins = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = pathlib.Path(__file__).resolve().parent

# IMPORTANT:
# Mounting StaticFiles at "/uploads" BEFORE API routers causes nginx "/api" rewriting
# to hit the mount and get a 307 redirect (e.g. POST /api/uploads -> backend POST /uploads).
# We therefore mount "/uploads" AFTER API routers are registered.
UPLOADS_DIR = pathlib.Path(os.getenv("UPLOADS_DIR", "uploads"))
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def safe_import(name: str):
    try:
        module = __import__(name, fromlist=["*"])
        logger.info("Imported %s", name)
        return module
    except Exception:
        logger.error("Failed to import %s:\n%s", name, traceback.format_exc())
        return None



checkout = safe_import("app.api.v1.checkout")
orders = safe_import("app.api.v1.orders")
withdraws = safe_import("app.api.v1.withdraws")
products = safe_import("app.api.v1.products")
cart = safe_import("app.api.v1.cart")
favorites = safe_import("app.api.v1.favorites")
payment = safe_import("app.api.v1.payment")
manager = safe_import("app.api.v1.manager")
assistant = safe_import("app.api.v1.assistant")
news = safe_import("app.api.v1.news")
importer = safe_import("app.api.v1.importer")
promo = safe_import("app.api.v1.promo")
categories = safe_import("app.api.v1.categories")
admin_products = safe_import("app.api.v1.admin_products")
admin_orders = safe_import("app.api.v1.admin_orders")
admin_promos = safe_import("app.api.v1.admin_promos")
admin_auth = safe_import("app.api.v1.admin_auth")
admin_dashboard = safe_import("app.api.v1.admin_dashboard")
admin_managers = safe_import("app.api.v1.admin_managers")
auth = safe_import("app.api.v1.auth")

def include_router_if_present(mod, prefix: str = ""):
    try:
        if mod and getattr(mod, "router", None):
            app.include_router(mod.router, prefix=prefix)
            logger.info("Included router %s with prefix '%s'", getattr(mod, "__name__", str(mod)), prefix)
    except Exception:
        logger.exception("Failed to include router %s with prefix '%s'", getattr(mod, "__name__", str(mod)), prefix)


def include_router_multi_prefix(mod, prefixes: list[str]):
    """Include the same router under multiple prefixes.

    Why: the frontend nginx config proxies /api/* to the backend root (strips "/api"),
    but some clients also call the backend directly with "/api" or "/api/v1".
    Supporting multiple prefixes keeps the system resilient across deployments.
    """
    for p in prefixes:
        include_router_if_present(mod, prefix=p)

# Public API (mount under multiple prefixes for compatibility)
PUBLIC_PREFIXES = ["", "/api", "/v1", "/api/v1"]
include_router_multi_prefix(auth, PUBLIC_PREFIXES)
include_router_multi_prefix(categories, PUBLIC_PREFIXES)
include_router_multi_prefix(products, PUBLIC_PREFIXES)
include_router_multi_prefix(cart, PUBLIC_PREFIXES)
include_router_multi_prefix(favorites, PUBLIC_PREFIXES)
include_router_multi_prefix(orders, PUBLIC_PREFIXES)
include_router_multi_prefix(payment, PUBLIC_PREFIXES)
include_router_multi_prefix(news, PUBLIC_PREFIXES)
include_router_multi_prefix(importer, PUBLIC_PREFIXES)
include_router_multi_prefix(promo, PUBLIC_PREFIXES)
include_router_multi_prefix(manager, PUBLIC_PREFIXES)
include_router_multi_prefix(assistant, PUBLIC_PREFIXES)
include_router_multi_prefix(withdraws, PUBLIC_PREFIXES)

# Admin API (same nginx strip behavior)
ADMIN_PREFIXES = ["/admin", "/api/admin", "/v1/admin", "/api/v1/admin"]
include_router_multi_prefix(admin_products, ADMIN_PREFIXES)
include_router_multi_prefix(admin_orders, ADMIN_PREFIXES)
include_router_multi_prefix(admin_promos, ADMIN_PREFIXES)
include_router_multi_prefix(admin_auth, ADMIN_PREFIXES)
include_router_multi_prefix(admin_dashboard, ADMIN_PREFIXES)
include_router_multi_prefix(admin_managers, ADMIN_PREFIXES)

# uploads and logs
try:
    from app.api.v1 import uploads as uploads_router
    if getattr(uploads_router, "router", None):
        app.include_router(uploads_router.router)
        logger.info("Included uploads router (no prefix)")
except Exception:
    logger.exception("Failed to import/include uploads router")

if recommendations_router:
    try:
        app.include_router(recommendations_router)
        logger.info("Included recommendations router (no prefix)")
    except Exception:
        logger.exception("Failed to include recommendations router")

if logs_router:
    try:
        # Accept logs both when called directly (/api/logs) and via nginx strip (/logs)
        for p in ["/logs", "/api/logs", "/v1/logs", "/api/v1/logs"]:
            app.include_router(logs_router, prefix=p)
            logger.info("Included logs router at %s", p)
    except Exception:
        logger.exception("Failed to include logs router")

# Mount uploaded files AFTER API routers, so POST /uploads is handled by the uploads API
# (and not redirected by the StaticFiles mount).
try:
    app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
    logger.info("Mounted /uploads static directory: %s", str(UPLOADS_DIR))
except Exception:
    logger.exception("Failed to mount /uploads")

@app.get("/health")
def health(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        logger.exception("health check failed: %s", e)
        return {"status": "error", "detail": str(e)}

