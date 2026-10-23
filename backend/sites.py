# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Sites distants : ce que leur cache doit avoir, et s'il l'a.

Chaque nuit, le cache d'un site recopie depuis OSIRIS (rsync, en lecture seule)
tout ce qu'un PC peut demander, puis rend compte : réussite ou erreur, et la
liste des images Windows qu'il possède. OSIRIS compare cette liste aux siennes.

La comparaison porte sur les images parce que c'est là qu'un écart fait du tort
sans bruit : un PC du site installerait l'ancienne version, journal au vert.
Pour le reste (pilotes, WinPE, installeurs), rsync garantit l'égalité à la fin
d'une copie réussie ; c'est donc l'âge de la dernière réussite qui le couvre.
"""
import fnmatch
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

# Ce que le cache ne recopie pas : les sauvegardes d'images ratées ou anciennes,
# et les ISO (montées par les hyperviseurs, jamais demandées par un PC). La même
# liste figure dans deploy/cache/rsyncd-cache.conf.example — un test y veille.
EXCLUSIONS = ("*.bak*", "*.ko-*", "*.iso")

EXTENSIONS_IMAGE = (".wim", ".esd")

# Au-delà, la copie de nuit a manqué au moins une nuit entière.
RETARD_MAX = timedelta(hours=36)


def exclu(nom: str) -> bool:
    return any(fnmatch.fnmatch(nom, motif) for motif in EXCLUSIONS)


def images_presentes(dossier: str) -> list[dict]:
    """Les images Windows d'un dossier, telles que le cache les recevra.

    Même forme que celle que le cache envoie : nom, taille, date de modification
    (rsync la conserve, elle est donc comparable d'un côté à l'autre).
    """
    images = []
    try:
        noms = sorted(os.listdir(dossier))
    except OSError:
        return []
    for nom in noms:
        if not nom.lower().endswith(EXTENSIONS_IMAGE) or exclu(nom):
            continue
        chemin = os.path.join(dossier, nom)
        try:
            st = os.stat(chemin)
        except OSError:
            continue
        if os.path.isfile(chemin):
            images.append({"nom": nom, "taille": st.st_size, "mtime": int(st.st_mtime)})
    return images


def lire_images(texte: str) -> list[dict]:
    """La liste stockée en base, ou vide si elle est illisible."""
    try:
        valeur = json.loads(texte or "[]")
    except ValueError:
        return []
    return [i for i in valeur if isinstance(i, dict) and "nom" in i] if isinstance(valeur, list) else []


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    """SQLite rend des dates naïves ; elles sont stockées en UTC."""
    if d is not None and d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def ecarts(attendues: list[dict], cache: list[dict],
           copie_reussie_le: Optional[datetime]) -> list[dict]:
    """Une ligne par image qui diffère entre OSIRIS et le cache.

    Une image modifiée sur OSIRIS APRÈS la dernière copie réussie est un écart
    normal : la copie de la nuit suivante l'apportera. On le dit, pour qu'un
    opérateur ne cherche pas une panne là où il n'y en a pas.
    """
    sur_cache = {i["nom"]: i for i in cache}
    sur_osiris = {i["nom"]: i for i in attendues}
    depuis = _aware(copie_reussie_le)
    lignes = []
    for nom, attendue in sur_osiris.items():
        recente = depuis is None or attendue["mtime"] > depuis.timestamp()
        presente = sur_cache.get(nom)
        if presente is None:
            probleme = "absente du cache"
        elif presente.get("taille") != attendue["taille"] or presente.get("mtime") != attendue["mtime"]:
            probleme = "différente sur le cache"
        else:
            continue
        lignes.append({"nom": nom, "probleme": probleme, "attendue_cette_nuit": recente})
    for nom in sur_cache:
        if nom not in sur_osiris:
            # Inoffensif : aucun profil ne peut la désigner si OSIRIS ne l'a plus.
            # rsync --delete la retirera ; on le signale sans s'en alarmer.
            lignes.append({"nom": nom, "probleme": "en trop sur le cache", "attendue_cette_nuit": True})
    return lignes


def etat(site, attendues: list[dict], maintenant: Optional[datetime] = None) -> dict:
    """État d'un site, en clair pour l'opérateur : un code, une phrase, les écarts."""
    maintenant = maintenant or datetime.now(timezone.utc)
    reussie = _aware(site.copie_reussie_le)
    liste = ecarts(attendues, lire_images(site.images), reussie)
    graves = [e for e in liste if not e["attendue_cette_nuit"]]

    if site.rapport_le is None:
        code, message = "jamais", (
            "Le cache n'a encore jamais rendu compte : il n'est pas installé, "
            "ou sa première copie n'est pas terminée.")
    elif site.erreur and site.inachevee:
        # Combien de temps sans copie complète : c'est ce qui sépare « première copie
        # en cours » de « la fenêtre est trop courte pour ce site ».
        reference = reussie or _aware(site.cree_le) or maintenant
        jours = int((maintenant - reference).total_seconds() // 86400)
        code, message = "inachevee", (
            "Copie inachevée : la fenêtre de nuit s'est terminée avant la fin. Ce qui a été "
            "reçu est gardé, et la nuit prochaine reprend là. Normal pour une première copie "
            "ou une grosse image" + (
                f" ; mais aucune copie complète depuis {jours} j : la fenêtre ou le débit "
                "sont trop justes pour ce site." if jours >= 3 else "."))
    elif site.erreur:
        code, message = "echec", (
            f"La dernière copie a échoué : {site.erreur}. "
            "Le cache sert toujours ce qu'il avait avant.")
    elif reussie is None or maintenant - reussie > RETARD_MAX:
        heures = int((maintenant - reussie).total_seconds() // 3600) if reussie else None
        code, message = "en_retard", (
            f"Aucune copie réussie depuis {heures} h. " if heures is not None else
            "Aucune copie réussie à ce jour. ") + (
            "Le cache est peut-être éteint, ou ne joint plus OSIRIS.")
    elif graves:
        code, message = "images_differentes", (
            "Le cache n'a pas les mêmes images qu'OSIRIS alors que sa dernière copie "
            "a réussi : un PC de ce site pourrait recevoir une autre version.")
    elif liste:
        code, message = "a_jour", "À jour ; des images modifiées arriveront avec la copie de cette nuit."
    else:
        code, message = "a_jour", "À jour."
    return {"code": code, "message": message, "ecarts": liste}
