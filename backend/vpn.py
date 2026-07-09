# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""
Gestion des tunnels VPN site-à-site par organisation.

Chaque VpnTunnel correspond à un client distant (ex: Midi2i) : un fichier
.ovpn permanent (un par client, tous actifs simultanément — contrairement à
l'ancien script PowerShell qui basculait un seul VPN à la fois), une route
vers le réseau du client, et un DNS interne à interroger pour son domaine AD.

L'application des changements sur le système (fichiers sous /etc, services
systemd) passe par deux scripts root minimalistes (deploy/osiris-vpn-*.sh)
invoqués via sudo — voir deploy/README.md pour l'installation.
"""
import ipaddress
import os
import re
import subprocess
import tempfile
from typing import Optional

from sqlmodel import Session, select

from crypto import decrypt
from models import DomainConfig, VpnTunnel

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")

VPN_APPLY_SCRIPT = "/usr/local/sbin/osiris-vpn-apply.sh"
VPN_DISABLE_SCRIPT = "/usr/local/sbin/osiris-vpn-disable.sh"
DNSMASQ_SNIPPET_HEADER = "# Généré automatiquement par OSIRIS (backend/vpn.py) — ne pas éditer à la main\n"


def make_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:31]
    if not SLUG_RE.match(slug):
        raise ValueError(f"Impossible de dériver un identifiant système valide depuis '{text}'")
    return slug


def render_ovpn_config(raw_config: str, route_cidr: str, slug: str) -> str:
    """Injecte une directive `route` pour que le tunnel reste utilisable même
    si le serveur ne pousse pas sa route, et fait pointer `auth-user-pass`
    (quand il est présent sans argument, donc interactif par défaut) vers le
    fichier d'identifiants géré par OSIRIS pour ce tunnel."""
    lines = raw_config.rstrip("\n").split("\n")
    lines = [
        f"auth-user-pass /etc/openvpn/client/{slug}.auth" if line.strip() == "auth-user-pass" else line
        for line in lines
    ]
    content = "\n".join(lines)
    if route_cidr:
        network = ipaddress.ip_network(route_cidr, strict=False)
        route_line = f"route {network.network_address} {network.netmask}"
        if route_line not in content:
            content += f"\n{route_line}"
    return content + "\n"


def render_auth_file(username: str, password: str) -> str:
    """Fichier `auth-user-pass` : login sur la première ligne, mot de passe
    (éventuellement suffixé d'un code TOTP) sur la seconde."""
    return f"{username}\n{password}\n"


def render_dnsmasq_snippet(session: Session) -> str:
    """Construit le snippet dnsmasq qui route les domaines AD des clients vers
    leur DNS interne via le bon tunnel, et pousse les routes classless (option
    121) aux machines déployées pour qu'elles atteignent ces réseaux via OSIRIS."""
    tunnels = session.exec(select(VpnTunnel).where(VpnTunnel.enabled == True)).all()  # noqa: E712
    lines = [DNSMASQ_SNIPPET_HEADER]
    routes = []
    for tunnel in tunnels:
        if tunnel.remote_dns:
            domain_configs = session.exec(
                select(DomainConfig).where(DomainConfig.organization_id == tunnel.organization_id)
            ).all()
            dns_ips = [ip.strip() for ip in tunnel.remote_dns.split(",") if ip.strip()]
            for dc in domain_configs:
                for dns_ip in dns_ips:
                    lines.append(f"server=/{dc.domain}/{dns_ip}")
        if tunnel.route_cidr:
            routes.append(tunnel.route_cidr)
    if routes:
        server_ip = os.environ.get("OSIRIS_IP", "10.0.0.1")
        pairs = ",".join(f"{cidr},{server_ip}" for cidr in routes)
        lines.append(f"dhcp-option=121,{pairs}")
    return "\n".join(lines) + "\n"


def _write_temp(content: str, mode: int = 0o600) -> str:
    fd, path = tempfile.mkstemp(prefix="osiris-vpn-", dir="/tmp")
    try:
        os.chmod(path, mode)
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except BaseException:
        os.unlink(path)
        raise
    return path


def apply_tunnel(session: Session, tunnel: VpnTunnel, totp_code: Optional[str] = None) -> None:
    """Écrit la conf OpenVPN + le fichier d'identifiants + le snippet dnsmasq
    à jour, puis (re)démarre le tunnel et recharge dnsmasq. Le code TOTP,
    quand fourni, n'est utilisé que pour construire ce fichier éphémère : il
    n'est jamais persisté (ni en base, ni dans les logs d'audit).
    Lève RuntimeError si le script root échoue, ValueError si les paramètres
    fournis sont insuffisants (slug invalide, TOTP requis mais absent)."""
    if not SLUG_RE.match(tunnel.slug):
        raise ValueError("Slug de tunnel invalide")
    if tunnel.requires_totp and not totp_code:
        raise ValueError("Ce tunnel nécessite un code TOTP à chaque application")

    ovpn_content = render_ovpn_config(decrypt(tunnel.ovpn_config), tunnel.route_cidr, tunnel.slug)
    dnsmasq_content = render_dnsmasq_snippet(session)

    ovpn_path = _write_temp(ovpn_content)
    dnsmasq_path = _write_temp(dnsmasq_content, mode=0o644)
    auth_path = None
    if tunnel.vpn_username:
        password = decrypt(tunnel.vpn_password)
        if tunnel.requires_totp:
            password += totp_code
        auth_path = _write_temp(render_auth_file(tunnel.vpn_username, password))
    try:
        cmd = ["sudo", "-n", VPN_APPLY_SCRIPT, tunnel.slug, ovpn_path, dnsmasq_path, auth_path or "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    finally:
        os.unlink(ovpn_path)
        os.unlink(dnsmasq_path)
        if auth_path:
            os.unlink(auth_path)
    if result.returncode != 0:
        raise RuntimeError(f"Échec de l'application du tunnel : {result.stderr.strip()[:500]}")


def disable_tunnel(session: Session, tunnel: VpnTunnel) -> None:
    """Arrête + désactive le service systemd du tunnel et régénère le snippet
    dnsmasq (sans ce tunnel). À appeler avant de supprimer un VpnTunnel."""
    if not SLUG_RE.match(tunnel.slug):
        raise ValueError("Slug de tunnel invalide")
    dnsmasq_content = render_dnsmasq_snippet(session)
    dnsmasq_path = _write_temp(dnsmasq_content, mode=0o644)
    try:
        result = subprocess.run(
            ["sudo", "-n", VPN_DISABLE_SCRIPT, tunnel.slug, dnsmasq_path],
            capture_output=True, text=True, timeout=20,
        )
    finally:
        os.unlink(dnsmasq_path)
    if result.returncode != 0:
        raise RuntimeError(f"Échec de la désactivation du tunnel : {result.stderr.strip()[:500]}")


def tunnel_status(slug: str) -> str:
    """Interroge systemd pour l'état réel du tunnel ('active', 'inactive', 'failed'...)."""
    if not SLUG_RE.match(slug):
        return "unknown"
    result = subprocess.run(
        ["systemctl", "is-active", f"openvpn-client@{slug}"],
        capture_output=True, text=True, timeout=5,
    )
    return result.stdout.strip() or "unknown"
