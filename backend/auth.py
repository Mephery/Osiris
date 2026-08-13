# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
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
# Cette clé signe les jetons de session : qui la connaît peut en forger un, donc
# se faire passer pour un administrateur. Elle n'a pas de valeur de repli, et
# c'est délibéré — un défaut silencieux serait une valeur *publique*, puisque le
# code est ouvert. Mieux vaut un démarrage qui échoue qu'une authentification qui
# n'authentifie rien. Même exigence que FERNET_KEY (voir crypto.py).
_REPLI_HISTORIQUE = "changeme-generate-a-real-secret"

SECRET_KEY = os.environ.get("JWT_SECRET", "").strip()
if not SECRET_KEY or SECRET_KEY == _REPLI_HISTORIQUE:
    raise RuntimeError(
        "JWT_SECRET manquante ou laissée à sa valeur d'exemple dans .env. "
        "Elle signe les jetons d'authentification : sans secret propre à cette "
        "installation, n'importe qui peut forger un jeton d'administrateur. "
        "En générer une : openssl rand -hex 32"
    )

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
            # Refresh apres commit : session.commit() expire les objets SQLAlchemy,
            # ce qui provoquerait un DetachedInstanceError apres la fermeture de session.
            session.refresh(user)
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


oauth2_scheme_optionnel = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optionnel),
) -> Optional[User]:
    """Utilisateur authentifie s'il l'est, None sinon — sans jamais lever 401.

    Pour les routes que les MACHINES appellent, donc sans identifiants par
    construction, mais dont certaines actions doivent rester reservees aux
    operateurs. Elle permet de trancher action par action plutot que route par
    route : cf. `/machines/{mac}/status`, ouvert aux rapports d'une machine
    (deploying / deployed / failed) mais fermé au `pending` qui, lui, declenche
    une REINSTALLATION.
    """
    if not token:
        return None
    try:
        return get_current_user(token)
    except HTTPException:
        return None


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Reserve aux administrateurs")
    return current_user
