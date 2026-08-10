# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
import logging
import os
from cryptography.fernet import Fernet, InvalidToken

_log = logging.getLogger("osiris.crypto")

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
    """Déchiffre un token Fernet → chaîne en clair. Retourne '' si invalide.

    Le '' est volontaire : un secret illisible ne doit pas faire tomber l'appelant,
    qui sait mieux que nous quoi en dire (« Token Proxmox non déchiffrable »,
    « identifiants vCenter absents »…). Mais il ne doit pas non plus disparaître en
    silence : une FERNET_KEY changée rend TOUS les secrets illisibles d'un coup, et
    sans trace on cherche la panne du côté du réseau ou des droits.
    """
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        _log.error("Secret chiffré illisible : FERNET_KEY changée, ou valeur corrompue "
                   "en base. Le secret concerné doit être ressaisi.")
        return ""
    except Exception:
        _log.exception("Échec inattendu du déchiffrement d'un secret")
        return ""
