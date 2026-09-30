# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Client minimal de l'API Zabbix + enregistrement d'un hôte déployé.

Dès qu'une machine passe « deployed », OSIRIS crée (ou met à jour) son hôte dans
Zabbix par l'API : bon groupe, modèle selon l'OS, et surtout le **bon proxy** —
la supervision de septembre était muette parce qu'un hôte pointait sur le proxy
d'un autre site (`proxy.get` résout ici le proxy à partir du `zabbix_server` de
l'organisation / de l'hyperviseur). L'opération est **idempotente** (create ou
update) et ne **supprime jamais** rien : le jeton `s_osiris` n'a volontairement
pas `host.delete`.

Volontairement en `urllib` (stdlib) : `requests` n'est pas une dépendance de
production déclarée, et un client synchrone suffit — l'appel part d'une tâche de
fond, après la réponse HTTP à la machine.
"""
import json
import logging
import os
import urllib.request
from typing import Optional

_log = logging.getLogger("osiris.zabbix")

# URL COMPLÈTE du point d'entrée JSON-RPC, ex. https://<zabbix>/api_jsonrpc.php
ZABBIX_API_URL   = os.environ.get("ZABBIX_API_URL", "")
ZABBIX_API_TOKEN = os.environ.get("ZABBIX_API_TOKEN", "")
# Groupe d'hôtes où atterrissent les machines déployées. Un sous-groupe par
# organisation est créé dessous (« <groupe>/<org> ») quand l'orga est connue.
ZABBIX_DEPLOYED_GROUP   = os.environ.get("ZABBIX_DEPLOYED_GROUP", "")
ZABBIX_TEMPLATE_LINUX   = os.environ.get("ZABBIX_TEMPLATE_LINUX", "Linux by Zabbix agent active")
ZABBIX_TEMPLATE_WINDOWS = os.environ.get("ZABBIX_TEMPLATE_WINDOWS", "Windows by Zabbix agent active")

_HTTP_TIMEOUT = 15


def zabbix_configure() -> bool:
    """Vrai seulement si tout le nécessaire est renseigné : sinon on saute
    l'enregistrement en silence (fonctionnalité inactive tant que non configurée)."""
    return bool(ZABBIX_API_URL and ZABBIX_API_TOKEN and ZABBIX_DEPLOYED_GROUP)


def _call(method: str, params, auth: bool = True):
    """Un appel JSON-RPC à l'API Zabbix, authentifié par le jeton `s_osiris`."""
    payload = json.dumps({"jsonrpc": "2.0", "method": method,
                          "params": params, "id": 1}).encode()
    headers = {"Content-Type": "application/json-rpc"}
    if auth:
        # Zabbix ≥ 5.4 : jeton d'API porté par l'en-tête, pas par un champ `auth`.
        headers["Authorization"] = f"Bearer {ZABBIX_API_TOKEN}"
    req = urllib.request.Request(ZABBIX_API_URL, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
        body = json.loads(r.read())
    if "error" in body:
        err = body["error"]
        raise RuntimeError(f"Zabbix {method} : {err.get('data') or err.get('message')}")
    return body["result"]


def _api_major() -> int:
    """Version majeure de l'API (le champ du proxy a changé en 7.0)."""
    try:
        return int(str(_call("apiinfo.version", [], auth=False)).split(".")[0])
    except Exception:
        return 6   # défaut prudent : nomenclature 6.x


def _proxy_fields(collector: str) -> dict:
    """Champs à poser sur l'hôte pour le rattacher au proxy `collector`.

    `{}` si le proxy est introuvable : mieux vaut un hôte supervisé par le serveur
    (et un log) qu'un échec de création. Le nom cherché est celui du proxy dans
    Zabbix — c'est ce que doit contenir `zabbix_server` côté orga/hyperviseur.
    """
    if not collector:
        return {}
    # `zabbix_server` peut être un NOM de proxy ou une IP (le champ sert d'abord de
    # `Server=` à l'agent, où l'on met souvent l'IP). On tente donc les deux : le
    # nom/host du proxy, et l'IP/DNS de son interface (proxy passif).
    proxies = _call("proxy.get", {"output": ["proxyid", "host", "name"],
                                  "selectInterface": ["ip", "dns"]})
    def _candidates(p):
        itf = p.get("interface") or {}
        return (p.get("host"), p.get("name"), itf.get("ip"), itf.get("dns"))
    match = next((p for p in proxies if collector in _candidates(p)), None)
    if not match:
        _log.warning("Zabbix : proxy %r introuvable, hôte supervisé par le serveur", collector)
        return {}
    pid = match["proxyid"]
    if _api_major() >= 7:
        return {"monitored_by": 1, "proxyid": pid}   # 1 = proxy
    return {"proxy_hostid": pid}


def _get_or_create_group(name: str) -> str:
    found = _call("hostgroup.get", {"output": ["groupid"], "filter": {"name": [name]}})
    if found:
        return found[0]["groupid"]
    return _call("hostgroup.create", {"name": name})["groupids"][0]


def _template_id(name: str) -> Optional[str]:
    """id du modèle par son nom technique OU visible. None si absent (le nom du
    modèle Linux change selon l'âge de l'installation Zabbix)."""
    for key in ("host", "name"):
        found = _call("template.get", {"output": ["templateid"], "filter": {key: [name]}})
        if found:
            return found[0]["templateid"]
    _log.warning("Zabbix : modèle %r introuvable, hôte créé sans modèle", name)
    return None


def _host_id(hostname: str) -> Optional[str]:
    found = _call("host.get", {"output": ["hostid"], "filter": {"host": [hostname]}})
    return found[0]["hostid"] if found else None


def register_deployed_host(*, hostname: str, os_type: str, collector: str,
                           org_name: str = "", hw_model: str = "", ip: str = "") -> str:
    """Crée ou met à jour l'hôte d'une machine déployée dans Zabbix.

    Renvoie « created » / « updated » / « skip:… ». Ne lève pas : toute erreur est
    journalisée et avalée — un raté de supervision ne doit jamais casser un
    déploiement (l'agent finira de toute façon par se signaler).
    """
    if not zabbix_configure():
        return "skip:non-configure"
    try:
        group_name = f"{ZABBIX_DEPLOYED_GROUP}/{org_name}" if org_name else ZABBIX_DEPLOYED_GROUP
        groupid = _get_or_create_group(group_name)
        tmpl_name = ZABBIX_TEMPLATE_WINDOWS if os_type == "windows" else ZABBIX_TEMPLATE_LINUX
        templateid = _template_id(tmpl_name)

        common = {
            "groups": [{"groupid": groupid}],
            "inventory_mode": 0,   # manuel : c'est OSIRIS qui renseigne
            "inventory": {"name": hostname, "os": os_type,
                          "hardware": hw_model,
                          "notes": f"Déployé par OSIRIS{(' — ' + org_name) if org_name else ''}"},
        }
        common.update(_proxy_fields(collector))
        if templateid:
            common["templates"] = [{"templateid": templateid}]

        existing = _host_id(hostname)
        if existing:
            _call("host.update", {"hostid": existing, **common})
            return "updated"

        _call("host.create", {
            "host": hostname,
            "interfaces": [{
                "type": 1, "main": 1,           # 1 = agent
                "useip": 1 if ip else 0,
                "ip": ip, "dns": hostname if not ip else "",
                "port": "10050",
            }],
            **common,
        })
        return "created"
    except Exception as exc:      # noqa: BLE001 — on avale volontairement
        _log.warning("Zabbix : enregistrement de %r échoué : %s", hostname, exc)
        return f"error:{exc}"
