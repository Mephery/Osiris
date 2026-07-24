# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""MAC du PC vs MAC de l'adaptateur USB-Ethernet (`deploy_mac`).

Un même dongle sert à déployer plusieurs machines à la suite. Sa MAC ne peut donc
pas être l'identité du poste : elle est stockée à part dans `deploy_mac`, facultative,
et OUBLIÉE dès la fin du déploiement pour être réutilisable ailleurs.
"""
import main
from sqlmodel import Session, select

from models import engine, Machine, OsImage, Profile

DONGLE = "00e04c680636"
PC_MAC = "94105a2d9384"


def _windows_image():
    with Session(engine) as s:
        s.add(OsImage(name="Win11", version="25H2", os="windows",
                      iso_url="file:///tmp/x.iso", status="ready"))
        s.commit()


def _machine(mac=PC_MAC, deploy_mac=None, hostname="PC-DONGLE", status="pending"):
    with Session(engine) as s:
        p = Profile(name="P-Win", os="windows", locale="fr-FR")
        s.add(p)
        s.commit()
        s.refresh(p)
        m = Machine(mac=mac, deploy_mac=deploy_mac, hostname=hostname, client="Acme",
                    os="windows", status=status, profile_id=p.id)
        s.add(m)
        s.commit()
        s.refresh(m)
        return m


def _reload(mac):
    with Session(engine) as s:
        return s.exec(select(Machine).where(Machine.mac == mac)).first()


# ── Résolution en WinPE ───────────────────────────────────────────────────────

def test_winpe_auto_resout_par_mac_du_dongle(client, monkeypatch):
    """La MAC vue sur le réseau est celle du dongle : elle doit résoudre la machine
    via `deploy_mac`, et le script généré porter la MAC CANONIQUE du PC."""
    _windows_image()
    _machine(mac=PC_MAC, deploy_mac=DONGLE)
    monkeypatch.setattr(main, "_ip_to_mac", lambda ip: DONGLE)

    r = client.get("/winpe-auto")
    assert r.status_code == 200
    assert "PC-DONGLE" in r.text
    # C'est la MAC du PC qui est gravée dans le script, pas celle du dongle :
    # tous les callbacks /machines/{mac}/... doivent viser l'identité permanente.
    assert f"set MAC={PC_MAC}" in r.text
    assert DONGLE not in r.text


def test_winpe_auto_sans_dongle_resout_par_mac_du_pc(client, monkeypatch):
    """Rétrocompatibilité : sans adaptateur, la MAC vue EST celle du PC."""
    _windows_image()
    _machine(mac=PC_MAC, deploy_mac=None)
    monkeypatch.setattr(main, "_ip_to_mac", lambda ip: PC_MAC)

    r = client.get("/winpe-auto")
    assert r.status_code == 200
    assert f"set MAC={PC_MAC}" in r.text


def test_winpe_auto_dongle_non_declare_refuse(client, monkeypatch):
    """Un dongle inconnu ne doit pas déclencher un déploiement générique."""
    _windows_image()
    _machine(mac=PC_MAC, deploy_mac=None)
    monkeypatch.setattr(main, "_ip_to_mac", lambda ip: DONGLE)

    r = client.get("/winpe-auto")
    assert r.status_code == 404


# ── Oubli automatique en fin de déploiement ───────────────────────────────────

def test_dongle_oublie_quand_la_machine_est_deployee(client):
    """Le dongle est libéré au passage en 'deployed' : réutilisable immédiatement."""
    m = _machine(mac=PC_MAC, deploy_mac=DONGLE)
    assert m.deploy_mac == DONGLE

    r = client.post(f"/machines/{PC_MAC}/status", params={"status": "deployed"})
    assert r.status_code == 200

    assert _reload(PC_MAC).deploy_mac is None


def test_dongle_conserve_tant_que_le_deploiement_est_en_cours(client):
    """Tant que la machine n'est pas déployée, l'adaptateur lui reste affecté."""
    _machine(mac=PC_MAC, deploy_mac=DONGLE)

    r = client.post(f"/machines/{PC_MAC}/status", params={"status": "deploying"})
    assert r.status_code == 200

    assert _reload(PC_MAC).deploy_mac == DONGLE


# ── Création ──────────────────────────────────────────────────────────────────

def test_creation_sans_dongle_laisse_le_champ_null(client, admin_headers):
    """Le champ est FACULTATIF : une machine sans adaptateur a deploy_mac = None."""
    r = client.post("/machines", headers=admin_headers, json={
        "mac": PC_MAC, "hostname": "PC-A", "client": "Acme", "os": "windows"})
    assert r.status_code == 201
    assert r.json()["deploy_mac"] is None


def test_creation_chaine_vide_vaut_pas_de_dongle(client, admin_headers):
    """Une chaîne vide envoyée par un formulaire ne doit pas devenir une MAC bidon."""
    r = client.post("/machines", headers=admin_headers, json={
        "mac": PC_MAC, "hostname": "PC-A", "client": "Acme", "os": "windows",
        "deploy_mac": ""})
    assert r.status_code == 201
    assert r.json()["deploy_mac"] is None


def test_plusieurs_machines_sans_dongle_coexistent(client, admin_headers):
    """L'index unique ne doit pas interdire plusieurs machines sans adaptateur."""
    for i, mac in enumerate(("94105a2d9384", "94105a2d93e7")):
        r = client.post("/machines", headers=admin_headers, json={
            "mac": mac, "hostname": f"PC-{i}", "client": "Acme", "os": "windows"})
        assert r.status_code == 201


def test_creation_dongle_deja_affecte_refusee(client, admin_headers):
    """Deux machines ne peuvent pas revendiquer le même dongle : l'identification
    en WinPE deviendrait ambiguë."""
    _machine(mac=PC_MAC, deploy_mac=DONGLE)

    r = client.post("/machines", headers=admin_headers, json={
        "mac": "94105a2d93e7", "hostname": "PC-B", "client": "Acme",
        "os": "windows", "deploy_mac": DONGLE})
    assert r.status_code == 409
    assert "libérer" in r.json()["detail"]


def test_creation_dongle_identique_au_pc_refusee(client, admin_headers):
    """Saisir la même MAC dans les deux champs est une erreur de saisie."""
    r = client.post("/machines", headers=admin_headers, json={
        "mac": PC_MAC, "hostname": "PC-A", "client": "Acme", "os": "windows",
        "deploy_mac": PC_MAC})
    assert r.status_code == 400


# ── Édition ───────────────────────────────────────────────────────────────────

def test_patch_chaine_vide_libere_le_dongle(client, admin_headers):
    """Libération manuelle depuis l'UI, sans attendre la fin d'un déploiement."""
    _machine(mac=PC_MAC, deploy_mac=DONGLE)

    r = client.patch(f"/machines/{PC_MAC}", headers=admin_headers,
                     json={"deploy_mac": ""})
    assert r.status_code == 200
    assert r.json()["deploy_mac"] is None
    assert _reload(PC_MAC).deploy_mac is None


def test_patch_affecte_un_dongle(client, admin_headers):
    _machine(mac=PC_MAC, deploy_mac=None)

    r = client.patch(f"/machines/{PC_MAC}", headers=admin_headers,
                     json={"deploy_mac": "00:E0:4C:68:06:36"})
    assert r.status_code == 200
    assert r.json()["deploy_mac"] == DONGLE      # normalisée comme la MAC du PC


def test_patch_dongle_deja_affecte_refuse(client, admin_headers):
    _machine(mac=PC_MAC, deploy_mac=DONGLE, hostname="PC-A")
    _machine(mac="94105a2d93e7", deploy_mac=None, hostname="PC-B")

    r = client.patch("/machines/94105a2d93e7", headers=admin_headers,
                     json={"deploy_mac": DONGLE})
    assert r.status_code == 409


def test_patch_sans_deploy_mac_ne_touche_pas_au_dongle(client, admin_headers):
    """Modifier un autre champ ne doit pas libérer l'adaptateur par effet de bord."""
    _machine(mac=PC_MAC, deploy_mac=DONGLE)

    r = client.patch(f"/machines/{PC_MAC}", headers=admin_headers,
                     json={"hostname": "PC-RENOMME"})
    assert r.status_code == 200
    assert _reload(PC_MAC).deploy_mac == DONGLE
