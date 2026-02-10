# backend/app/db/session.py
import os
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

# Production-ready settings:
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://tgshop:tgshop@db:5432/tgshop")

POOL_SIZE = int(os.getenv("SQLALCHEMY_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "20"))
POOL_PRE_PING = True

# If you want to disable pooling for some envs, you can use NullPool
engine = create_engine(
    DATABASE_URL,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_pre_ping=POOL_PRE_PING,
    future=True,
)

# session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# generator for FastAPI dependency injection
def get_db():
    """
    FastAPI dependency that yields a DB session and ensures it is closed.
    Usage: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.close()
        except Exception:
            pass
