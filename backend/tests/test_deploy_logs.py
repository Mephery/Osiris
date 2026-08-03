# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Persistance du journal de déploiement.

Le besoin d'origine : la fenêtre WinPE disparaît avec le reboot de la machine, et
le journal doit rester consultable après coup. Il vivait dans un dict en mémoire,
donc un redémarrage du backend — ou un simple F5, le front ne lisant que le flux
WebSocket — le faisait disparaître.
"""
import main
from models import DeployLogLine, Machine, engine
from sqlmodel import Session, select

MAC = "aabbccddeeff"


def _post(client, mac, msg):
    return client.post(f"/machines/{mac}/log", params={"msg": msg})


def test_une_ligne_postee_est_ecrite_en_base(client, test_machine):
    assert _post(client, MAC, "DISM 42%").status_code == 200

    with Session(engine) as session:
        lignes = session.exec(select(DeployLogLine).where(DeployLogLine.mac == MAC)).all()
    assert len(lignes) == 1
    assert "DISM 42%" in lignes[0].line
    assert lignes[0].run == 1


def test_le_journal_survit_a_un_redemarrage_du_backend(client, test_machine, admin_headers):
    """La régression visée : rien ne doit dépendre d'un état en mémoire."""
    for msg in ("Montage SMB", "Application du WIM", "Redemarrage"):
        _post(client, MAC, msg)

    # Ce que verrait un backend fraîchement redémarré : plus que la base.
    with Session(engine) as session:
        lignes = session.exec(
            select(DeployLogLine).where(DeployLogLine.mac == MAC).order_by(DeployLogLine.id)
        ).all()
    assert [l.line.split("] ", 1)[1] for l in lignes] == [
        "Montage SMB", "Application du WIM", "Redemarrage",
    ]

    logs = client.get(f"/machines/{MAC}/logs", headers=admin_headers).json()["logs"]
    assert len(logs) == 3


def test_chaque_ligne_est_horodatee(client, test_machine, admin_headers):
    _post(client, MAC, "Demarrage")
    logs = client.get(f"/machines/{MAC}/logs", headers=admin_headers).json()["logs"]
    assert logs[0].startswith("[") and "] Demarrage" in logs[0]


def test_les_logs_exigent_une_authentification(client, test_machine):
    _post(client, MAC, "secret")
    assert client.get(f"/machines/{MAC}/logs").status_code == 401
    assert client.get(f"/machines/{MAC}/logs.txt").status_code == 401


# ── Redéploiement : le journal précédent n'est plus détruit ────────────────────

def test_un_redeploiement_ouvre_un_nouveau_journal(client, test_machine, admin_headers):
    _post(client, MAC, "tentative 1")
    client.post(f"/machines/{MAC}/status", params={"status": "pending"})
    _post(client, MAC, "tentative 2")

    # Le terminal live ne montre que le déploiement courant.
    logs = client.get(f"/machines/{MAC}/logs", headers=admin_headers).json()["logs"]
    assert len(logs) == 1
    assert "tentative 2" in logs[0]

    # ... mais la tentative précédente est toujours en base.
    with Session(engine) as session:
        runs = {l.run for l in session.exec(
            select(DeployLogLine).where(DeployLogLine.mac == MAC)).all()}
    assert runs == {1, 2}


def test_redeploy_now_ouvre_aussi_un_nouveau_journal(client, test_machine, admin_headers):
    """`redeploy-now` est LE bouton de redéploiement de l'UI, et il ne passe pas par
    `report_machine_status` : il doit incrémenter le compteur lui aussi."""
    _post(client, MAC, "tentative 1")
    client.post(f"/machines/{MAC}/redeploy-now", headers=admin_headers)
    _post(client, MAC, "tentative 2")

    logs = client.get(f"/machines/{MAC}/logs", headers=admin_headers).json()["logs"]
    assert len(logs) == 1 and "tentative 2" in logs[0]


def test_le_redeploiement_en_lot_ouvre_un_nouveau_journal(client, test_machine, admin_headers):
    _post(client, MAC, "tentative 1")
    rep = client.post("/machines/batch-status",
                      json={"macs": [MAC], "status": "pending"}, headers=admin_headers)
    assert rep.status_code == 200
    _post(client, MAC, "tentative 2")

    logs = client.get(f"/machines/{MAC}/logs", headers=admin_headers).json()["logs"]
    assert len(logs) == 1 and "tentative 2" in logs[0]


def test_le_txt_contient_toutes_les_tentatives(client, test_machine, admin_headers):
    """C'est justement après un échec qu'on relance : comparer les deux tentatives
    est le plus utile, donc le téléchargement sert l'historique entier."""
    _post(client, MAC, "tentative 1")
    client.post(f"/machines/{MAC}/status", params={"status": "pending"})
    _post(client, MAC, "tentative 2")

    corps = client.get(f"/machines/{MAC}/logs.txt", headers=admin_headers).text
    assert "tentative 1" in corps and "tentative 2" in corps
    assert "Déploiement n°1" in corps and "Déploiement n°2" in corps


# ── Téléchargement .txt ────────────────────────────────────────────────────────

def test_le_txt_se_telecharge_avec_un_nom_parlant(client, test_machine, admin_headers):
    _post(client, MAC, "Montage SMB")
    rep = client.get(f"/machines/{MAC}/logs.txt", headers=admin_headers)

    assert rep.status_code == 200
    assert rep.headers["content-type"].startswith("text/plain")
    disposition = rep.headers["content-disposition"]
    assert "attachment" in disposition
    assert "PC-TEST" in disposition and MAC in disposition
    assert "PC-TEST" in rep.text and "Montage SMB" in rep.text


def test_le_txt_d_une_machine_sans_log_reste_valide(client, test_machine, admin_headers):
    rep = client.get(f"/machines/{MAC}/logs.txt", headers=admin_headers)
    assert rep.status_code == 200
    assert "aucune ligne" in rep.text


# ── Garde-fou volumétrie ───────────────────────────────────────────────────────

def test_un_journal_emballe_est_tronque(client, test_machine, monkeypatch):
    """Une machine coincée en boucle PXE ne doit pas pouvoir gonfler la base."""
    monkeypatch.setattr(main, "DEPLOY_LOG_MAX_LINES", 3)
    for i in range(10):
        _post(client, MAC, f"ligne {i}")

    with Session(engine) as session:
        lignes = session.exec(
            select(DeployLogLine).where(DeployLogLine.mac == MAC).order_by(DeployLogLine.id)
        ).all()

    assert len(lignes) == 4          # le plafond, plus la ligne qui l'annonce
    assert "tronque" in lignes[-1].line


# ── Libération du dongle ───────────────────────────────────────────────────────

def test_la_liberation_du_dongle_est_journalisee(client, test_machine, admin_headers):
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == MAC)).one()
        machine.deploy_mac = "001122334455"
        session.add(machine)
        session.commit()

    client.post(f"/machines/{MAC}/status", params={"status": "deployed"})

    logs = client.get(f"/machines/{MAC}/logs", headers=admin_headers).json()["logs"]
    assert any("001122334455" in l and "libere" in l for l in logs)
