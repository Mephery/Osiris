# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Licence WithSecure : celle de l'organisation de la machine, jamais une autre.

La clé d'abonnement (VOUCHER) et l'identifiant de profil WithSecure étaient
écrits dans les arguments d'installation de l'APPLICATION, une application par
client. Le profil de déploiement choisissait laquelle installer, et rien ne
reliait ce choix à l'organisation de la machine : un profil copié depuis celui
d'un autre client enregistrait les postes sur l'abonnement de cet autre client,
sans la moindre erreur.

La clé vit désormais sur l'organisation. L'application unique porte des
marqueurs, remplacés au déploiement par la clé de l'organisation de la machine.
Une organisation sans clé n'a pas de repli : la machine est refusée, et si elle
passait malgré tout, le premier démarrage n'installe pas WithSecure plutôt que
de l'installer sous une licence étrangère.
"""
import re

MARQUEUR_CLE = "%CLE_WITHSECURE%"
MARQUEUR_PROFIL = "%PROFIL_WITHSECURE%"

# Format des clés d'abonnement : 5 groupes de 4, ex. « ABCD-EFGH-1234-5678-WXYZ ».
# Le format strict sert aussi de protection : la clé est recopiée telle quelle
# dans une chaîne PowerShell.
_CLE = re.compile(r"^[A-Z0-9]{4}(-[A-Z0-9]{4}){4}$")
_PROFIL = re.compile(r"^\d{1,12}$")
# Une clé recopiée dans l'application, c'est-à-dire tout ce qui n'est pas le marqueur.
_CLE_EN_DUR = re.compile(r"\bVOUCHER=(?!" + re.escape(MARQUEUR_CLE) + r")", re.IGNORECASE)


def normaliser_cle(brut: str | None) -> str:
    """Clé saisie → forme canonique, ou ValueError. Vide = pas de clé."""
    cle = (brut or "").strip().upper()
    if cle and not _CLE.match(cle):
        raise ValueError("Clé WithSecure invalide : 5 groupes de 4 lettres ou chiffres "
                         "séparés par des tirets, ex. ABCD-EFGH-1234-5678-WXYZ")
    return cle


def normaliser_profil(brut: str | int | None) -> str:
    """Identifiant de profil WithSecure saisi → chiffres, ou ValueError."""
    profil = str(brut if brut is not None else "").strip()
    if profil and not _PROFIL.match(profil):
        raise ValueError("Identifiant de profil WithSecure invalide : des chiffres uniquement")
    return profil


def refus(app, cle: str, profil: str, nom_org: str) -> str | None:
    """Pourquoi cette application ne peut pas être installée pour cette organisation.

    None = rien ne s'y oppose (y compris pour toute application sans licence).
    """
    args = app.install_args or ""
    if _CLE_EN_DUR.search(args):
        return (f"{app.name} porte sa propre clé de licence dans ses arguments "
                f"d'installation : elle doit venir de l'organisation (marqueur {MARQUEUR_CLE})")
    qui = nom_org or "une machine sans organisation"
    if MARQUEUR_CLE in args and not cle:
        return f"{app.name} : pas de clé WithSecure pour {qui}"
    if MARQUEUR_PROFIL in args and not profil:
        return f"{app.name} : pas d'identifiant de profil WithSecure pour {qui}"
    return None


def args_installation(app, cle: str, profil: str) -> str:
    """Arguments d'installation avec la licence de l'organisation à la place des marqueurs."""
    return (app.install_args or "").replace(MARQUEUR_CLE, cle).replace(MARQUEUR_PROFIL, profil)
