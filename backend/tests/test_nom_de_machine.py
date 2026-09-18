# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le nom de machine, et les autres champs libres, finissaient tels quels dans
des scripts exécutés en root.

`_log "OSIRIS First Boot - {{ machine.hostname }}"` : avec le nom
`srv$(commande)`, la commande s'exécutait sur la machine déployée. N'importe quel
compte capable de créer une fiche — un technicien, une clé d'API, un import
CSV — obtenait ainsi un accès root. Même chose avec le client dans le script
WinPE (un `&` y enchaîne une commande) et avec l'OU dans une chaîne PowerShell
(un retour à la ligne en sort).

Deux verrous : le nom est refusé à TOUTES les entrées, et jamais rendu dans un
script s'il est invalide — pour une fiche déjà en base ou arrivée par un chemin
oublié.
"""
import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

import main
from models import Hypervisor, Machine, engine

ATTAQUE = "srv$(touch /tmp/osiris-injection)"


def _creer(http, headers, **kw):
    corps = {"mac": "aa:bb:cc:dd:ee:01", "hostname": "PC-01", "client": "Acme", "os": "ubuntu"}
    corps.update(kw)
    return http.post("/machines", json=corps, headers=headers)


# ── Aux entrées ───────────────────────────────────────────────────────────────

def test_un_technicien_ne_peut_plus_injecter_de_commande(client, technician_headers):
    r = _creer(client, technician_headers, hostname=ATTAQUE)
    assert r.status_code == 400
    with Session(engine) as s:
        assert not s.exec(select(Machine)).all()


@pytest.mark.parametrize("nom", ["srv;reboot", "a b", "-debut", "fin-", "é-accent", "a" * 64, "12345", ""])
def test_les_noms_invalides_sont_refuses(client, admin_headers, nom):
    assert _creer(client, admin_headers, hostname=nom).status_code == 400


def test_windows_limite_le_nom_a_15_caracteres(client, admin_headers):
    """Au-delà, Windows tronque en silence et l'AD enregistre un autre nom."""
    assert _creer(client, admin_headers, hostname="PC-COMPTA-ETAGE2", os="windows").status_code == 400
    assert _creer(client, admin_headers, hostname="PC-COMPTA-ETAGE2", os="ubuntu").status_code == 201


def test_passer_en_windows_revalide_le_nom(client, admin_headers):
    _creer(client, admin_headers, hostname="serveur-de-fichiers-01")
    r = client.patch("/machines/aabbccddee01", json={"os": "windows"}, headers=admin_headers)
    assert r.status_code == 400


def test_la_modification_d_une_fiche_est_controlee(client, admin_headers):
    _creer(client, admin_headers)
    r = client.patch("/machines/aabbccddee01", json={"hostname": ATTAQUE}, headers=admin_headers)
    assert r.status_code == 400


def test_le_webhook_est_controle(client, admin_headers):
    r = client.post("/webhooks/new-machine", headers=admin_headers,
                    json={"mac": "aa:bb:cc:dd:ee:02", "hostname": ATTAQUE})
    assert r.status_code == 400


def test_l_import_csv_rejette_la_ligne_sans_creer_la_machine(client, admin_headers):
    csv = f"mac,hostname,client,os\naa:bb:cc:dd:ee:03,{ATTAQUE},Acme,ubuntu\naa:bb:cc:dd:ee:04,PC-OK,Acme,ubuntu\n"
    r = client.post("/machines/import", content=csv.encode(), headers=admin_headers)
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        noms = [m.hostname for m in s.exec(select(Machine)).all()]
    assert noms == ["PC-OK"]


def test_la_creation_de_vm_est_controlee_avant_l_hyperviseur(client, admin_headers, monkeypatch):
    with Session(engine) as s:
        h = Hypervisor(name="pve", url="https://pve.test:8006", token_id="t", token_secret="", tls_verify=False)
        s.add(h)
        s.commit()
        hv_id = h.id

    async def interdit(*a, **kw):
        raise AssertionError("l'hyperviseur ne devait pas être appelé")
    monkeypatch.setattr(main, "_proxmox_get", interdit)
    r = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": ATTAQUE, "client": "Acme", "os": "debian", "node": "pve",
        "storage": "s", "bridge": "b", "boot_mode": "template", "template_id": 1})
    assert r.status_code == 400


@pytest.mark.parametrize("champ", ["client", "ou"])
def test_un_retour_a_la_ligne_est_refuse_dans_les_champs_libres(client, admin_headers, champ):
    """Il suffit à sortir de la chaîne PowerShell @' … '@ qui porte l'OU."""
    assert _creer(client, admin_headers, **{champ: "Acme\n'@\nRemove-Item C:\\ -Recurse"}).status_code == 400


# ── Au rendu : jamais un nom non contrôlé dans un script ──────────────────────

def test_une_fiche_invalide_deja_en_base_n_est_jamais_rendue(tmp_path):
    """L'attaque prouvée le 18/09, rejouée : le script ne sort plus."""
    with pytest.raises(HTTPException):
        main._firstboot_linux_content(
            hostname=ATTAQUE, mac="aabbccddeeff", ou="",
            profile_ctx={"os": "ubuntu", "default_user": "u", "join_domain": False,
                         "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0},
            linux_apps=[], zabbix=None, osiris_url="http://o")


# /winpe-script exige en plus une image Windows en base : il répond 503 avant
# d'atteindre le rendu ici, mais porte le même verrou, au même endroit.
@pytest.mark.parametrize("route", ["/firstboot-windows/{}", "/firstboot-linux/{}"])
def test_les_routes_de_script_refusent_une_fiche_invalide(client, route):
    with Session(engine) as s:
        # Écrite directement en base : c'est le cas d'une fiche antérieure au contrôle
        s.add(Machine(mac="aabbccddee09", hostname=ATTAQUE, client="c",
                      os="windows" if "windows" in route else "ubuntu",
                      status="pending"))
        s.commit()
    r = client.get(route.format("aabbccddee09"))
    assert r.status_code == 400
    assert "invalide" in r.text


def test_le_client_est_neutralise_dans_le_script_winpe():
    rendu = main._cmd_texte("Acme & del /q C:\\* | x > y")
    assert not set("&|<>") & set(rendu)
    assert rendu.startswith("Acme")
