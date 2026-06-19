"""
Utilitaires d'authentification : hachage de mots de passe et tokens JWT.

Un JWT (JSON Web Token) c'est un ticket signé que le serveur émet à la connexion.
Le client le renvoie dans chaque requête. Le serveur vérifie la signature — si elle
est valide, il sait qui fait la requête sans interroger la base de données.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlmodel import Session, select

from models import User, engine

# ── Config ─────────────────────────────────────────────────────────────────────
SECRET_KEY      = os.environ.get("JWT_SECRET", "changeme-generate-a-real-secret")
ALGORITHM       = "HS256"
TOKEN_EXPIRE_H  = 12   # le token expire après 12 heures

# CryptContext gère le hachage bcrypt des mots de passe utilisateurs
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2PasswordBearer dit à FastAPI où trouver le token dans les requêtes
# (dans l'en-tête Authorization: Bearer <token>)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Mots de passe ──────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── Tokens JWT ─────────────────────────────────────────────────────────────────

def create_token(user_id: int, role: str) -> str:
    """Crée un JWT signé contenant l'id et le rôle de l'utilisateur."""
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_H)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    Dépendance FastAPI : décode le token et retourne l'utilisateur.
    Si le token est absent, expiré ou falsifié → 401.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
    """Dépendance : bloque l'accès si l'utilisateur n'est pas admin."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    return current_user
