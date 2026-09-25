# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le jeton d'une machine : ce qui prouve qu'un appel vient bien d'ELLE.

Les machines appellent OSIRIS sans compte : pour chercher leur script (qui porte
le compte de jonction au domaine, le mot de passe BIOS…) et pour rendre compte
(journal, smoke tests, LAPS, BitLocker). Jusqu'ici, connaître une MAC suffisait —
or une MAC n'a rien de secret : elle circule sur le réseau local et figure sur
l'étiquette du poste.

Le jeton est un secret aléatoire propre à la machine, renouvelé à chaque
redéploiement. Il voyage DANS le script qu'elle télécharge : la première demande
d'une fenêtre de déploiement le reçoit (remise unique), toutes les suivantes
doivent le présenter. OSIRIS n'en garde que l'empreinte.

Il ne peut pas expirer à la fin du déploiement : la rotation LAPS, des mois plus
tard, est un appel de la machine installée.

Mode transition (défaut) : tant que les gabarits n'ont pas été rescellés, leurs
agents n'envoient pas de jeton. Un appel SANS jeton est alors accepté mais
consigné ; un jeton FAUX est toujours refusé. `OSIRIS_JETON_OBLIGATOIRE=1`
refuse aussi l'absence, une fois tous les gabarits rescellés.
"""
import hashlib
import hmac
import os
import secrets

ENTETE = "X-Osiris-Jeton"


def obligatoire() -> bool:
    """Relu à chaque appel : basculer ne demande qu'un redémarrage de l'API."""
    return os.environ.get("OSIRIS_JETON_OBLIGATOIRE", "").strip().lower() in ("1", "true", "oui", "yes")


def nouveau() -> tuple[str, str]:
    """(jeton en clair, empreinte). Le clair part dans le script, jamais en base."""
    clair = secrets.token_urlsafe(32)
    return clair, empreinte(clair)


def empreinte(clair: str) -> str:
    return hashlib.sha256(clair.encode()).hexdigest()


def correspond(presente: str, empreinte_attendue: str) -> bool:
    """Comparaison en temps constant : la durée ne doit rien dire du jeton."""
    return bool(presente and empreinte_attendue) and hmac.compare_digest(
        empreinte(presente), empreinte_attendue)
