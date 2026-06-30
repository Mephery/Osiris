# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
import os
from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("FERNET_KEY", "")
        if not key:
            raise RuntimeError("FERNET_KEY manquante dans .env")
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt(value: str) -> str:
    """Chiffre une chaîne en clair → token Fernet (str)."""
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Déchiffre un token Fernet → chaîne en clair. Retourne '' si invalide."""
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, Exception):
        return ""
