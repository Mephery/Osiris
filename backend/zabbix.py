# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Client minimal de l'API Zabbix + enregistrement d'un hôte déployé.

Dès qu'une machine passe « deployed », OSIRIS crée (ou met à jour) son hôte dans
Zabbix par l'API : bon groupe, modèle selon l'OS, et surtout le **bon proxy** —
la supervision de septembre était muette parce qu'un hôte pointait sur le proxy
d'un autre site (`proxy.get` résout ici le proxy à partir du `zabbix_server` de
l'organisation / de l'hyperviseur). L'opération est **idempotente** (create ou
update). Il ne désactive ou ne supprime un hôte QUE sur demande de l'opérateur, à
la suppression de la machine (cf. `retirer_hote`) — et `host.delete` n'est permis
que si le rôle du jeton `s_osiris` l'autorise.

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
# Sous-groupe « <groupe>/<org> » par organisation ? Défaut NON (groupe plat) :
# créer un sous-groupe exige `hostgroup.create`, que le jeton étroit `s_osiris`
# n'a pas — et le groupe plat, lui, préexiste et suffit. À activer seulement si
# le jeton a le droit de créer des groupes.
ZABBIX_SUBGROUP_BY_ORG  = os.environ.get("ZABBIX_SUBGROUP_BY_ORG", "").strip().lower() in ("1", "true", "yes", "oui")


def _parse_proxy_map(raw: str) -> dict:
    """« ip=nom,ip2=nom2 » → {ip: nom}. Fait le pont entre le `zabbix_server`
    (une IP, dont l'agent a besoin en `Server=`) et le NOM du proxy attendu par
    l'API — l'API n'expose pas toujours l'adresse d'un proxy actif, donc on ne
    peut pas déduire le nom de l'IP autrement."""
    out = {}
    for pair in raw.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


ZABBIX_PROXY_MAP        = _parse_proxy_map(os.environ.get("ZABBIX_PROXY_MAP", ""))
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
    # Valeurs acceptées pour retrouver le proxy : le `collector` tel quel (utile si
    # c'est déjà un nom) ET son nom traduit par le mapping IP→nom. Le schéma du
    # proxy a changé en 7.0/8.0 : `host` + interface (proxy passif) est devenu
    # `name` + `address`, et `proxy_hostid` est devenu `proxyid` (+ `monitored_by`).
    accept = {collector, ZABBIX_PROXY_MAP.get(collector, collector)}
    major = _api_major()
    if major >= 7:
        proxies = _call("proxy.get", {"output": ["proxyid", "name", "address"]})
        match = next((p for p in proxies if accept & {p.get("name"), p.get("address")}), None)
        if match:
            return {"monitored_by": 1, "proxyid": match["proxyid"]}   # 1 = proxy
    else:
        proxies = _call("proxy.get", {"output": ["proxyid", "host"],
                                      "selectInterface": ["ip", "dns"]})
        def _cand(p):
            itf = p.get("interface") or {}
            return {p.get("host"), itf.get("ip"), itf.get("dns")}
        match = next((p for p in proxies if accept & _cand(p)), None)
        if match:
            return {"proxy_hostid": match["proxyid"]}
    _log.warning("Zabbix : proxy %r introuvable, hôte supervisé par le serveur", collector)
    return {}


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
        group_name = (f"{ZABBIX_DEPLOYED_GROUP}/{org_name}"
                      if ZABBIX_SUBGROUP_BY_ORG and org_name else ZABBIX_DEPLOYED_GROUP)
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
        proxy = _proxy_fields(collector)
        if collector and not proxy:
            # Un collecteur est déclaré mais on ne sait pas le rattacher à un proxy :
            # créer l'hôte « supervisé par le serveur » le rendrait MUET (l'agent
            # actif parle à son proxy, qui ne connaîtrait pas cet hôte). On préfère
            # ne rien créer et laisser une trace — il suffit d'ajouter la
            # correspondance dans ZABBIX_PROXY_MAP pour le site concerné.
            _log.warning("Zabbix : proxy introuvable pour %r → hôte %s NON créé "
                         "(ajouter %r à ZABBIX_PROXY_MAP)", collector, hostname, collector)
            return "skip:proxy-inconnu"
        common.update(proxy)

        existing = _host_id(hostname)
        if existing:
            # On ne re-passe PAS `templates` en mise à jour : re-lier un modèle déjà
            # présent déclenche un « System error » (constaté en Zabbix 8.0), et le
            # modèle a de toute façon été posé à la création (ou par l'agent).
            _call("host.update", {"hostid": existing, **common})
            return "updated"

        create = {
            "host": hostname,
            "interfaces": [{
                "type": 1, "main": 1,           # 1 = agent
                "useip": 1 if ip else 0,
                "ip": ip, "dns": hostname if not ip else "",
                "port": "10050",
            }],
            **common,
        }
        if templateid:
            create["templates"] = [{"templateid": templateid}]
        _call("host.create", create)
        return "created"
    except Exception as exc:      # noqa: BLE001 — on avale volontairement
        _log.warning("Zabbix : enregistrement de %r échoué : %s", hostname, exc)
        return f"error:{exc}"


# ── Sort de l'hôte quand la machine quitte OSIRIS ─────────────────────────────
# Sans ça, chaque VM supprimée laissait un hôte orphelin qui alertait « agent
# injoignable » jusqu'à ce que quelqu'un le retire à la main. Le choix revient à
# l'opérateur : DÉSACTIVER garde l'historique d'un vrai serveur, SUPPRIMER
# nettoie une VM de test.
#
# Garde-fou : un NOM ne prouve pas une identité (même leçon que les numéros de VM
# recyclés par Proxmox). OSIRIS n'agit que sur un hôte rangé dans SON groupe : un
# vrai serveur du même nom, ajouté à la main ailleurs, reste intact.

ACTIONS_RETRAIT = ("rien", "desactiver", "supprimer")


def _dans_groupe_osiris(noms: list) -> bool:
    g = ZABBIX_DEPLOYED_GROUP
    return any(n == g or n.startswith(g + "/") for n in noms)


def _hote_detaille(hostname: str) -> Optional[dict]:
    """L'hôte et ses groupes. `selectHostGroups` depuis Zabbix 6.2, `selectGroups`
    avant : on essaie le récent, puis l'ancien."""
    for cle, champ in (("selectHostGroups", "hostgroups"), ("selectGroups", "groups")):
        try:
            found = _call("host.get", {"output": ["hostid", "host", "status"],
                                       "filter": {"host": [hostname]}, cle: ["name"]})
        except RuntimeError:
            continue
        if not found:
            return None
        h = found[0]
        return {"hostid": h["hostid"], "actif": str(h.get("status")) == "0",
                "groupes": [g["name"] for g in h.get(champ) or []]}
    raise RuntimeError("Zabbix host.get : groupes de l'hôte illisibles")


def etat_hote(hostname: str) -> dict:
    """Ce que la fenêtre de suppression doit montrer. Ne lève pas : un Zabbix
    injoignable ne doit pas empêcher d'ouvrir la fenêtre."""
    if not zabbix_configure():
        return {"configure": False}
    try:
        h = _hote_detaille(hostname)
    except Exception as exc:      # noqa: BLE001
        return {"configure": True, "erreur": str(exc)}
    if not h:
        return {"configure": True, "existe": False}
    return {"configure": True, "existe": True, "actif": h["actif"],
            "gere": _dans_groupe_osiris(h["groupes"]), "groupes": h["groupes"]}


def retirer_hote(hostname: str, action: str) -> str:
    """Applique le choix de l'opérateur. Renvoie « inchange », « absent »,
    « non-gere », « desactive » ou « supprime ». LÈVE en cas d'échec : l'appelant
    doit pouvoir le dire à l'opérateur, qui croirait sinon l'hôte retiré."""
    if action not in ACTIONS_RETRAIT:
        raise ValueError(f"action Zabbix inconnue : {action}")
    if action == "rien" or not zabbix_configure():
        return "inchange"
    h = _hote_detaille(hostname)
    if not h:
        return "absent"
    if not _dans_groupe_osiris(h["groupes"]):
        _log.warning("Zabbix : %r hors du groupe %r (%s) — laissé intact",
                     hostname, ZABBIX_DEPLOYED_GROUP, ", ".join(h["groupes"]))
        return "non-gere"
    try:
        if action == "desactiver":
            _call("host.update", {"hostid": h["hostid"], "status": 1})   # 1 = désactivé
            return "desactive"
        _call("host.delete", [h["hostid"]])
        return "supprime"
    except RuntimeError as exc:
        if "No permissions" in str(exc):
            raise RuntimeError(
                f"le rôle Zabbix du jeton OSIRIS n'autorise pas "
                f"{'host.delete' if action == 'supprimer' else 'host.update'}") from exc
        raise
