import hashlib
import hmac
import secrets
from datetime import timedelta, timezone
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from .config import setting
from .db import get_db, insert_if_missing
from .models import User, Session, now, uid

COOKIE = "bioerp_session"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt, digest = encoded.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hmac.new(setting("SESSION_SECRET").encode(), token.encode(), hashlib.sha256).hexdigest()


def public_user(user):
    return {"id": user.id, "email": user.email, "role": user.role}


def bootstrap_accounts(db):
    if not setting("SESSION_SECRET"):
        return
    for role in ("approver", "operator"):
        prefix = f"INITIAL_{role.upper()}"
        email, password = setting(f"{prefix}_EMAIL"), setting(f"{prefix}_PASSWORD")
        if email and password:
            insert_if_missing(db, User, {"id": uid(), "email": email.lower(), "password_hash": hash_password(password), "role": role}, ["email"])
    db.commit()


def current_user(request: Request, db=Depends(get_db)):
    if not setting("SESSION_SECRET"):
        raise HTTPException(503, detail={"code": "setup_required", "message": "Configure SESSION_SECRET and initial account environment variables"})
    token = request.cookies.get(COOKIE)
    session = db.get(Session, token_hash(token)) if token else None
    if not session:
        raise HTTPException(401, "Login required")
    expiry = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
    if expiry <= now():
        raise HTTPException(401, "Session expired")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Invalid session")
    return user


def mutation_user(request: Request, user=Depends(current_user)):
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlsplit
        allowed = {request.headers.get("host", ""), *setting("ALLOWED_ORIGINS").split(",")}
        if urlsplit(origin).netloc not in allowed and origin not in allowed:
            raise HTTPException(403, "Cross-origin mutation rejected")
    return user


def approver(user=Depends(mutation_user)):
    if user.role != "approver":
        raise HTTPException(403, "Approver role required")
    return user
