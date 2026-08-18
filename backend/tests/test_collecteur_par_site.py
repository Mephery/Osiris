# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le collecteur Zabbix appartient au SITE, pas au propriétaire de la machine.

Il n'était déclaré que sur l'organisation. Une organisation dont les machines
vivent sur plusieurs sites ne pouvait donc en désigner qu'un seul : toutes ses VM
visaient le même collecteur, où qu'elles tournent.

Ce n'est pas une préférence d'architecture, cela se paie en pare-feu. Une VM qui
parle à un collecteur distant traverse tous les filtres du trajet, et il faut une
autorisation sur chacun — dont rien ne signale l'absence : l'agent se tait, et il
faut aller chercher pourquoi. Or chaque site a déjà son propre relais, sur le
sous-réseau même des VM. Visé depuis l'hyperviseur, il ne rencontre aucun filtre.

L'organisation reste le défaut : c'est le seul champ dont dispose une machine
physique, qui n'a pas d'hyperviseur.
"""
import pytest
from sqlmodel import Session

import main
from models import Hypervisor, Machine, Organization, Profile, engine

PROXY_SITE = "172.29.12.50"       # le relais du site où tourne la VM
PROXY_CENTRAL = "10.231.248.130"  # celui déclaré par l'organisation


def _org(slug="acme", collecteur="") -> Organization:
    with Session(engine) as session:
        o = Organization(name="Acme", slug=slug, zabbix_server=collecteur)
        session.add(o)
        session.commit()
        session.refresh(o)
        return o


def _hv(collecteur="") -> Hypervisor:
    with Session(engine) as session:
        h = Hypervisor(name="Nova", type="proxmox", url="https://pve.test:8006",
                       token_id="osiris@pve!osiris", token_secret="",
                       zabbix_server=collecteur)
        session.add(h)
        session.commit()
        session.refresh(h)
        return h


def _machine(supervisee=True) -> Machine:
    return Machine(mac="aabbccddeeff", hostname="SRV-TEST", client="Acme",
                   os="ubuntu", supervised=supervisee)


# ── Qui l'emporte ────────────────────────────────────────────────────────────

def test_le_collecteur_de_lhyperviseur_lemporte(clean_db):
    """Une VM parle au relais de SON site, quel que soit le client à qui elle
    appartient — c'est ce qui évite d'ouvrir un flux à travers chaque pare-feu."""
    ctx = main._zabbix_context(_machine(), _org(collecteur=PROXY_CENTRAL),
                               _hv(collecteur=PROXY_SITE))

    assert ctx["server"] == PROXY_SITE


def test_lorganisation_reste_le_defaut(clean_db):
    """Un hyperviseur sans collecteur ne doit rien casser : le comportement des
    installations en place ne change pas d'un pouce."""
    ctx = main._zabbix_context(_machine(), _org(collecteur=PROXY_CENTRAL), _hv())

    assert ctx["server"] == PROXY_CENTRAL


def test_une_machine_physique_utilise_son_organisation(clean_db):
    """Elle n'a pas d'hyperviseur : c'est le seul champ dont elle dispose."""
    ctx = main._zabbix_context(_machine(), _org(collecteur=PROXY_CENTRAL), None)

    assert ctx["server"] == PROXY_CENTRAL


def test_un_hyperviseur_suffit_sans_organisation(clean_db):
    """Le collecteur dit à qui parler ; l'organisation ne sert qu'à ranger l'hôte.
    Une VM sans client déclaré peut être supervisée."""
    ctx = main._zabbix_context(_machine(), None, _hv(collecteur=PROXY_SITE))

    assert ctx["server"] == PROXY_SITE
    assert ctx["metadata"] == "osiris linux"


def test_les_espaces_autour_de_ladresse_sont_retires(clean_db):
    """Collée depuis un pare-feu ou un ticket, l'adresse traîne souvent un espace ;
    il finirait tel quel dans `ServerActive` et l'agent ne joindrait personne."""
    ctx = main._zabbix_context(_machine(), None, _hv(collecteur=f"  {PROXY_SITE} "))

    assert ctx["server"] == PROXY_SITE


# ── Quand on n'installe rien ─────────────────────────────────────────────────

def test_sans_aucun_collecteur_on_ninstalle_pas_dagent(clean_db):
    """Un agent sans adresse à qui parler est un service qui démarre, échoue en
    silence et fait croire que la machine est supervisée."""
    assert main._zabbix_context(_machine(), _org(), _hv()) is None


def test_une_machine_non_supervisee_reste_non_supervisee(clean_db):
    """La case de la fiche prime sur toute adresse trouvée."""
    assert main._zabbix_context(_machine(supervisee=False), None,
                                _hv(collecteur=PROXY_SITE)) is None


# ── De bout en bout : ce que la VM reçoit réellement ─────────────────────────

def test_le_script_de_premier_demarrage_porte_le_bon_collecteur(client, clean_db):
    """Le seul test qui prouve la chaîne complète : c'est ce fichier-là que la VM
    écrit dans sa configuration d'agent."""
    org, hv = _org(collecteur=PROXY_CENTRAL), _hv(collecteur=PROXY_SITE)
    with Session(engine) as session:
        profil = Profile(name="Serveur Linux", os="ubuntu", locale="fr-FR")
        session.add(profil)
        session.commit()
        session.refresh(profil)
        session.add(Machine(mac="aabbccddeeff", hostname="SRV-NOVA", client="Acme",
                            os="ubuntu", profile_id=profil.id,
                            organization_id=org.id, hypervisor_id=hv.id))
        session.commit()

    resp = client.get("/firstboot-linux/aabbccddeeff")

    assert resp.status_code == 200, resp.text
    assert f"ServerActive={PROXY_SITE}" in resp.text
    assert PROXY_CENTRAL not in resp.text, \
        "le collecteur de l'organisation ne doit plus apparaître nulle part"


# ── La fiche hyperviseur ─────────────────────────────────────────────────────

def test_le_collecteur_sedite_sur_la_fiche(client, admin_headers):
    hv = client.post("/hypervisors", headers=admin_headers, json={
        "name": "Nova", "url": "https://pve.test:8006",
        "token_id": "osiris@pve!osiris", "token_secret": "s3cret",
        "zabbix_server": PROXY_SITE}).json()
    assert hv["zabbix_server"] == PROXY_SITE

    resp = client.patch(f"/hypervisors/{hv['id']}", headers=admin_headers,
                        json={"zabbix_server": ""})

    assert resp.status_code == 200, resp.text
    assert resp.json()["zabbix_server"] == "", "on doit pouvoir revenir à l'organisation"


def test_une_fiche_sans_collecteur_reste_valide(client, admin_headers):
    """Le champ est optionnel : ne pas le renseigner ne doit rien exiger de plus."""
    resp = client.post("/hypervisors", headers=admin_headers, json={
        "name": "FIT", "url": "https://fit.test:8006",
        "token_id": "osiris@pve!osiris", "token_secret": "s3cret"})

    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["zabbix_server"] == ""
