"""Tests d'intégration : CRUD machines, permissions, webhook new-machine."""


# ── Permissions ────────────────────────────────────────────────────────────────

def test_lister_machines_sans_auth(client):
    r = client.get("/machines")
    assert r.status_code == 401


def test_lister_machines_technician(client, technician_headers):
    r = client.get("/machines", headers=technician_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_creer_organisation_requiert_admin(client, technician_headers):
    r = client.post("/organizations", json={"name": "Acme", "slug": "acme"},
                    headers=technician_headers)
    assert r.status_code == 403


def test_creer_organisation_en_tant_quadmin(client, admin_headers):
    r = client.post("/organizations", json={"name": "Acme Corp", "slug": "acme-corp"},
                    headers=admin_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Acme Corp"
    assert body["slug"] == "acme-corp"


def test_supprimer_utilisateur_requiert_admin(client, technician_headers, technician_user):
    r = client.delete(f"/users/{technician_user.id}", headers=technician_headers)
    assert r.status_code == 403


# ── Création de machine ────────────────────────────────────────────────────────

def test_creer_machine(client, admin_headers):
    payload = {"mac": "aa:bb:cc:dd:ee:ff", "hostname": "PC-TEST",
                "client": "Acme", "os": "windows"}
    r = client.post("/machines", json=payload, headers=admin_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["mac"] == "aabbccddeeff"
    assert body["hostname"] == "PC-TEST"


def test_creer_machine_mac_invalide(client, admin_headers):
    payload = {"mac": "pas-une-mac", "hostname": "PC-TEST", "client": "X", "os": "windows"}
    r = client.post("/machines", json=payload, headers=admin_headers)
    assert r.status_code == 400


def test_creer_machine_mac_dupliquee(client, admin_headers):
    payload = {"mac": "11:22:33:44:55:66", "hostname": "PC-A", "client": "X", "os": "windows"}
    r1 = client.post("/machines", json=payload, headers=admin_headers)
    assert r1.status_code == 201
    r2 = client.post("/machines", json=payload, headers=admin_headers)
    assert r2.status_code == 400


def test_creer_machine_technician_autorise(client, technician_headers):
    """Les techniciens peuvent enregistrer des machines (pas uniquement les admins)."""
    payload = {"mac": "aa:11:22:33:44:55", "hostname": "PC-TECH", "client": "Y", "os": "ubuntu"}
    r = client.post("/machines", json=payload, headers=technician_headers)
    assert r.status_code == 201


# ── Webhook new-machine ────────────────────────────────────────────────────────

def test_webhook_new_machine_cree_machine(client, admin_headers):
    r = client.post("/webhooks/new-machine",
                    json={"mac": "de:ad:be:ef:00:01", "hostname": "PC-GLPI", "client": "Client X"},
                    headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert body["mac"] == "deadbeef0001"


def test_webhook_new_machine_idempotent(client, admin_headers):
    """Appeler deux fois avec la même MAC ne crée pas de doublon."""
    payload = {"mac": "de:ad:be:ef:00:02", "hostname": "PC-GLPI2", "client": "Client X"}
    r1 = client.post("/webhooks/new-machine", json=payload, headers=admin_headers)
    assert r1.json()["created"] is True

    r2 = client.post("/webhooks/new-machine", json=payload, headers=admin_headers)
    assert r2.status_code == 200
    assert r2.json()["created"] is False
    assert r2.json()["mac"] == "deadbeef0002"
