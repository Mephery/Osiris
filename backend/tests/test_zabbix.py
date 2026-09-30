# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Création de l'hôte d'une machine déployée dans Zabbix (zabbix.py).

L'API Zabbix est entièrement mockée (`_call`) : on teste la logique de
réconciliation, pas le réseau. Points sensibles couverts : idempotence
(create vs update), le BON proxy (la cause de la coupure de septembre), la
différence de champ proxy entre Zabbix 6.x et 7.0, et le fait qu'un raté
(modèle/proxy absent, erreur d'API) ne bloque jamais.
"""
import pytest

import zabbix


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(zabbix, "ZABBIX_API_URL", "http://zbx/api_jsonrpc.php")
    monkeypatch.setattr(zabbix, "ZABBIX_API_TOKEN", "tok")
    monkeypatch.setattr(zabbix, "ZABBIX_DEPLOYED_GROUP", "OSIRIS-deployes")
    monkeypatch.setattr(zabbix, "ZABBIX_TEMPLATE_LINUX", "Linux by Zabbix agent active")
    monkeypatch.setattr(zabbix, "ZABBIX_TEMPLATE_WINDOWS", "Windows by Zabbix agent active")


def _mock(monkeypatch, *, host_exists=False, template=True, proxy=True, version="6.0.0"):
    calls = []

    def fake(method, params, auth=True):
        calls.append((method, params))
        if method == "apiinfo.version":
            return version
        if method == "hostgroup.get":
            return []                       # force la création → id déterministe
        if method == "hostgroup.create":
            return {"groupids": ["10"]}
        if method == "template.get":
            return [{"templateid": "20"}] if template else []
        if method == "proxy.get":
            return ([{"proxyid": "5", "host": "fit-zbprx01", "name": "fit-zbprx01",
                      "interface": {"ip": "192.0.2.130", "dns": ""}}] if proxy else [])
        if method == "host.get":
            return [{"hostid": "100"}] if host_exists else []
        if method in ("host.create", "host.update"):
            return {"hostids": ["100"]}
        raise AssertionError(f"méthode inattendue : {method}")

    monkeypatch.setattr(zabbix, "_call", fake)
    return calls


def _params(calls, method):
    return next(p for (m, p) in calls if m == method)


def _methods(calls):
    return [m for (m, _) in calls]


# ── Garde-fous ─────────────────────────────────────────────────────────────────

def test_non_configure_ne_fait_rien(monkeypatch):
    monkeypatch.setattr(zabbix, "ZABBIX_API_URL", "")
    # pas de _call mocké : s'il était appelé, ce serait une vraie requête → échec net
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="windows", collector="") == "skip:non-configure"


def test_une_erreur_d_api_est_avalee(monkeypatch):
    def boom(method, params, auth=True):
        if method == "host.get":
            raise RuntimeError("Zabbix host.get : boom")
        return [] if method.endswith(".get") else {"groupids": ["10"], "hostids": ["1"]}
    monkeypatch.setattr(zabbix, "_call", boom)
    out = zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="p")
    assert out.startswith("error:")     # pas d'exception qui remonte


# ── Idempotence ────────────────────────────────────────────────────────────────

def test_cree_l_hote_absent(monkeypatch):
    calls = _mock(monkeypatch, host_exists=False)
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="fit-zbprx01") == "created"
    assert "host.create" in _methods(calls)
    assert "host.update" not in _methods(calls)


def test_met_a_jour_l_hote_existant(monkeypatch):
    calls = _mock(monkeypatch, host_exists=True)
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="fit-zbprx01") == "updated"
    assert "host.update" in _methods(calls)
    assert "host.create" not in _methods(calls)
    assert _params(calls, "host.update")["hostid"] == "100"


# ── Proxy (le bug de septembre) ────────────────────────────────────────────────

def test_proxy_pose_par_nom_en_6(monkeypatch):
    calls = _mock(monkeypatch, version="6.0.25")
    zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="fit-zbprx01")
    assert _params(calls, "host.create")["proxy_hostid"] == "5"


def test_proxy_resolu_aussi_par_ip(monkeypatch):
    """`zabbix_server` contient souvent l'IP, pas le nom du proxy."""
    calls = _mock(monkeypatch, version="6.0.25")
    zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="192.0.2.130")
    assert _params(calls, "host.create")["proxy_hostid"] == "5"


def test_proxy_champ_7_0(monkeypatch):
    calls = _mock(monkeypatch, version="7.0.0")
    zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="fit-zbprx01")
    p = _params(calls, "host.create")
    assert p["proxyid"] == "5" and p["monitored_by"] == 1
    assert "proxy_hostid" not in p


def test_proxy_introuvable_ne_bloque_pas(monkeypatch):
    calls = _mock(monkeypatch, proxy=False)
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="inconnu") == "created"
    p = _params(calls, "host.create")
    assert "proxy_hostid" not in p and "proxyid" not in p


# ── Modèle & groupe ────────────────────────────────────────────────────────────

def test_modele_absent_ne_bloque_pas(monkeypatch):
    calls = _mock(monkeypatch, template=False)
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="fit-zbprx01") == "created"
    assert "templates" not in _params(calls, "host.create")


def test_modele_windows_selon_l_os(monkeypatch):
    calls = _mock(monkeypatch)
    zabbix.register_deployed_host(hostname="PC1", os_type="windows", collector="fit-zbprx01")
    # le filtre template.get doit porter le nom Windows
    tmpl_calls = [p for (m, p) in calls if m == "template.get"]
    noms = [v for p in tmpl_calls for v in p["filter"].values()]
    assert any("Windows" in str(n) for n in noms)


def test_sous_groupe_par_organisation(monkeypatch):
    calls = _mock(monkeypatch)
    zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="fit-zbprx01", org_name="Acme")
    noms = [v for (m, p) in calls if m == "hostgroup.get"
            for v in p["filter"]["name"]]
    assert "OSIRIS-deployes/Acme" in noms
