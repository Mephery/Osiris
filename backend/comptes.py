# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le compte d'une personne précise sur UNE VM Linux : un nom, une clé SSH, sudo ou non.

Distinct du compte d'administration du profil (`humans`), posé sur toutes les VM
du profil : celui-ci n'existe que sur la machine demandée — le développeur d'un
client, par exemple. La clé est OBLIGATOIRE : les VM refusent la connexion SSH
par mot de passe, un compte sans clé existerait sans que personne puisse y entrer.
"""
import base64
import re
import struct
from typing import Optional

from fastapi import HTTPException
from sqlmodel import SQLModel

NOM_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
# Comptes que l'image porte déjà ou qu'OSIRIS installe : y poser une clé
# ouvrirait un compte système, ou détournerait celui de l'agent de supervision.
RESERVES = {"root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news",
            "uucp", "proxy", "www-data", "backup", "list", "irc", "gnats", "nobody",
            "_apt", "messagebus", "sshd", "zabbix", "polkitd", "syslog", "uuidd",
            "tcpdump", "tss", "landscape", "fwupd-refresh", "usbmux", "dnsmasq"}
TYPES_CLE = ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384",
             "ecdsa-sha2-nistp521", "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com")


class CompteVm(SQLModel):
    nom: str
    cle_ssh: str
    sudo: bool = False


def _type_encode(corps: str) -> str:
    """Le type de clé inscrit DANS la clé, si elle est entière ; « » sinon.

    Une clé publique est une suite de champs précédés de leur longueur (type,
    puis les nombres de la clé). Elle doit se lire EXACTEMENT jusqu'au dernier
    octet : tronquée au copier-coller, elle annonce un champ plus long que ce
    qui reste. Ne regarder que le type ne suffisait pas — une clé coupée sur un
    multiple de 4 caractères reste du base64 valide et commence bien."""
    try:
        brut = base64.b64decode(corps, validate=True)
    except Exception:
        return ""
    champs, i = [], 0
    while i < len(brut):
        if i + 4 > len(brut):
            return ""
        (longueur,) = struct.unpack(">I", brut[i:i + 4])
        if i + 4 + longueur > len(brut):
            return ""
        champs.append(brut[i + 4:i + 4 + longueur])
        i += 4 + longueur
    if len(champs) < 2:
        return ""
    try:
        return champs[0].decode("ascii")
    except UnicodeDecodeError:
        return ""


def valider_compte(compte: Optional["CompteVm"], utilisateur_profil: str = "") -> Optional[dict]:
    """Le compte normalisé, ou un 422 qui dit quoi corriger. None = pas de compte."""
    if compte is None or not (compte.nom.strip() or compte.cle_ssh.strip()):
        return None
    nom = compte.nom.strip()
    cle = " ".join(compte.cle_ssh.split())   # une clé collée sur plusieurs lignes
    morceaux = cle.split(" ")
    erreur = (
        f"le nom « {nom} » doit commencer par une minuscule et ne contenir que des "
        "minuscules, chiffres, - et _ (32 caractères au plus)" if not NOM_RE.fullmatch(nom)
        else f"« {nom} » est un compte du système : choisir un autre nom"
            if nom in RESERVES or nom.startswith("systemd-")
        else f"« {nom} » est déjà le compte d'administration du profil"
            if nom == (utilisateur_profil or "").strip()
        else "la clé SSH est obligatoire : sans elle, personne ne pourrait se connecter "
             "(la connexion par mot de passe est désactivée)" if not cle
        else "la clé SSH doit commencer par son type (ssh-ed25519, ssh-rsa, ecdsa-…)"
            if len(morceaux) < 2 or morceaux[0] not in TYPES_CLE
        else "la clé SSH semble tronquée ou altérée : la recopier entièrement depuis le fichier .pub"
            if _type_encode(morceaux[1]) != morceaux[0]
        else ""
    )
    if erreur:
        raise HTTPException(status_code=422, detail=f"Compte de la VM : {erreur}.")
    return {"nom": nom, "cle_ssh": cle, "sudo": bool(compte.sudo)}
