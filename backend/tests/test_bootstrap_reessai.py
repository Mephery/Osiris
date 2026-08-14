# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""L'agent d'amorçage doit réessayer, et dire quand il renonce.

Régression du 2026-08-14. Une VM avait été créée avant que son chemin réseau soit
ouvert. L'agent a tenté de joindre OSIRIS pendant un quart d'heure, a renoncé, et
**a rendu 0**. systemd affichait alors « active (exited) », donc :

- `systemctl status` disait « réussi » ;
- la supervision ne voyait aucune unité en échec ;
- la fiche OSIRIS restait « en attente », exactement comme si la machine
  attendait encore — alors que plus personne n'appelait.

Il a fallu un `systemctl restart` à la main pour débloquer la situation, et une
demi-journée pour comprendre que le silence venait de là.

Deux corrections, vérifiées ici : renoncer est une ERREUR, et l'unité réessaie
d'elle-même au lieu de s'arrêter définitivement.
"""
import re

import pytest


@pytest.fixture
def agent(client):
    """Le script d'amorçage tel qu'OSIRIS le sert réellement."""
    resp = client.get("/bootstrap/linux")
    assert resp.status_code == 200
    return resp.text


# ── Renoncer n'est pas réussir ────────────────────────────────────────────────

def test_labandon_sort_en_erreur(agent):
    """`exit 0` disait « réussi » à systemd et rendait la panne invisible."""
    fin = agent.split("Abandon apres")[1]

    assert "exit 1" in fin.split("OSIRIS_BOOTSTRAP_EOF")[0], \
        "renoncer doit rendre un code non nul, sinon systemd affiche « active (exited) »"


def test_le_succes_reste_un_succes(agent):
    """Le chemin nominal ne doit pas devenir un échec au passage : quand la fiche
    est trouvée, le script passe la main au script de premier démarrage."""
    assert "exec /bin/bash \"$SCRIPT\"" in agent


# ── L'unité réessaie ─────────────────────────────────────────────────────────

def test_lunite_reessaie_apres_un_echec(agent):
    """Sans ça, une VM démarrée trop tôt n'essaie plus jamais avant un reboot."""
    unite = agent.split("osiris-firstboot.service << 'OSIRIS_UNIT_EOF'")[1]

    assert "Restart=on-failure" in unite
    m = re.search(r"RestartSec=(\d+)", unite)
    assert m, "un délai entre deux tentatives est nécessaire"
    assert 30 <= int(m.group(1)) <= 600, \
        f"délai de {m.group(1)}s : trop court, on martèle ; trop long, on n'aide plus"


def test_le_type_dunite_autorise_le_reessai(agent):
    """systemd REFUSE `Restart=` sur un `Type=oneshot` : l'unité ne démarrerait
    même pas. Le type et la politique de redémarrage doivent être cohérents."""
    unite = agent.split("osiris-firstboot.service << 'OSIRIS_UNIT_EOF'")[1]

    assert "Type=oneshot" not in unite, "incompatible avec Restart="
    assert "Type=simple" in unite


def test_lunite_nest_pas_desactivee_par_labandon(agent):
    """Seul le script de premier démarrage désactive l'unité, une fois qu'il a
    réellement tourné. Renoncer ne doit pas rendre la VM définitivement orpheline."""
    fin = agent.split("Abandon apres")[1].split("OSIRIS_BOOTSTRAP_EOF")[0]

    assert "disable" not in fin


# ── Les horodatages disent dans quelle horloge ils parlent ───────────────────

def test_lhorodatage_porte_son_fuseau(agent):
    """Une image cloud tourne en UTC, l'exploitant lit en heure locale. Sans le
    fuseau, deux horloges se mélangent dans le même journal sans que personne ne
    le voie — deux heures d'écart le 2026-08-14, et un diagnostic faussé."""
    assert "%Z" in agent, "l'horodatage de l'agent doit nommer son fuseau"


def test_lhorodatage_du_premier_demarrage_aussi(client, test_machine):
    """Ces lignes-là finissent dans le journal de déploiement d'OSIRIS, mêlées à
    des horodatages produits par le serveur : c'est là que la confusion coûte."""
    resp = client.get(f"/firstboot-linux/{test_machine.mac}")

    assert resp.status_code == 200, resp.text
    assert "%Z" in resp.text or "date '+%H:%M:%S %Z'" in resp.text


# ── Le diagnostic déjà en place ne doit pas régresser ────────────────────────

def test_les_causes_dechec_restent_distinguees(agent):
    """Acquis d'une session précédente : 404, 30x et serveur injoignable donnaient
    le même silence, et le journal accusait l'absence de fiche dans les trois cas."""
    for indice in ("serveur injoignable", "pas de fiche pour cette MAC", "REDIRECTION"):
        assert indice in agent, f"le diagnostic « {indice} » a disparu"
