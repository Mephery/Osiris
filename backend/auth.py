"""
Utilitaires d'authentification : hachage de mots de passe et tokens JWT.
"""
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from models import ApiKey, User, engine

# ── Config ─────────────────────────────────────────────────────────────────────
SECRET_KEY      = os.environ.get("JWT_SECRET", "changeme-generate-a-real-secret")
ALGORITHM       = "HS256"
TOKEN_EXPIRE_H  = 12
TEMP_TOKEN_EXPIRE_MIN = 5   # token temporaire 2FA : valable 5 minutes

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Mots de passe ──────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Tokens JWT ─────────────────────────────────────────────────────────────────

def create_token(payload: dict) -> str:
    """Cree un JWT signe. payload doit contenir sub, role, email."""
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_H)
    return jwt.encode({**payload, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def create_temp_token(user_id: str) -> str:
    """Token temporaire emis apres le mot de passe, avant verification TOTP."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=TEMP_TOKEN_EXPIRE_MIN)
    return jwt.encode({"sub": user_id, "scope": "totp", "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_temp_token(token: str) -> Optional[dict]:
    """Decode et valide un token temporaire TOTP. Retourne None si invalide."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("scope") != "totp":
            return None
        return payload
    except JWTError:
        return None


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expire",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Cle API personnelle
    if token.startswith("osiris_sk_"):
        prefix = token[:16]
        key_hash = hashlib.sha256(token.encode()).hexdigest()
        with Session(engine) as session:
            api_key = session.exec(select(ApiKey).where(ApiKey.prefix == prefix)).first()
            if not api_key or api_key.key_hash != key_hash:
                raise credentials_error
            user = session.get(User, api_key.user_id)
            if not user:
                raise credentials_error
            # Mise a jour last_used_at (best-effort, pas bloquant)
            api_key.last_used_at = datetime.now(timezone.utc)
            session.add(api_key)
            session.commit()
        return user

    # JWT standard
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("scope") == "totp":
            raise credentials_error
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise credentials_error
    except JWTError:
        raise credentials_error

    with Session(engine) as session:
        user = session.get(User, int(user_id))
    if user is None:
        raise credentials_error
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Reserve aux administrateurs")
    return current_user
