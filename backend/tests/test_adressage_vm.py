# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Adressage d'une VM : refuser une saisie fautive AVANT de toucher l'hyperviseur.

Régression du 2026-08-14, sur une vraie création. L'adresse avait été saisie sans
son préfixe (« 172.29.12.200 » au lieu de « …/24 ») et partait telle quelle vers
Proxmox, qui exige `ip=<adresse>/<préfixe>`. Le clone réussissait, la configuration
échouait juste après, et le rollback détruisait la VM qui venait de naître : un
aller-retour clone/destruction sur une infrastructure de production, pour une faute
de frappe dans un formulaire.

Le rollback avait raison de faire ce qu'il a fait — il a même vérifié le nom avant
de détruire. C'est de ne pas être arrivé jusque-là qui compte.

Ces tests vérifient donc DEUX choses à chaque fois : que la requête est refusée, et
qu'**aucun appel n'a été fait à l'hyperviseur**.
"""
import pytest
from sqlmodel import Session

import main
from models import Hypervisor, engine


def _hv() -> int:
    with Session(engine) as session:
        h = Hypervisor(name="pve", type="proxmox", url="https://pve.test:8006",
                       token_id="osiris@pve!osiris", token_secret="", pool="osiris")
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


def _mouchard(monkeypatch) -> list:
    """Enregistre tout appel à l'hyperviseur. Doit rester vide sur un refus."""
    appels: list = []

    async def fake_get(h, path):
        appels.append(f"GET {path}")
        return "150" if path.endswith("/cluster/nextid") else {}

    async def fake_post(h, path, data=None):
        appels.append(f"POST {path}")
        return {}

    async def fake_put(h, path, data):
        appels.append(f"PUT {path}")
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_proxmox_put", fake_put)
    return appels


def _creer(client, admin_headers, hv_id, **o):
    corps = dict(hostname="SRV-TEST", client="Acme", os="ubuntu", node="pve",
                 storage="ceph", bridge="vmbr12", boot_mode="cloudinit", template_id=9001)
    corps.update(o)
    return client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json=corps)


# ── Le cas réellement rencontré ───────────────────────────────────────────────

def test_une_adresse_sans_prefixe_est_refusee_sans_rien_creer(client, admin_headers, monkeypatch):
    """LE bug du 14/08 : « 172.29.12.200 » au lieu de « 172.29.12.200/24 »."""
    hv_id = _hv()
    appels = _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id,
                  ip_cidr="172.29.12.200", gateway="172.29.12.1", dns_servers="8.8.8.8")

    assert resp.status_code == 400, resp.text
    d = resp.json()["detail"]
    assert "172.29.12.200/24" in d, "le message doit montrer la forme attendue"
    assert appels == [], f"l'hyperviseur n'aurait pas dû être appelé : {appels}"


def test_une_adresse_en_cidr_passe(client, admin_headers, monkeypatch):
    """Le corollaire : la validation ne doit pas bloquer une saisie correcte."""
    hv_id = _hv()
    _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id,
                  ip_cidr="172.29.12.200/24", gateway="172.29.12.1", dns_servers="8.8.8.8")

    assert resp.status_code != 400, resp.text


# ── La passerelle : l'erreur qui ne lève AUCUNE exception ─────────────────────

def test_une_passerelle_hors_du_reseau_est_refusee(client, admin_headers, monkeypatch):
    """
    Celle-ci ne fait échouer aucun appel : Proxmox l'accepte, la VM démarre, ne
    route nulle part, ne rappelle jamais OSIRIS et reste « en attente » sans un mot.
    C'est le symptôme le plus coûteux de toute la chaîne, donc celui qu'il vaut le
    plus la peine d'attraper à la saisie.
    """
    hv_id = _hv()
    appels = _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id,
                  ip_cidr="172.29.12.200/24", gateway="172.29.99.1")

    assert resp.status_code == 400, resp.text
    assert "hors du réseau" in resp.json()["detail"]
    assert appels == []


def test_une_passerelle_point_a_point_reste_autorisee(client, admin_headers, monkeypatch):
    """En /31 et /32, la passerelle est légitimement hors du réseau de l'interface :
    le contrôle ne doit pas transformer une configuration valide en refus."""
    hv_id = _hv()
    _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id,
                  ip_cidr="172.29.12.200/32", gateway="172.29.99.1",
                  dns_servers="8.8.8.8")

    assert resp.status_code != 400, resp.text


def test_une_passerelle_qui_nest_pas_une_adresse_est_refusee(client, admin_headers, monkeypatch):
    hv_id = _hv()
    appels = _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id,
                  ip_cidr="172.29.12.200/24", gateway="172.29.12.1/24")

    assert resp.status_code == 400, resp.text
    assert "sans préfixe" in resp.json()["detail"], "dire que la passerelle s'écrit nue"
    assert appels == []


def test_une_passerelle_sans_adresse_est_refusee(client, admin_headers, monkeypatch):
    """Laisser l'adresse vide met la VM en DHCP : la passerelle saisie serait ignorée
    en silence, et l'opérateur croirait avoir configuré quelque chose."""
    hv_id = _hv()
    appels = _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id, ip_cidr="", gateway="172.29.12.1")

    assert resp.status_code == 400, resp.text
    assert appels == []


# ── DNS ───────────────────────────────────────────────────────────────────────

def test_un_dns_invalide_est_refuse(client, admin_headers, monkeypatch):
    hv_id = _hv()
    appels = _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id,
                  ip_cidr="172.29.12.200/24", dns_servers="8.8.8.8, pas-une-ip")

    assert resp.status_code == 400, resp.text
    assert appels == []


def test_plusieurs_dns_separes_par_des_virgules_passent(client, admin_headers, monkeypatch):
    hv_id = _hv()
    _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id,
                  ip_cidr="172.29.12.200/24", dns_servers="8.8.8.8, 1.1.1.1")

    assert resp.status_code != 400, resp.text


# ── DHCP : le défaut, qui ne doit rien exiger ────────────────────────────────

def test_sans_aucun_adressage_on_reste_en_dhcp(client, admin_headers, monkeypatch):
    hv_id = _hv()
    _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id, ip_cidr="", gateway="", dns_servers="")

    assert resp.status_code != 400, resp.text


# ── La validation vaut pour TOUS les modes, pas seulement cloud-init ─────────

@pytest.mark.parametrize("mode,extra", [
    ("pxe", {}),
    ("template", {"template_id": 100}),
    ("cloudinit", {"template_id": 9001}),
])
def test_ladressage_est_valide_quel_que_soit_le_mode(client, admin_headers, monkeypatch,
                                                     mode, extra):
    """L'adresse est aussi gravée dans la fiche pour le premier démarrage d'une
    machine physique : une saisie fautive casse ce chemin-là aussi."""
    hv_id = _hv()
    appels = _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id, boot_mode=mode,
                  ip_cidr="172.29.12.200", **extra)

    assert resp.status_code == 400, f"mode {mode} : {resp.text}"
    assert appels == []


# ── L'adresse fixe sans DNS : la panne qui se déclare « déployée » ───────────

def test_une_adresse_fixe_sans_dns_est_refusee(client, admin_headers, monkeypatch):
    """
    Constaté le 18/08 en relisant le code : sans `dns_servers`, OSIRIS n'écrit aucun
    `nameserver` dans cloud-init. En adressage fixe, personne ne prend le relais —
    c'est justement le bail DHCP qui aurait fourni un résolveur.

    Et la panne ne se voit pas. La VM démarre, rappelle OSIRIS (joint par son
    adresse, pas par un nom) et passe « déployée ». Ce qui échoue ensuite ne passe
    que par des noms : `apt-get`, donc les applications du profil et l'agent de
    supervision. On obtient une machine annoncée prête, à moitié vide.
    """
    hv_id = _hv()
    appels = _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id,
                  ip_cidr="172.29.12.200/24", gateway="172.29.12.1", dns_servers="")

    assert resp.status_code == 400, resp.text
    assert "résolveur" in resp.json()["detail"]
    assert appels == [], f"l'hyperviseur n'aurait pas dû être appelé : {appels}"


def test_le_message_propose_les_deux_issues(client, admin_headers, monkeypatch):
    """Renseigner un DNS, ou renoncer à l'adresse fixe. Un refus qui ne dit pas
    comment en sortir se contourne en vidant le champ d'à côté, au hasard."""
    hv_id = _hv()
    _mouchard(monkeypatch)

    d = _creer(client, admin_headers, hv_id, ip_cidr="172.29.12.200/24",
               gateway="172.29.12.1", dns_servers="").json()["detail"]

    assert "DNS" in d and "DHCP" in d


def test_le_dhcp_reste_possible_sans_dns(client, admin_headers, monkeypatch):
    """Le corollaire à ne pas casser : sans adresse fixe, le bail fournit le
    résolveur et l'exiger n'aurait aucun sens."""
    hv_id = _hv()
    _mouchard(monkeypatch)

    resp = _creer(client, admin_headers, hv_id, ip_cidr="", gateway="", dns_servers="")

    assert resp.status_code != 400, resp.text
