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
    monkeypatch.setattr(zabbix, "ZABBIX_SUBGROUP_BY_ORG", False)   # défaut : groupe plat
    monkeypatch.setattr(zabbix, "ZABBIX_PROXY_MAP", {})


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
            return ([{"proxyid": "5", "host": "zbx-proxy01", "name": "zbx-proxy01",
                      "address": "192.0.2.130",
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
        if method == "apiinfo.version":
            return "6.0.0"
        if method == "proxy.get":       # proxy résolu, on dépasse l'étape proxy
            return [{"proxyid": "5", "host": "p"}]
        if method == "host.get":        # ... et ça casse ici
            raise RuntimeError("Zabbix host.get : boom")
        return [] if method.endswith(".get") else {"groupids": ["10"], "hostids": ["1"]}
    monkeypatch.setattr(zabbix, "_call", boom)
    out = zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="p")
    assert out.startswith("error:")     # pas d'exception qui remonte


# ── Idempotence ────────────────────────────────────────────────────────────────

def test_cree_l_hote_absent(monkeypatch):
    calls = _mock(monkeypatch, host_exists=False)
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="zbx-proxy01") == "created"
    assert "host.create" in _methods(calls)
    assert "host.update" not in _methods(calls)


def test_met_a_jour_l_hote_existant(monkeypatch):
    calls = _mock(monkeypatch, host_exists=True)
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="zbx-proxy01") == "updated"
    assert "host.update" in _methods(calls)
    assert "host.create" not in _methods(calls)
    assert _params(calls, "host.update")["hostid"] == "100"


def test_update_ne_touche_pas_aux_modeles(monkeypatch):
    """Re-lier un modèle déjà présent plante en Zabbix 8.0 : l'update l'évite."""
    calls = _mock(monkeypatch, host_exists=True)
    zabbix.register_deployed_host(hostname="PC1", os_type="windows", collector="zbx-proxy01")
    assert "templates" not in _params(calls, "host.update")


def test_creation_pose_bien_le_modele(monkeypatch):
    calls = _mock(monkeypatch, host_exists=False, template=True)
    zabbix.register_deployed_host(hostname="PC1", os_type="windows", collector="zbx-proxy01")
    assert _params(calls, "host.create")["templates"] == [{"templateid": "20"}]


# ── Proxy (le bug de septembre) ────────────────────────────────────────────────

def test_proxy_pose_par_nom_en_6(monkeypatch):
    calls = _mock(monkeypatch, version="6.0.25")
    zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="zbx-proxy01")
    assert _params(calls, "host.create")["proxy_hostid"] == "5"


def test_proxy_resolu_aussi_par_ip(monkeypatch):
    """`zabbix_server` contient souvent l'IP, pas le nom du proxy."""
    calls = _mock(monkeypatch, version="6.0.25")
    zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="192.0.2.130")
    assert _params(calls, "host.create")["proxy_hostid"] == "5"


def test_proxy_champ_7_0(monkeypatch):
    calls = _mock(monkeypatch, version="7.0.0")
    zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="zbx-proxy01")
    p = _params(calls, "host.create")
    assert p["proxyid"] == "5" and p["monitored_by"] == 1
    assert "proxy_hostid" not in p


def test_proxy_resolu_par_mapping_ip_nom(monkeypatch):
    """Le mapping IP→nom fait le pont quand `zabbix_server` est une IP que l'API
    ne rattache à aucun proxy (proxy actif : pas d'adresse exposée)."""
    monkeypatch.setattr(zabbix, "ZABBIX_PROXY_MAP", {"203.0.113.99": "zbx-proxy01"})
    calls = _mock(monkeypatch, version="8.0.0")
    # le mock ne connaît le proxy que par son NOM (pas cette IP)
    zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="203.0.113.99")
    assert _params(calls, "host.create")["proxyid"] == "5"


def test_proxy_8_0_beta_par_adresse(monkeypatch):
    """Zabbix 8.0 : version « 8.0.0beta2 » bien lue, proxy résolu par `address`."""
    calls = _mock(monkeypatch, version="8.0.0beta2")
    zabbix.register_deployed_host(hostname="PC1", os_type="linux", collector="192.0.2.130")
    p = _params(calls, "host.create")
    assert p["proxyid"] == "5" and p["monitored_by"] == 1


def test_proxy_introuvable_saute_pour_eviter_un_hote_muet(monkeypatch):
    """Collecteur déclaré mais proxy non résolu → on NE crée PAS l'hôte : le
    créer « supervisé par le serveur » le rendrait muet."""
    calls = _mock(monkeypatch, proxy=False)
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="inconnu") == "skip:proxy-inconnu"
    assert "host.create" not in _methods(calls)


# ── Modèle & groupe ────────────────────────────────────────────────────────────

def test_modele_absent_ne_bloque_pas(monkeypatch):
    calls = _mock(monkeypatch, template=False)
    assert zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="zbx-proxy01") == "created"
    assert "templates" not in _params(calls, "host.create")


def test_modele_windows_selon_l_os(monkeypatch):
    calls = _mock(monkeypatch)
    zabbix.register_deployed_host(hostname="PC1", os_type="windows", collector="zbx-proxy01")
    # le filtre template.get doit porter le nom Windows
    tmpl_calls = [p for (m, p) in calls if m == "template.get"]
    noms = [v for p in tmpl_calls for v in p["filter"].values()]
    assert any("Windows" in str(n) for n in noms)


def test_groupe_plat_par_defaut(monkeypatch):
    """Par défaut : groupe plat (le jeton étroit ne peut pas créer de sous-groupe)."""
    calls = _mock(monkeypatch)
    zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="zbx-proxy01", org_name="Acme")
    noms = [v for (m, p) in calls if m == "hostgroup.get" for v in p["filter"]["name"]]
    assert "OSIRIS-deployes" in noms
    assert "OSIRIS-deployes/Acme" not in noms


def test_sous_groupe_par_organisation_si_active(monkeypatch):
    monkeypatch.setattr(zabbix, "ZABBIX_SUBGROUP_BY_ORG", True)
    calls = _mock(monkeypatch)
    zabbix.register_deployed_host(
        hostname="PC1", os_type="linux", collector="zbx-proxy01", org_name="Acme")
    noms = [v for (m, p) in calls if m == "hostgroup.get" for v in p["filter"]["name"]]
    assert "OSIRIS-deployes/Acme" in noms
