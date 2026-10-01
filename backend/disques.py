# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les disques supplémentaires d'une VM Linux : ce qu'on accepte, et comment on les nomme.

Un seul disque /data existait, et sa taille voyageait mal : l'hyperviseur recevait
celle du formulaire, le premier démarrage celle du PROFIL. Un profil à 0 et un
formulaire à 20 Go donnaient un disque créé que personne ne formatait. La liste
des disques est désormais enregistrée sur la fiche de la machine, et c'est elle
que lisent l'hyperviseur ET le premier démarrage.

Chaque disque porte un libellé, que l'on retrouve partout dans la VM :
- `lsblk` : le volume LVM s'appelle `vg_<libellé>-<libellé>` ;
- `lsblk -f` : l'étiquette du système de fichiers ;
- `lsblk -o SERIAL` (Proxmox) : le numéro de série du disque, qui sert aussi à
  le RETROUVER sans se fier à /dev/sdb — un nom qui peut changer d'un
  démarrage à l'autre.
"""
import json
import re

from fastapi import HTTPException
from sqlmodel import SQLModel

MAX_DISQUES = 4
SYSTEMES = ("ext4", "xfs")

# ── Schéma de partition du disque système (gabarit LVM, convention figée) ───────
# UEFI : partition EFI + /boot, puis UN groupe LVM « osiris » qui porte le système
# (/ = LV root), le swap (LV) et les volumes extras (LV). Un seul disque, comme le
# standard de l'équipe (cf. leur lsblk). Le gabarit livre un / MINIMAL avec de
# l'espace libre dans le VG : l'agent AGRANDIT / et CRÉE les LV au premier
# démarrage — on ne réduit jamais un système monté.
EFI_MB = 512            # partition système EFI (UEFI)
BOOT_GB = 1             # /boot (demande de l'équipe : >= 1 Go, plus sûr)
VG_NOM = "osiris"       # nom du groupe de volumes LVM du gabarit
ROOT_GB_DEFAUT = 200    # taille de / par défaut (modifiable)
SWAP_GB_DEFAUT = 2      # taille du swap par défaut (modifiable)
ROOT_GB_MIN = 10        # en deçà, un serveur ne tient pas
SWAP_GB_MIN = 1


def schema_partition(root_gb: int = ROOT_GB_DEFAUT, swap_gb: int = SWAP_GB_DEFAUT,
                     extras: list[dict] | None = None, uefi: bool = True) -> dict:
    """Le schéma complet d'un disque système LVM : la liste des « tranches » (pour
    l'aperçu du formulaire) et la TAILLE TOTALE du disque à provisionner.

    Un seul disque : [EFI] + /boot + VG osiris { swap, /, extras… }. Les tailles
    s'additionnent — c'est cette somme que l'hyperviseur doit créer.
    """
    extras = extras or []
    tranches = []
    if uefi:
        tranches.append({"nom": "EFI", "montage": "/boot/efi", "taille_gb": EFI_MB / 1024,
                         "fs": "vfat", "type": "partition"})
    tranches.append({"nom": "boot", "montage": "/boot", "taille_gb": BOOT_GB,
                     "fs": "ext4", "type": "partition"})
    tranches.append({"nom": "swap", "montage": "swap", "taille_gb": swap_gb,
                     "fs": "swap", "type": "lvm"})
    tranches.append({"nom": "root", "montage": "/", "taille_gb": root_gb,
                     "fs": "ext4", "type": "lvm"})
    for d in extras:
        tranches.append({"nom": d["libelle"], "montage": d["point_montage"],
                         "taille_gb": d["taille_gb"], "fs": d["systeme_fichiers"],
                         "type": "lvm"})
    total = sum(t["taille_gb"] for t in tranches)
    return {"vg": VG_NOM, "uefi": uefi, "tranches": tranches,
            "total_gb": int(total) + (1 if total != int(total) else 0)}


def valider_systeme(root_gb: int, swap_gb: int) -> None:
    """Garde-fous sur / et swap, ou un 422 qui dit quoi corriger."""
    if not ROOT_GB_MIN <= root_gb <= 16384:
        raise HTTPException(status_code=422,
                            detail=f"La taille de / doit être comprise entre {ROOT_GB_MIN} et 16384 Go.")
    if not SWAP_GB_MIN <= swap_gb <= 256:
        raise HTTPException(status_code=422,
                            detail=f"La taille du swap doit être comprise entre {SWAP_GB_MIN} et 256 Go.")
# xfs limite l'étiquette à 12 caractères : la même borne pour tous, pour qu'un
# changement de système de fichiers ne rende pas un libellé soudain invalide.
LIBELLE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,11}$")
# Monter un disque vierge par-dessus l'un de ceux-là masquerait le système.
MONTAGES_INTERDITS = {"/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc",
                      "/run", "/sbin", "/sys", "/tmp", "/usr", "/var", "/root"}
MONTAGE_RE = re.compile(r"^(/[a-zA-Z0-9._-]+)+$")


class DisqueVm(SQLModel):
    taille_gb: int
    point_montage: str
    libelle: str = ""
    lvm: bool = True
    systeme_fichiers: str = "ext4"


def libelle_depuis_montage(montage: str) -> str:
    """« /var/lib/mysql » → « mysql » : le dernier élément, ramené à ce qu'un
    libellé accepte. Proposé par défaut, modifiable."""
    dernier = montage.rstrip("/").rsplit("/", 1)[-1].lower()
    return re.sub(r"[^a-z0-9_-]", "-", dernier).strip("-_")[:12] or "data"


def valider_disques(disques: list, data_disk_gb: int = 0) -> list[dict]:
    """La liste normalisée des disques, ou un 422 qui dit précisément quoi corriger.

    `data_disk_gb` : l'ancien champ unique, encore envoyé par un client qui ne
    connaît pas la liste. Il devient un disque /data, en LVM et ext4, exactement
    ce qu'il produisait avant."""
    if not disques and data_disk_gb:
        disques = [DisqueVm(taille_gb=data_disk_gb, point_montage="/data", libelle="data")]
    if len(disques) > MAX_DISQUES:
        raise HTTPException(status_code=422, detail=f"Au plus {MAX_DISQUES} disques supplémentaires.")
    propres, montages, libelles = [], set(), set()
    for i, d in enumerate(disques, start=1):
        d = d if isinstance(d, DisqueVm) else DisqueVm(**d)
        montage = d.point_montage.strip().rstrip("/") or "/"
        libelle = (d.libelle or libelle_depuis_montage(montage)).strip().lower()
        erreur = (
            "sa taille doit être comprise entre 1 et 16384 Go" if not 1 <= d.taille_gb <= 16384
            else f"le point de montage « {montage} » doit être un chemin absolu simple (ex : /data)"
                if not MONTAGE_RE.fullmatch(montage)
            else f"« {montage} » est un répertoire du système : y monter un disque vierge le masquerait"
                if montage in MONTAGES_INTERDITS
            else f"« {montage} » est déjà utilisé par un autre disque" if montage in montages
            else f"le libellé « {libelle} » doit faire 1 à 12 caractères : minuscules, chiffres, - et _"
                if not LIBELLE_RE.fullmatch(libelle)
            else f"le libellé « {libelle} » est déjà utilisé par un autre disque" if libelle in libelles
            else f"système de fichiers « {d.systeme_fichiers} » inconnu (ext4 ou xfs)"
                if d.systeme_fichiers not in SYSTEMES
            else ""
        )
        if erreur:
            raise HTTPException(status_code=422, detail=f"Disque {i} : {erreur}.")
        montages.add(montage)
        libelles.add(libelle)
        propres.append({"taille_gb": d.taille_gb, "point_montage": montage, "libelle": libelle,
                        "lvm": d.lvm, "systeme_fichiers": d.systeme_fichiers})
    return propres


def disques_de(fiche: str) -> list[dict]:
    """La liste enregistrée sur une fiche machine (JSON), vide si absente ou illisible."""
    try:
        valeur = json.loads(fiche or "[]")
    except ValueError:
        return []
    return valeur if isinstance(valeur, list) else []


def config_proxmox(disques: list[dict], storage: str, bus: str = "scsi", fmt: str = "") -> dict:
    """Les entrées de configuration Proxmox des disques : scsi1, scsi2…, chacun
    avec son libellé en numéro de série — c'est par lui que le premier
    démarrage retrouve le bon disque."""
    return {f"{bus}{i}": f"{storage}:{d['taille_gb']}{fmt},serial={d['libelle']}"
            for i, d in enumerate(disques, start=1)}
