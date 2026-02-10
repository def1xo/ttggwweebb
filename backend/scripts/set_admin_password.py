#!/usr/bin/env python3
import os
import argparse
import sys
import uuid
import runpy
from getpass import getpass
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--telegram-id", required=False, help="Telegram ID of admin (string)")
    parser.add_argument("--username", required=False, help="username")
    parser.add_argument("--password", help="Admin password (optional, will prompt if omitted)")
    parser.add_argument("--database-url", help="Optional DATABASE_URL (env fallback)")
    args = parser.parse_args()

    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        print("Set DATABASE_URL env or pass --database-url")
        return

    if not args.password:
        pw = getpass("Password: ")
    else:
        pw = args.password

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    # import models lazily
    from app.db import models

    user = None
    if args.telegram_id:
        user = session.query(models.User).filter(models.User.telegram_id == str(args.telegram_id)).first()
    if not user and args.username:
        user = session.query(models.User).filter(models.User.username == args.username).first()

    if user:
        print(f"Found existing user id={user.id}, username={user.username}, role={user.role} — updating to admin and setting password.")
        user.role = "admin"
        if hasattr(user, "password_hash"):
            user.password_hash = hash_password(pw)
        elif hasattr(user, "password"):
            setattr(user, "password", hash_password(pw))
        else:
            print("Warning: user model has no password field 'password_hash' or 'password'.")
        session.add(user)
    else:
        print("User not found — creating new admin user.")
        u = models.User(
            telegram_id=str(args.telegram_id) if args.telegram_id else None,
            username=(args.username or f"admin_{uuid.uuid4().hex[:8]}"),
            role="admin",
            
        )
        if hasattr(u, "password_hash"):
            u.password_hash = hash_password(pw)
        elif hasattr(u, "password"):
            setattr(u, "password", hash_password(pw))
        session.add(u)

    session.commit()
    print("Done.")

if __name__ == "__main__":
    main()