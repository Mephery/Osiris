# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
from typing import Optional
from urllib.parse import quote
from xml.sax.saxutils import escape
from passlib.hash import sha512_crypt
from fastapi import HTTPException, FastAPI, Request, Response, Depends, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlmodel import SQLModel, Session, select, func

from arq import create_pool
from arq.connections import RedisSettings
from jinja2 import Environment, FileSystemLoader

import pyotp
import qrcode
from models import ApiKey, Application, AuditLog, DeployLogLine, DeploymentEvent, DriverPack, DomainConfig, Hypervisor, Machine, Organization, OsImage, Profile, User, VpnTunnel, engine, init_db, normalize_model
import vpn
import vsphere
from auth import (
    hash_password, verify_password, create_token,
    get_current_user, require_admin
)
from crypto import encrypt, decrypt


# ── Démarrage ──────────────────────────────────────────────────────────────────

arq_pool = None

# Routes que les machines en cours de deploiement appellent en HTTP CLAIR : elles
# n'ont ni navigateur, ni magasin de certificats, et leur client (iPXE, curl de
# WinPE, amorcage Linux) ne suit pas les redirections. Elles doivent donc etre
# proxifiees telles quelles par le frontal.
_ROUTES_MACHINES = (
    "/boot",
    "/bootstrap/linux",
    "/firstboot-linux/000000000000",
    "/firstboot-windows/000000000000",
    "/winpe-script/000000000000",
    "/preseed/000000000000",
)


async def _verifier_routes_machines() -> None:
    """Alerte si le frontal ne sert pas en clair les routes du deploiement.

    Le 2026-08-05, `/firstboot-linux/*` manquait au matcher du Caddyfile *installe*
    — le depot avait ete mis a jour 15 jours plus tot, pas la machine. Caddy
    repondait 308 vers HTTPS, l'amorcage des VM Linux echouait en boucle, et rien
    nulle part ne signalait la derive.

    On ne teste PAS le code exact (404 sur une MAC bidon est normal et prouve que la
    route arrive bien jusqu'a l'application) : seule une **redirection** trahit une
    route absente du frontal.
    """
    await asyncio.sleep(10)   # laisser le frontal et l'application se poser
    suspectes = []
    try:
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for route in _ROUTES_MACHINES:
                try:
                    async with session.get(f"{OSIRIS_BASE_URL}{route}",
                                           allow_redirects=False) as rep:
                        if 300 <= rep.status < 400:
                            suspectes.append(f"{route} -> HTTP {rep.status}")
                except Exception as exc:
                    suspectes.append(f"{route} -> injoignable ({type(exc).__name__})")
    except Exception:
        return   # une verification de confort ne doit jamais gener le demarrage

    if suspectes:
        logging.getLogger("osiris.routes").warning(
            "Routes de deploiement NON servies en clair par le frontal : %s. "
            "Les machines ne suivent pas les redirections : PXE, WinPE et l'amorcage "
            "Linux echoueront. Verifier le matcher du Caddyfile installe "
            "(/etc/caddy/Caddyfile) face a celui du depot.",
            " ; ".join(suspectes),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global arq_pool
    init_db()
    _seed_admin()
    _seed_default_profiles()
    _seed_apps()
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    arq_pool = await create_pool(RedisSettings.from_dsn(redis_url))
    verif = asyncio.create_task(_verifier_routes_machines())
    yield
    verif.cancel()
    await arq_pool.aclose()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    lifespan=lifespan,
    title="OSIRIS API",
    description=(
        "API REST du serveur de déploiement PXE OSIRIS.\n\n"
        "Authentification : `Authorization: Bearer <jwt>` ou `Authorization: Bearer osiris_sk_...` (clé API personnelle).\n\n"
        "Documentation complète : voir le README du projet."
    ),
    version="1.0.0",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Config ─────────────────────────────────────────────────────────────────────

OSIRIS_BASE_URL = os.environ.get("OSIRIS_BASE_URL", "http://10.0.0.1:8000")
OSIRIS_IP       = os.environ.get("OSIRIS_IP", "10.0.0.1")
SSH_PUBKEY      = os.environ.get("OSIRIS_SSH_PUBKEY", "").strip()
ADMIN_EMAIL     = os.environ.get("ADMIN_EMAIL", "admin@osiris.local")
ADMIN_PASSWORD  = os.environ.get("ADMIN_PASSWORD", "changeme")
WIN_SHARE_PATH  = os.environ.get("WIN_SHARE_PATH", "/srv/data/windows")

# Mapping IANA → noms Windows (subset courant MSP France)
_LINUX_TO_WIN_TZ: dict[str, str] = {
    "Europe/Paris":      "Romance Standard Time",
    "Europe/Brussels":   "Romance Standard Time",
    "Europe/Luxembourg": "Romance Standard Time",
    "Europe/London":     "GMT Standard Time",
    "Europe/Berlin":     "W. Europe Standard Time",
    "Europe/Madrid":     "Romance Standard Time",
    "Europe/Rome":       "W. Europe Standard Time",
    "Europe/Amsterdam":  "W. Europe Standard Time",
    "Europe/Zurich":     "W. Europe Standard Time",
    "America/New_York":  "Eastern Standard Time",
    "America/Chicago":   "Central Standard Time",
    "America/Denver":    "Mountain Standard Time",
    "America/Los_Angeles": "Pacific Standard Time",
    "UTC": "UTC",
}

def _win_timezone(tz: str) -> str:
    return _LINUX_TO_WIN_TZ.get(tz, tz)  # retourne la valeur telle quelle si déjà au format Windows

allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pilotes réseau WinPE : servis à wimboot au démarrage PXE (voir _winpe_chain_lines).
# Monté AVANT /static, sinon le mount le plus générique capterait le chemin.
WINPE_DRIVERS_PATH = os.environ.get("WINPE_DRIVERS_PATH", "/srv/data/windows/winpe-drivers")
if os.path.isdir(WINPE_DRIVERS_PATH):
    app.mount("/static/winpe-drivers",
              StaticFiles(directory=WINPE_DRIVERS_PATH), name="winpe-drivers")

app.mount("/static", StaticFiles(directory="static"), name="static")

class ConnectionManager:
    """Garde la liste des connexions WebSocket ouvertes et diffuse les messages."""
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        message = json.dumps(data)
        for ws in self.active.copy():
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect(ws)

manager = ConnectionManager()

_deploy_progress: dict[str, int] = {}

# Au-dela de cette limite, on cesse de persister les lignes d'un MEME deploiement.
# Une machine coincee dans une boucle PXE peut poster sans fin ; passe quelques
# milliers de lignes le journal n'a de toute facon plus aucune valeur de diagnostic,
# et rien ne doit pouvoir faire grossir la base indefiniment.
DEPLOY_LOG_MAX_LINES = 5000

# ── Mode capture : mac → {wim_name, registered_at, status} ───────────────────
_capture_jobs: dict[str, dict] = {}


jinja_env = Environment(
    loader=FileSystemLoader("templates"),
    trim_blocks=True,    # supprime le saut de ligne après un bloc {% %}
    lstrip_blocks=True,  # supprime les espaces avant un bloc {% %} en début de ligne
    autoescape=False,    # on gère l'échappement XML manuellement
)

def _bash_squote(s: str) -> str:
    """Entoure une valeur de guillemets simples bash, en echappant les apostrophes internes.
    Sur pour tout caractere : dollar, guillemets, backtick, backslash, espaces, etc."""
    return "'" + str(s).replace("'", "'\\''") + "'"

jinja_env.filters["bash_squote"] = _bash_squote


# ── Validation MAC ─────────────────────────────────────────────────────────────

MAC_REGEX = re.compile(r'^[0-9a-f]{12}$')

def validate_mac(raw: str) -> str:
    clean = raw.lower().replace(":", "").replace("-", "")
    if not MAC_REGEX.match(clean):
        raise HTTPException(status_code=400, detail=f"Format MAC invalide : {raw!r}")
    return clean


def _validate_mac_prefix(raw: str) -> str:
    """Normalise un préfixe MAC d'organisation : 4 octets hexa, sans séparateur.

    Vide = fonctionnalité désactivée. On refuse un préfixe multicast (bit de poids
    faible du 1er octet à 1) : ce serait une adresse source invalide, la machine
    perdrait le réseau.
    """
    clean = (raw or "").strip().lower().replace(":", "").replace("-", "")
    if not clean:
        return ""
    if len(clean) != 8 or not all(c in "0123456789abcdef" for c in clean):
        raise HTTPException(
            status_code=400,
            detail=f"Préfixe MAC invalide : {raw!r} — attendu 4 octets hexa (ex: 02aabbcc)",
        )
    if int(clean[:2], 16) & 0x01:
        raise HTTPException(
            status_code=400,
            detail=f"Préfixe MAC {raw!r} multicast — inutilisable comme adresse source",
        )
    return clean


# Les 3 derniers chiffres du hostname portent le numéro de poste.
HOSTNAME_SEQ_REGEX = re.compile(r"(\d{3})$")


def mac_from_hostname(hostname: str, mac_prefix: str) -> str:
    """MAC imposée par la convention du client, ou '' si elle ne s'applique pas.

    Les 3 derniers chiffres du hostname sont RECOPIÉS TELS QUELS dans les deux
    derniers octets, zéro-padés sur 4 — ce n'est pas une conversion décimale vers
    hexa : le poste 095 donne '0095' -> ...:00:95 et le poste 100 donne '0100' ->
    ...:01:00 (et non ...:00:64). Les chiffres 0-9 étant tous des caractères hexa
    valides, la correspondance est bijective de 000 à 999 et ne peut pas déborder.
    """
    if not mac_prefix:
        return ""
    match = HOSTNAME_SEQ_REGEX.search((hostname or "").strip())
    if not match:
        return ""
    return f"{mac_prefix}{match.group(1).rjust(4, '0')}"


# ── Schémas de requête ─────────────────────────────────────────────────────────

class WebhookNewMachine(SQLModel):
    """Payload simplifié pour créer une machine depuis un outil externe (GLPI, Jira, RMM...)."""
    mac: str
    hostname: str = ""
    client: str = ""
    os: str = "windows"
    organization_id: Optional[int] = None
    profile_id: Optional[int] = None

class MachinePatch(SQLModel):
    hostname: Optional[str] = None
    client: Optional[str] = None
    os: Optional[str] = None
    ou: Optional[str] = None
    # MAC de l'adaptateur USB-Ethernet. Chaîne vide = libérer explicitement le dongle
    # (le PATCH ignore les None, ils signifient "champ non fourni").
    deploy_mac: Optional[str] = None
    organization_id: Optional[int] = None
    profile_id: Optional[int] = None
    driver_pack_id: Optional[int] = None
    notes: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    supervised: Optional[bool] = None
    ip_cidr: Optional[str] = None
    gateway: Optional[str] = None
    dns_servers: Optional[str] = None

class ProfileCreate(SQLModel):
    name: str
    os: str
    locale: str = "fr_FR.UTF-8"
    keyboard: str = "fr"
    timezone: str = "Europe/Paris"
    default_user: str = "osiris"
    extra_packages: str = ""
    join_domain: bool = True
    domain: str = "entreprise.local"
    domain_join_user: str = ""
    domain_join_password: str = ""
    win_image: str = ""
    win_index: int = 1
    enable_bitlocker: bool = True
    bitlocker_pin: bool = False
    network_drives: str = ""
    printers: str = ""
    post_script: str = ""
    tv_suffix: str = ""
    app_ids: str = ""
    machine_type: str = "workstation"
    ssh_authorized_keys: str = ""
    vm_vcpus: int = 2
    vm_ram_mb: int = 2048
    vm_disk_gb: int = 20
    vm_data_disk_gb: int = 0
    set_root_password: bool = False

class ProfilePatch(SQLModel):
    name: Optional[str] = None
    locale: Optional[str] = None
    keyboard: Optional[str] = None
    timezone: Optional[str] = None
    default_user: Optional[str] = None
    extra_packages: Optional[str] = None
    join_domain: Optional[bool] = None
    domain: Optional[str] = None
    domain_join_user: Optional[str] = None
    domain_join_password: Optional[str] = None
    win_image: Optional[str] = None
    win_index: Optional[int] = None
    enable_bitlocker: Optional[bool] = None
    bitlocker_pin: Optional[bool] = None
    network_drives: Optional[str] = None
    printers: Optional[str] = None
    post_script: Optional[str] = None
    tv_suffix: Optional[str] = None
    app_ids: Optional[str] = None
    machine_type: Optional[str] = None
    ssh_authorized_keys: Optional[str] = None
    vm_vcpus: Optional[int] = None
    vm_ram_mb: Optional[int] = None
    vm_disk_gb: Optional[int] = None
    vm_data_disk_gb: Optional[int] = None
    set_root_password: Optional[bool] = None

class LoginRequest(SQLModel):
    email: str
    password: str

class PasswordChange(SQLModel):
    current_password: str
    new_password: str

class OrgCreate(SQLModel):
    name: str
    slug: str

class UserCreate(SQLModel):
    email: str
    password: str
    role: str = "technician"


# ── Admin par défaut au démarrage ──────────────────────────────────────────────

def _seed_admin():
    """Crée un admin par défaut si aucun utilisateur n'existe en base."""
    with Session(engine) as session:
        if session.exec(select(User)).first():
            return
        admin = User(
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            role="admin",
        )
        session.add(admin)
        session.commit()
        print(f"[OSIRIS] Admin créé : {ADMIN_EMAIL} — changez le mot de passe !")


def _seed_default_profiles():
    """Crée un profil par défaut pour chaque OS si aucun profil n'existe."""
    with Session(engine) as session:
        if session.exec(select(Profile)).first():
            return
        session.add(Profile(name="Ubuntu — par défaut",  os="ubuntu"))
        session.add(Profile(name="Debian — par défaut",  os="debian"))
        session.add(Profile(name="Windows — par défaut", os="windows", locale="fr-FR"))
        session.add(Profile(name="Ubuntu Server — par défaut", os="ubuntu", machine_type="server", enable_bitlocker=False))
        session.add(Profile(name="Debian Server — par défaut", os="debian", machine_type="server", enable_bitlocker=False))
        # Windows Server : jamais BitLocker par défaut, pas de jonction domaine auto.
        # win_index=2 = édition "Standard (Desktop Experience)" typique des ISO Server.
        # win_image reste vide : l'admin le renseigne avec le wim_name de son image Server
        # (ex. "server2022.wim") une fois l'ISO Server ajoutée dans OSIRIS.
        session.add(Profile(name="Windows Server — par défaut", os="windows", locale="fr-FR",
                            machine_type="server", enable_bitlocker=False,
                            join_domain=False, win_index=2))
        session.commit()
        print("[OSIRIS] Profils par défaut créés")


_SEED_APPS = [
    {"name": "Google Chrome",        "winget_id": "Google.Chrome",                        "apt_package": "google-chrome-stable", "category": "browser",  "icon": "🌐"},
    {"name": "Mozilla Firefox",      "winget_id": "Mozilla.Firefox",                      "apt_package": "firefox",              "category": "browser",  "icon": "🦊"},
    {"name": "7-Zip",                "winget_id": "7zip.7zip",                            "apt_package": "p7zip-full",           "category": "tools",    "icon": "🗜️"},
    {"name": "VLC",                  "winget_id": "VideoLAN.VLC",                         "apt_package": "vlc",                  "category": "media",    "icon": "🎬"},
    {"name": "LibreOffice",          "winget_id": "TheDocumentFoundation.LibreOffice",    "apt_package": "libreoffice",          "category": "office",   "icon": "📄"},
    {"name": "Notepad++",            "winget_id": "Notepad++.Notepad++",                  "apt_package": "",                     "category": "dev",      "icon": "📝"},
    {"name": "PDF24",                "winget_id": "geeksoftwareGmbH.PDF24Creator",        "apt_package": "",                     "category": "tools",    "icon": "📑"},
    {"name": "Zoom",                 "winget_id": "Zoom.Zoom",                            "apt_package": "",                     "category": "comm",     "icon": "📹"},
    {"name": "Bitwarden",            "winget_id": "Bitwarden.Bitwarden",                  "apt_package": "bitwarden",            "category": "security", "icon": "🔐"},
    {"name": "Paint.NET",            "winget_id": "dotPDN.PaintDotNet",                   "apt_package": "",                     "category": "tools",    "icon": "🎨"},
    {"name": "Teams",                "winget_id": "Microsoft.Teams",                      "apt_package": "",                     "category": "comm",     "icon": "💬"},
    {"name": "Signal",               "winget_id": "OpenWhisperSystems.Signal",            "apt_package": "signal-desktop",       "category": "comm",     "icon": "🔒"},
    {"name": "TeamViewer",           "winget_id": "TeamViewer.TeamViewer",                "apt_package": "",                     "category": "remote",   "icon": "👥"},
    {"name": "Microsoft 365 (abonnement)", "winget_id": "Microsoft.Office",              "apt_package": "",                     "category": "office",   "icon": "🏢"},
    {"name": "Office 2021 (volume)", "winget_id": "",                                     "apt_package": "",                     "category": "office",   "icon": "🏢", "install_type": "exe", "installer_file": "setup_office2021.exe", "installer_config_file": "conf_office2021.xml", "install_args": "/configure conf_office2021.xml", "detect_name": "Office LTSC"},
    {"name": "Adobe Acrobat Reader", "winget_id": "Adobe.Acrobat.Reader.64-bit",          "apt_package": "",                     "category": "tools",    "icon": "📋"},
    {"name": "Audacity",             "winget_id": "Audacity.Audacity",                    "apt_package": "audacity",             "category": "media",    "icon": "🎙️"},
    {"name": "VS Code",              "winget_id": "Microsoft.VisualStudioCode",           "apt_package": "",                     "category": "dev",      "icon": "💻"},
    {"name": "Java OpenJDK 21",      "winget_id": "Eclipse.Temurin.21",                   "apt_package": "openjdk-21-jre",       "category": "tools",    "icon": "☕"},
    {"name": ".NET Runtime 8",       "winget_id": "Microsoft.DotNet.DesktopRuntime.8",    "apt_package": "",                     "category": "tools",    "icon": "⚡"},
    {"name": "Nextcloud Client",     "winget_id": "Nextcloud.Nextcloud",                  "apt_package": "nextcloud-desktop",    "category": "office",   "icon": "☁️"},
    {"name": "NetExplorer",          "winget_id": "NetExplorer.NetExplorer",              "apt_package": "",                     "category": "office",   "icon": "📁"},
    {"name": "Citrix Workspace",     "winget_id": "Citrix.Workspace",                     "apt_package": "",                     "category": "remote",   "icon": "🖥️"},
    {"name": "OpenVPN",              "winget_id": "OpenVPNTechnologies.OpenVPN",          "apt_package": "openvpn",              "category": "security", "icon": "🔑"},
    {"name": "WithSecure",           "winget_id": "",                                     "apt_package": "",                     "category": "security", "icon": "🛡️", "install_type": "msi", "installer_file": "ElementsAgentOfflineInstaller.msi", "install_args": "/qn VOUCHER=REMPLACER_PAR_VOTRE_CLE LANGUAGE=fr UNIQUE_SIGNUP_ID=smbios"},
    # Services serveur (apt uniquement)
    {"name": "Docker",               "winget_id": "",    "apt_package": "docker.io",                    "category": "server",   "icon": "🐳"},
    {"name": "Nginx",                "winget_id": "",    "apt_package": "nginx",                        "category": "server",   "icon": "🌐"},
    {"name": "Apache2",              "winget_id": "",    "apt_package": "apache2",                      "category": "server",   "icon": "🪶"},
    {"name": "PostgreSQL",           "winget_id": "",    "apt_package": "postgresql",                   "category": "server",   "icon": "🐘"},
    {"name": "MariaDB",              "winget_id": "",    "apt_package": "mariadb-server",               "category": "server",   "icon": "🦭"},
    {"name": "Redis",                "winget_id": "",    "apt_package": "redis-server",                 "category": "server",   "icon": "🔴"},
    {"name": "Fail2ban",             "winget_id": "",    "apt_package": "fail2ban",                     "category": "server",   "icon": "🚫"},
    {"name": "UFW",                  "winget_id": "",    "apt_package": "ufw",                          "category": "server",   "icon": "🧱"},
    {"name": "Certbot (Nginx)",      "winget_id": "",    "apt_package": "python3-certbot-nginx",        "category": "server",   "icon": "🔒"},
    {"name": "Node Exporter",        "winget_id": "",    "apt_package": "prometheus-node-exporter",     "category": "server",   "icon": "📊"},
    {"name": "WireGuard",            "winget_id": "",    "apt_package": "wireguard",                    "category": "server",   "icon": "🔑"},
    {"name": "Netdata",              "winget_id": "",    "apt_package": "netdata",                      "category": "server",   "icon": "📈"},
]

def _seed_apps():
    """Insère les apps manquantes (idempotent — vérifie par nom)."""
    with Session(engine) as session:
        existing_names = {a.name for a in session.exec(select(Application)).all()}
        added = 0
        for a in _SEED_APPS:
            if a["name"] not in existing_names:
                session.add(Application(**a))
                added += 1
        if added:
            session.commit()
            print(f"[OSIRIS] {added} application(s) ajoutée(s) au catalogue")


# ── Audit log ─────────────────────────────────────────────────────────────────

def _log(session: Session, user: User, action: str,
         target_mac: str | None = None, details: dict | None = None):
    """Ajoute une entrée d'audit dans la session courante (sans commit — le appelant commit)."""
    session.add(AuditLog(
        user_id=user.id,
        user_email=user.email,
        action=action,
        target_mac=target_mac,
        details=json.dumps(details, ensure_ascii=False) if details else None,
    ))


async def _send_webhook(url: str, machine: Machine, status: str):
    """Envoie une notification webhook compatible Teams / Slack / Discord / Make / n8n."""
    if not url:
        return
    icons = {"deployed": "✅", "failed": "❌", "deploying": "🔄", "pending": "⏳"}
    icon  = icons.get(status, "ℹ️")
    labels = {"deployed": "déployée", "failed": "échec", "deploying": "en cours", "pending": "en attente"}
    label  = labels.get(status, status)
    text = f"{icon} **{machine.hostname}** — {label} ({machine.os.upper()} · {machine.client})"
    payload = {
        # Champ "text" : compatibilité Teams / Slack / Discord (message lisible)
        "text": text,
        # Champs structurés : utilisables par Make, Zapier, n8n, scripts
        "event": f"machine.{status}",
        "hostname": machine.hostname,
        "mac": machine.mac,
        "client": machine.client,
        "os": machine.os,
        "hw_model": machine.hw_model,
        "hw_ram_gb": machine.hw_ram_gb,
        "hw_serial": machine.hw_serial,
        "osiris_url": OSIRIS_BASE_URL,
    }
    try:
        import urllib.request as _req
        data = json.dumps(payload).encode()
        req  = _req.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        _req.urlopen(req, timeout=5)
    except Exception:
        pass  # les webhooks sont best-effort


def _record_deploy_event(session: Session, machine: Machine, status: str):
    """Enregistre un événement de déploiement (sans commit)."""
    profile_name = ""
    if machine.profile_id:
        p = session.get(Profile, machine.profile_id)
        if p:
            profile_name = p.name
    session.add(DeploymentEvent(
        mac=machine.mac,
        hostname=machine.hostname,
        status=status,
        os=machine.os,
        profile_name=profile_name,
    ))


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {"status": "Osiris API v2026"}


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.post("/auth/login")
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == body.email)).first()
        if not user or not verify_password(body.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        _log(session, user, "login")
        session.commit()
        user_id, user_role, user_email = user.id, user.role, user.email
        has_totp = bool(user.totp_secret)
    if has_totp:
        from auth import create_temp_token
        temp = create_temp_token(str(user_id))
        return {"totp_required": True, "temp_token": temp}
    token = create_token({"sub": str(user_id), "role": user_role, "email": user_email})
    return {"access_token": token, "token_type": "bearer", "role": user_role, "email": user_email}


@app.get("/auth/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email, "role": current_user.role}


@app.patch("/auth/me/password")
def change_password(body: PasswordChange, current_user: User = Depends(get_current_user)):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Mot de passe actuel incorrect")
    with Session(engine) as session:
        user = session.get(User, current_user.id)
        user.hashed_password = hash_password(body.new_password)
        session.add(user)
        session.commit()
    return {"detail": "Mot de passe mis à jour"}


# ── Organisations ──────────────────────────────────────────────────────────────

def _org_dict(o: Organization) -> dict:
    # bios_password jamais renvoye en clair : seul un booleen dit s'il est defini.
    return {"id": o.id, "name": o.name, "slug": o.slug,
            "webhook_url": o.webhook_url, "zabbix_server": o.zabbix_server,
            "mac_prefix": o.mac_prefix, "has_bios_password": bool(o.bios_password)}


@app.get("/organizations", dependencies=[Depends(get_current_user)])
def get_organizations():
    with Session(engine) as session:
        orgs = session.exec(select(Organization)).all()
        return [_org_dict(o) for o in orgs]


@app.post("/organizations", status_code=201)
def create_organization(body: OrgCreate, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        if session.exec(select(Organization).where(Organization.slug == body.slug)).first():
            raise HTTPException(status_code=400, detail="Ce slug est déjà utilisé")
        org = Organization(name=body.name, slug=body.slug)
        session.add(org)
        _log(session, current_user, "create_org", details={"name": body.name, "slug": body.slug})
        session.commit()
        session.refresh(org)
        return _org_dict(org)


@app.patch("/organizations/{org_id}")
async def patch_organization(org_id: int, request: Request, current_user: User = Depends(require_admin)):
    """Met à jour les champs d'une organisation (ex: webhook_url, zabbix_server)."""
    data = await request.json()
    with Session(engine) as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation introuvable")
        if "webhook_url" in data:
            org.webhook_url = data["webhook_url"]
        if "zabbix_server" in data:
            org.zabbix_server = (data["zabbix_server"] or "").strip()
        if "mac_prefix" in data:
            org.mac_prefix = _validate_mac_prefix(data["mac_prefix"])
        # Chaine vide = effacement explicite du mot de passe BIOS (le champ n'est
        # envoye par l'UI que s'il a ete modifie, cf. patch partiel des fiches).
        if "bios_password" in data:
            org.bios_password = encrypt(data["bios_password"]) if data["bios_password"] else ""
        if "name" in data:
            org.name = data["name"]
        session.add(org)
        session.commit()
        session.refresh(org)
        return _org_dict(org)


@app.delete("/organizations/{org_id}", status_code=204)
def delete_organization(org_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation introuvable")
        _log(session, current_user, "delete_org", details={"name": org.name, "slug": org.slug})
        session.delete(org)
        session.commit()


# ── Domaines AD par organisation ───────────────────────────────────────────────

class DomainConfigCreate(SQLModel):
    organization_id: int
    name: str
    domain: str
    join_user: str = ""
    join_password: str = ""
    default_ou: str = ""
    wifi_ssid: str = ""
    wifi_password: str = ""

class DomainConfigPatch(SQLModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    join_user: Optional[str] = None
    join_password: Optional[str] = None
    default_ou: Optional[str] = None
    wifi_ssid: Optional[str] = None
    wifi_password: Optional[str] = None

@app.get("/domain-configs", dependencies=[Depends(get_current_user)])
def get_domain_configs(org_id: Optional[int] = None):
    with Session(engine) as session:
        query = select(DomainConfig)
        if org_id is not None:
            query = query.where(DomainConfig.organization_id == org_id)
        configs = session.exec(query).all()
        return [
            {
                "id": c.id, "organization_id": c.organization_id, "name": c.name,
                "domain": c.domain, "join_user": c.join_user, "default_ou": c.default_ou,
                "wifi_ssid": c.wifi_ssid, "has_wifi_password": bool(c.wifi_password),
                # join_password / wifi_password jamais retournes en clair
            }
            for c in configs
        ]

@app.post("/domain-configs", status_code=201)
def create_domain_config(data: DomainConfigCreate, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        cfg = DomainConfig(
            organization_id=data.organization_id,
            name=data.name,
            domain=data.domain,
            join_user=data.join_user,
            join_password=encrypt(data.join_password) if data.join_password else "",
            default_ou=data.default_ou,
            wifi_ssid=data.wifi_ssid,
            wifi_password=encrypt(data.wifi_password) if data.wifi_password else "",
        )
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return {"id": cfg.id, "name": cfg.name, "domain": cfg.domain, "join_user": cfg.join_user, "default_ou": cfg.default_ou, "wifi_ssid": cfg.wifi_ssid}

@app.patch("/domain-configs/{cfg_id}")
def update_domain_config(cfg_id: int, data: DomainConfigPatch, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        cfg = session.get(DomainConfig, cfg_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Configuration introuvable")
        if data.name is not None: cfg.name = data.name
        if data.domain is not None: cfg.domain = data.domain
        if data.join_user is not None: cfg.join_user = data.join_user
        if data.join_password is not None: cfg.join_password = encrypt(data.join_password) if data.join_password else ""
        if data.default_ou is not None: cfg.default_ou = data.default_ou
        if data.wifi_ssid is not None: cfg.wifi_ssid = data.wifi_ssid
        if data.wifi_password is not None and data.wifi_password != "":
            cfg.wifi_password = encrypt(data.wifi_password)
        session.add(cfg)
        session.commit()
        return {"detail": "ok"}

@app.delete("/domain-configs/{cfg_id}", status_code=204)
def delete_domain_config(cfg_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        cfg = session.get(DomainConfig, cfg_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Configuration introuvable")
        session.delete(cfg)
        session.commit()


# ── Tunnels VPN clients (routage site-à-site) ───────────────────────────────────

class VpnTunnelCreate(SQLModel):
    organization_id: int
    name: str
    ovpn_config: str
    remote_dns: str = ""
    route_cidr: str = ""
    vpn_username: str = ""
    vpn_password: str = ""
    requires_totp: bool = False
    enabled: bool = True

class VpnTunnelPatch(SQLModel):
    name: Optional[str] = None
    ovpn_config: Optional[str] = None
    remote_dns: Optional[str] = None
    route_cidr: Optional[str] = None
    vpn_username: Optional[str] = None
    vpn_password: Optional[str] = None
    requires_totp: Optional[bool] = None
    enabled: Optional[bool] = None

class VpnTunnelApply(SQLModel):
    totp_code: Optional[str] = None

def _serialize_vpn_tunnel(t: VpnTunnel) -> dict:
    return {
        "id": t.id, "organization_id": t.organization_id, "name": t.name, "slug": t.slug,
        "has_config": bool(t.ovpn_config), "remote_dns": t.remote_dns, "route_cidr": t.route_cidr,
        "vpn_username": t.vpn_username, "has_password": bool(t.vpn_password), "requires_totp": t.requires_totp,
        "enabled": t.enabled, "status": t.status, "last_applied_at": t.last_applied_at,
    }

@app.get("/vpn-tunnels", dependencies=[Depends(get_current_user)])
def get_vpn_tunnels(org_id: Optional[int] = None):
    with Session(engine) as session:
        query = select(VpnTunnel)
        if org_id is not None:
            query = query.where(VpnTunnel.organization_id == org_id)
        return [_serialize_vpn_tunnel(t) for t in session.exec(query).all()]

def _clean_vpn_network_fields(route_cidr: Optional[str], remote_dns: Optional[str]) -> tuple:
    """Normalise et valide les champs réseau d'un tunnel.

    Une simple espace collée en fin de champ (copier-coller depuis une doc) faisait
    échouer ipaddress.ip_network() au moment de l'Apply, très loin de la saisie et
    avec un message incompréhensible. On nettoie et on valide ici, à la source.
    """
    if route_cidr is not None:
        route_cidr = route_cidr.strip()
        if route_cidr:
            try:
                ipaddress.ip_network(route_cidr, strict=False)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Réseau distant invalide : {route_cidr!r}. Format attendu : 192.168.10.0/24",
                )
    if remote_dns is not None:
        ips = [ip.strip() for ip in remote_dns.split(",") if ip.strip()]
        for ip in ips:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"DNS distant invalide : {ip!r}. Format attendu : 192.168.10.5,192.168.10.6",
                )
        remote_dns = ",".join(ips)
    return route_cidr, remote_dns


@app.post("/vpn-tunnels", status_code=201)
def create_vpn_tunnel(data: VpnTunnelCreate, current_user: User = Depends(require_admin)):
    data.route_cidr, data.remote_dns = _clean_vpn_network_fields(data.route_cidr, data.remote_dns)
    with Session(engine) as session:
        org = session.get(Organization, data.organization_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation introuvable")
        if session.exec(select(VpnTunnel).where(VpnTunnel.organization_id == data.organization_id)).first():
            raise HTTPException(status_code=400, detail="Cette organisation a déjà un tunnel VPN")
        try:
            slug = vpn.make_slug(org.slug)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        tunnel = VpnTunnel(
            organization_id=data.organization_id, name=data.name, slug=slug,
            ovpn_config=encrypt(data.ovpn_config) if data.ovpn_config else "",
            remote_dns=data.remote_dns, route_cidr=data.route_cidr,
            vpn_username=data.vpn_username,
            vpn_password=encrypt(data.vpn_password) if data.vpn_password else "",
            requires_totp=data.requires_totp, enabled=data.enabled,
        )
        session.add(tunnel)
        _log(session, current_user, "create_vpn_tunnel", details={"organization_id": data.organization_id, "name": data.name})
        session.commit()
        session.refresh(tunnel)
        return _serialize_vpn_tunnel(tunnel)

@app.patch("/vpn-tunnels/{tunnel_id}")
def update_vpn_tunnel(tunnel_id: int, data: VpnTunnelPatch, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        tunnel = session.get(VpnTunnel, tunnel_id)
        if not tunnel:
            raise HTTPException(status_code=404, detail="Tunnel introuvable")
        if data.name is not None: tunnel.name = data.name
        if data.ovpn_config is not None and data.ovpn_config != "":
            tunnel.ovpn_config = encrypt(data.ovpn_config)
        route_cidr, remote_dns = _clean_vpn_network_fields(data.route_cidr, data.remote_dns)
        if remote_dns is not None: tunnel.remote_dns = remote_dns
        if route_cidr is not None: tunnel.route_cidr = route_cidr
        if data.vpn_username is not None: tunnel.vpn_username = data.vpn_username
        if data.vpn_password is not None and data.vpn_password != "":
            tunnel.vpn_password = encrypt(data.vpn_password)
        if data.requires_totp is not None: tunnel.requires_totp = data.requires_totp
        if data.enabled is not None: tunnel.enabled = data.enabled
        session.add(tunnel)
        session.commit()
        return {"detail": "ok"}

@app.delete("/vpn-tunnels/{tunnel_id}", status_code=204)
def delete_vpn_tunnel(tunnel_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        tunnel = session.get(VpnTunnel, tunnel_id)
        if not tunnel:
            raise HTTPException(status_code=404, detail="Tunnel introuvable")
        try:
            vpn.disable_tunnel(session, tunnel)
        except (RuntimeError, ValueError) as e:
            raise HTTPException(status_code=502, detail=f"Impossible de désactiver proprement le tunnel : {e}")
        _log(session, current_user, "delete_vpn_tunnel", details={"organization_id": tunnel.organization_id, "name": tunnel.name})
        session.delete(tunnel)
        session.commit()

@app.post("/vpn-tunnels/{tunnel_id}/apply")
def apply_vpn_tunnel(tunnel_id: int, body: VpnTunnelApply = VpnTunnelApply(), current_user: User = Depends(require_admin)):
    if body.totp_code is not None and not re.fullmatch(r"\d{4,8}", body.totp_code):
        raise HTTPException(status_code=400, detail="Code TOTP invalide")
    with Session(engine) as session:
        tunnel = session.get(VpnTunnel, tunnel_id)
        if not tunnel:
            raise HTTPException(status_code=404, detail="Tunnel introuvable")
        if not tunnel.ovpn_config:
            raise HTTPException(status_code=400, detail="Aucune configuration .ovpn enregistrée pour ce tunnel")
        try:
            vpn.apply_tunnel(session, tunnel, totp_code=body.totp_code)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            tunnel.status = "failed"
            session.add(tunnel)
            session.commit()
            raise HTTPException(status_code=502, detail=str(e))
        tunnel.status = vpn.tunnel_status(tunnel.slug)
        tunnel.last_applied_at = datetime.now(timezone.utc)
        session.add(tunnel)
        _log(session, current_user, "apply_vpn_tunnel", details={"organization_id": tunnel.organization_id, "name": tunnel.name})
        session.commit()
        return _serialize_vpn_tunnel(tunnel)

@app.get("/vpn-tunnels/{tunnel_id}/status")
def get_vpn_tunnel_status(tunnel_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        tunnel = session.get(VpnTunnel, tunnel_id)
        if not tunnel:
            raise HTTPException(status_code=404, detail="Tunnel introuvable")
        tunnel.status = vpn.tunnel_status(tunnel.slug)
        session.add(tunnel)
        session.commit()
        return {"status": tunnel.status}


# ── Utilisateurs ───────────────────────────────────────────────────────────────

@app.get("/users", dependencies=[Depends(require_admin)])
def get_users():
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        return [{"id": u.id, "email": u.email, "role": u.role} for u in users]


@app.post("/users", status_code=201)
def create_user(body: UserCreate, current_user: User = Depends(require_admin)):
    if body.role not in ("admin", "technician"):
        raise HTTPException(status_code=400, detail="Rôle invalide : admin ou technician")
    with Session(engine) as session:
        if session.exec(select(User).where(User.email == body.email)).first():
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
        new_user = User(email=body.email, hashed_password=hash_password(body.password), role=body.role)
        session.add(new_user)
        _log(session, current_user, "create_user", details={"email": body.email, "role": body.role})
        session.commit()
        session.refresh(new_user)
        return {"id": new_user.id, "email": new_user.email, "role": new_user.role}


@app.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, current_user: User = Depends(require_admin)):
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas supprimer votre propre compte")
    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        _log(session, current_user, "delete_user", details={"email": user.email})
        session.delete(user)
        session.commit()


# ── 2FA TOTP ───────────────────────────────────────────────────────────────────

APP_NAME = "OSIRIS"

@app.get("/auth/totp/setup")
def totp_setup(current_user: User = Depends(get_current_user)):
    """Genere un nouveau secret TOTP et retourne le QR code en base64. Ne sauvegarde pas encore."""
    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=current_user.email, issuer_name=APP_NAME)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    return {"secret": secret, "qr_png_b64": qr_b64, "uri": uri}


class TotpEnableRequest(SQLModel):
    secret: str   # le secret genere par /setup
    code: str     # code 6 chiffres a verifier avant de sauvegarder

@app.post("/auth/totp/enable")
def totp_enable(data: TotpEnableRequest, current_user: User = Depends(get_current_user)):
    """Confirme le secret TOTP avec un code valide et l'active sur le compte."""
    totp = pyotp.TOTP(data.secret)
    if not totp.verify(data.code, valid_window=1):
        raise HTTPException(status_code=400, detail="Code invalide ou expire")
    with Session(engine) as session:
        user = session.get(User, current_user.id)
        user.totp_secret = encrypt(data.secret)
        session.add(user)
        _log(session, current_user, "totp_enable")
        session.commit()
    return {"detail": "Double authentification activee"}


class TotpDisableRequest(SQLModel):
    password: str

@app.post("/auth/totp/disable")
def totp_disable(data: TotpDisableRequest, current_user: User = Depends(get_current_user)):
    """Desactive le 2FA apres verification du mot de passe courant."""
    if not verify_password(data.password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Mot de passe incorrect")
    with Session(engine) as session:
        user = session.get(User, current_user.id)
        user.totp_secret = ""
        session.add(user)
        _log(session, current_user, "totp_disable")
        session.commit()
    return {"detail": "Double authentification desactivee"}


@app.get("/auth/totp/status")
def totp_status(current_user: User = Depends(get_current_user)):
    return {"totp_enabled": bool(current_user.totp_secret)}


class TotpVerifyRequest(SQLModel):
    temp_token: str
    code: str

@app.post("/auth/totp/verify")
@limiter.limit("10/minute")
def totp_verify(request: Request, data: TotpVerifyRequest):
    """Deuxieme etape du login : verifie le code TOTP et retourne le vrai JWT."""
    from auth import decode_temp_token
    payload = decode_temp_token(data.temp_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token temporaire invalide ou expire")
    user_id = payload.get("sub")
    with Session(engine) as session:
        user = session.exec(select(User).where(User.id == int(user_id))).first()
        if not user or not user.totp_secret:
            raise HTTPException(status_code=401, detail="Utilisateur introuvable ou 2FA non configure")
        totp = pyotp.TOTP(decrypt(user.totp_secret))
        if not totp.verify(data.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Code incorrect")
        token = create_token({"sub": str(user.id), "role": user.role, "email": user.email})
        return {"access_token": token, "token_type": "bearer"}


# ── Cles API personnelles ──────────────────────────────────────────────────────

@app.get("/auth/api-keys")
def list_api_keys(current_user: User = Depends(get_current_user)):
    """Liste les cles API de l'utilisateur connecte (jamais la cle en clair)."""
    with Session(engine) as session:
        keys = session.exec(select(ApiKey).where(ApiKey.user_id == current_user.id)).all()
        return [
            {
                "id": k.id,
                "name": k.name,
                "prefix": k.prefix,
                "created_at": k.created_at.isoformat(),
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in keys
        ]


class ApiKeyCreate(SQLModel):
    name: str

@app.post("/auth/api-keys", status_code=201)
def create_api_key(data: ApiKeyCreate, current_user: User = Depends(get_current_user)):
    """Genere une nouvelle cle API. La cle est retournee en clair UNE SEULE FOIS."""
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Le nom de la cle est requis")
    raw_key = "osiris_sk_" + secrets.token_hex(24)   # osiris_sk_ + 48 chars hex = 58 chars total
    prefix = raw_key[:16]                              # "osiris_sk_" + 6 chars
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    with Session(engine) as session:
        api_key = ApiKey(
            user_id=current_user.id,
            name=data.name.strip(),
            prefix=prefix,
            key_hash=key_hash,
        )
        session.add(api_key)
        _log(session, current_user, "create_api_key", details={"name": data.name})
        session.commit()
        session.refresh(api_key)
        return {
            "id": api_key.id,
            "name": api_key.name,
            "prefix": api_key.prefix,
            "key": raw_key,   # retourne en clair UNE SEULE FOIS
            "created_at": api_key.created_at.isoformat(),
        }


@app.delete("/auth/api-keys/{key_id}", status_code=204)
def revoke_api_key(key_id: int, current_user: User = Depends(get_current_user)):
    """Revoque une cle API. Seul le proprietaire peut la supprimer."""
    with Session(engine) as session:
        api_key = session.get(ApiKey, key_id)
        if not api_key:
            raise HTTPException(status_code=404, detail="Cle introuvable")
        if api_key.user_id != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Acces refuse")
        _log(session, current_user, "revoke_api_key", details={"name": api_key.name})
        session.delete(api_key)
        session.commit()


# ── Profils de déploiement ─────────────────────────────────────────────────────

def _profile_dict(p: Profile) -> dict:
    return {
        "id": p.id, "name": p.name, "os": p.os,
        "locale": p.locale, "keyboard": p.keyboard, "timezone": p.timezone,
        "default_user": p.default_user, "extra_packages": p.extra_packages,
        "join_domain": p.join_domain, "domain": p.domain,
        "domain_join_user": p.domain_join_user,
        "domain_join_password": "***" if p.domain_join_password else "",
        "win_image": p.win_image,
        "win_index": p.win_index,
        "enable_bitlocker": p.enable_bitlocker,
        "bitlocker_pin": p.bitlocker_pin,
        "network_drives": p.network_drives or "",
        "printers": p.printers or "",
        "post_script": p.post_script or "",
        "tv_suffix": "***" if p.tv_suffix else "",
        "app_ids": p.app_ids or "",
        "machine_type": p.machine_type or "workstation",
        "ssh_authorized_keys": p.ssh_authorized_keys or "",
        "vm_vcpus": p.vm_vcpus,
        "vm_ram_mb": p.vm_ram_mb,
        "vm_disk_gb": p.vm_disk_gb,
        "vm_data_disk_gb": p.vm_data_disk_gb,
        "set_root_password": p.set_root_password,
    }


def _profile_for_template(p: Profile, session: Session | None = None) -> dict:
    """Profil avec secrets déchiffrés — uniquement pour les templates Jinja2, jamais renvoyé au client."""
    # Résolution du domaine AD : la DomainConfig liée fournit des valeurs, mais ne doit
    # écraser un champ du profil QUE si elle le renseigne réellement — sinon on efface
    # silencieusement le compte de jonction du profil (footgun : jonction avec creds vides).
    domain = p.domain
    domain_join_user = p.domain_join_user
    domain_join_password = decrypt(p.domain_join_password or "")
    if p.domain_config_id and session:
        dc = session.get(DomainConfig, p.domain_config_id)
        if dc:
            if dc.domain:
                domain = dc.domain
            # Le compte de jonction est un couple user+password : on ne prend celui de la
            # DomainConfig que si elle définit un utilisateur, sinon on conserve celui du profil
            # (évite de mélanger l'user de la DomainConfig avec le mot de passe du profil).
            if dc.join_user:
                domain_join_user = dc.join_user
                domain_join_password = decrypt(dc.join_password or "")
    # WiFi : porte par la DomainConfig. On la retrouve via domain_config_id, sinon
    # (profil a domaine inline) via correspondance sur le nom de domaine resolu.
    wifi_ssid = ""
    wifi_password = ""
    if session:
        dc_wifi = session.get(DomainConfig, p.domain_config_id) if p.domain_config_id else None
        if not dc_wifi and domain:
            dc_wifi = session.exec(select(DomainConfig).where(DomainConfig.domain == domain)).first()
        if dc_wifi:
            wifi_ssid = dc_wifi.wifi_ssid
            wifi_password = decrypt(dc_wifi.wifi_password or "")
    return {
        "locale": p.locale, "keyboard": p.keyboard, "timezone": p.timezone,
        "default_user": p.default_user, "extra_packages": p.extra_packages,
        "join_domain": p.join_domain, "domain": domain,
        "domain_join_user": domain_join_user,
        "domain_join_password": domain_join_password,
        "win_image": p.win_image or "",
        "win_index": p.win_index,
        "enable_bitlocker": p.enable_bitlocker,
        "bitlocker_pin": p.bitlocker_pin,
        "laps_rotation_days": p.laps_rotation_days,
        "network_drives": json.loads(p.network_drives) if p.network_drives else [],
        "printers": json.loads(p.printers) if p.printers else [],
        "post_script": p.post_script or "",
        "tv_suffix": decrypt(p.tv_suffix or ""),
        "app_ids": p.app_ids or "",
        "domain_config_id": p.domain_config_id,
        "wifi_ssid": wifi_ssid,
        "wifi_password": wifi_password,
        "machine_type": p.machine_type or "workstation",
        "ssh_authorized_keys": p.ssh_authorized_keys or "",
        "set_root_password": p.set_root_password,
        "vm_data_disk_gb": p.vm_data_disk_gb,
    }


def _resolve_profile(session: Session, machine: Machine) -> Profile:
    """Retourne le profil de la machine, ou le premier profil par défaut pour son OS."""
    if machine.profile_id:
        profile = session.get(Profile, machine.profile_id)
        if profile:
            return profile
    profile = session.exec(select(Profile).where(Profile.os == machine.os)).first()
    if profile:
        return profile
    return Profile(name="_fallback", os=machine.os)


@app.get("/profiles", dependencies=[Depends(get_current_user)])
def get_profiles():
    with Session(engine) as session:
        return [_profile_dict(p) for p in session.exec(select(Profile)).all()]


@app.post("/profiles", status_code=201)
def create_profile(body: ProfileCreate, current_user: User = Depends(require_admin)):
    if body.os not in ("ubuntu", "windows", "debian"):
        raise HTTPException(status_code=400, detail="OS invalide : ubuntu, debian ou windows")
    with Session(engine) as session:
        data = body.model_dump()
        data["tv_suffix"] = encrypt(data.get("tv_suffix", ""))
        data["domain_join_password"] = encrypt(data.get("domain_join_password", ""))
        profile = Profile(**data)
        session.add(profile)
        _log(session, current_user, "create_profile", details={"name": body.name, "os": body.os})
        session.commit()
        session.refresh(profile)
        return _profile_dict(profile)


@app.patch("/profiles/{profile_id}")
def update_profile(profile_id: int, patch: ProfilePatch, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        profile = session.get(Profile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profil introuvable")
        changes = patch.model_dump(exclude_none=True)
        if "tv_suffix" in changes:
            changes["tv_suffix"] = encrypt(changes["tv_suffix"])
        if "domain_join_password" in changes:
            changes["domain_join_password"] = encrypt(changes["domain_join_password"])
        for field, value in changes.items():
            setattr(profile, field, value)
        session.add(profile)
        _log(session, current_user, "update_profile", details={"id": profile_id, **changes})
        session.commit()
        session.refresh(profile)
        return _profile_dict(profile)


@app.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        profile = session.get(Profile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profil introuvable")
        _log(session, current_user, "delete_profile", details={"name": profile.name})
        session.delete(profile)
        session.commit()


@app.post("/profiles/{profile_id}/clone", status_code=201)
def clone_profile(profile_id: int, current_user: User = Depends(require_admin)):
    """Duplique un profil existant (tous les champs sauf l'id)."""
    with Session(engine) as session:
        src = session.get(Profile, profile_id)
        if not src:
            raise HTTPException(status_code=404, detail="Profil introuvable")
        clone = Profile(
            name=f"{src.name} (copie)",
            os=src.os, locale=src.locale, keyboard=src.keyboard, timezone=src.timezone,
            default_user=src.default_user, extra_packages=src.extra_packages,
            join_domain=src.join_domain, domain=src.domain,
            domain_join_user=src.domain_join_user, domain_join_password=src.domain_join_password,
            win_image=src.win_image, win_index=src.win_index,
            enable_bitlocker=src.enable_bitlocker, bitlocker_pin=src.bitlocker_pin,
            network_drives=src.network_drives, printers=src.printers, post_script=src.post_script,
            tv_suffix=src.tv_suffix, app_ids=src.app_ids,
        )
        session.add(clone)
        _log(session, current_user, "clone_profile", details={"source": src.name})
        session.commit()
        session.refresh(clone)
        return _profile_dict(clone)


# ── Images OS ─────────────────────────────────────────────────────────────────

class ImageCreate(SQLModel):
    name: str
    version: str
    os: str = "ubuntu"
    iso_url: str
    wim_name: str = ""   # Windows : nom du .wim cible sur le partage (ex. "server2022.wim").
                         # Vide = install.wim. Permet de faire coexister client / Server.


# ── Applications (winget / apt) ───────────────────────────────────────────────

class ApplicationCreate(SQLModel):
    name: str
    winget_id: str = ""
    apt_package: str = ""
    category: str = "tools"
    icon: str = "📦"
    linux_post_install: str = ""


class ApplicationPatch(SQLModel):
    name: Optional[str] = None
    winget_id: Optional[str] = None
    apt_package: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    linux_post_install: Optional[str] = None


def _app_dict(a: Application) -> dict:
    return {"id": a.id, "name": a.name, "winget_id": a.winget_id,
            "apt_package": a.apt_package, "category": a.category, "icon": a.icon,
            "install_type": a.install_type, "installer_file": a.installer_file,
            "linux_post_install": a.linux_post_install}


@app.get("/apps", dependencies=[Depends(get_current_user)])
def get_apps():
    with Session(engine) as session:
        return [_app_dict(a) for a in session.exec(select(Application).order_by(Application.category, Application.name)).all()]


@app.post("/apps", status_code=201)
def create_app(body: ApplicationCreate, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        app_obj = Application(**body.model_dump())
        session.add(app_obj)
        session.commit()
        session.refresh(app_obj)
        return _app_dict(app_obj)


@app.patch("/apps/{app_id}")
def patch_app(app_id: int, body: ApplicationPatch, current_user: User = Depends(require_admin)):
    """Met à jour une application du catalogue (ex: son script de post-installation Linux)."""
    with Session(engine) as session:
        app_obj = session.get(Application, app_id)
        if not app_obj:
            raise HTTPException(status_code=404, detail="Application introuvable")
        for field, value in body.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(app_obj, field, value)
        session.add(app_obj)
        session.commit()
        session.refresh(app_obj)
        return _app_dict(app_obj)


@app.delete("/apps/{app_id}", status_code=204)
def delete_app(app_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        app_obj = session.get(Application, app_id)
        if not app_obj:
            raise HTTPException(status_code=404, detail="Application introuvable")
        session.delete(app_obj)
        session.commit()


def _image_dict(img: OsImage) -> dict:
    return {
        "id": img.id, "name": img.name, "version": img.version,
        "os": img.os, "status": img.status, "progress": img.progress,
        "nfs_path": img.nfs_path, "wim_name": img.wim_name, "error": img.error,
        "created_at": img.created_at.isoformat(),
    }


@app.get("/images", dependencies=[Depends(get_current_user)])
def get_images():
    with Session(engine) as session:
        return [_image_dict(i) for i in session.exec(select(OsImage)).all()]


@app.post("/images", status_code=201)
async def create_image(body: ImageCreate, current_user: User = Depends(require_admin)):
    if body.os not in ("ubuntu", "windows", "debian"):
        raise HTTPException(status_code=400, detail="OS invalide : ubuntu, debian ou windows")
    with Session(engine) as session:
        image = OsImage(
            name=body.name, version=body.version,
            os=body.os, iso_url=body.iso_url,
            wim_name=body.wim_name.strip() if body.os == "windows" else "",
            nfs_path=f"/srv/nfs/{body.os}-{body.version}",
        )
        session.add(image)
        _log(session, current_user, "create_image", details={"name": body.name, "version": body.version})
        session.commit()
        session.refresh(image)
        image_id = image.id
        result = _image_dict(image)
    await arq_pool.enqueue_job("download_iso", image_id)
    return result


@app.delete("/images/{image_id}", status_code=204)
def delete_image(image_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        image = session.get(OsImage, image_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image introuvable")
        _log(session, current_user, "delete_image", details={"name": image.name})
        session.delete(image)
        session.commit()


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    try:
        with Session(engine) as s:
            s.exec(select(User).limit(1))
        db = "ok"
    except Exception:
        db = "error"
    return {"status": "ok" if db == "ok" else "degraded", "db": db, "version": "1.0.0"}


# ── Boot iPXE ──────────────────────────────────────────────────────────────────

_winpe_log = logging.getLogger("osiris.winpe")
_hv_log    = logging.getLogger("osiris.hypervisor")


def _winpe_driver_initrd_lines() -> str:
    """Lignes iPXE livrant les pilotes réseau WinPE à wimboot.

    wimboot injecte tout fichier `initrd` supplémentaire dans `\\Windows\\System32\\`
    de l'image démarrée, sans jamais modifier boot.wim. C'est ce qui remplace
    l'ancienne cuisson des pilotes dans le WIM : y ajouter un dossier racine
    `\\drivers\\` produisait un WIM que wimboot ne démarrait plus (constaté le
    2026-07-22 sur ZBook Firefly G8), tout en obligeant à réécrire 600 Mo à
    chaque import d'ISO. startnet.cmd fait ensuite `drvload` sur ces .inf.

    Les fichiers sont aplatis (System32 est un espace de noms plat) : un .inf et
    ses .sys/.cat se retrouvent donc côte à côte, ce dont drvload a besoin.
    """
    if not os.path.isdir(WINPE_DRIVERS_PATH):
        return ""

    lines: list[str] = []
    seen: dict[str, str] = {}
    for root, _, files in os.walk(WINPE_DRIVERS_PATH):
        for name in sorted(files):
            full = os.path.join(root, name)
            rel  = os.path.relpath(full, WINPE_DRIVERS_PATH)
            # Collision de noms : System32 étant plat, deux pilotes homonymes
            # s'écraseraient en silence. On garde le premier et on le signale.
            if name.lower() in seen:
                _winpe_log.warning(
                    "Pilote WinPE ignoré (nom déjà utilisé par %s) : %s",
                    seen[name.lower()], rel,
                )
                continue
            seen[name.lower()] = rel
            url = f"{OSIRIS_BASE_URL}/static/winpe-drivers/{quote(rel)}"
            lines.append(f"initrd --name {name} {url} {name}\n")
    return "".join(lines)


def _winpe_chain_lines() -> str:
    """Lignes iPXE qui chargent WinPE via wimboot (identiques pour toute machine)."""
    return (
        f"kernel {OSIRIS_BASE_URL}/static/wimboot\n"
        f"initrd --name bootmgr {OSIRIS_BASE_URL}/static/winpe/bootmgr bootmgr\n"
        # bootmgr.efi est le chargeur UEFI. L'exemple de référence de wimboot passe
        # LES DEUX chargeurs ; on ne servait que celui du BIOS.
        f"initrd --name bootmgr.efi {OSIRIS_BASE_URL}/static/winpe/bootmgr.efi bootmgr.efi\n"
        f"initrd --name BCD {OSIRIS_BASE_URL}/static/winpe/boot/bcd BCD\n"
        f"initrd --name boot.sdi {OSIRIS_BASE_URL}/static/winpe/boot/boot.sdi boot.sdi\n"
        f"initrd --name boot.wim {OSIRIS_BASE_URL}/static/winpe/sources/boot.wim boot.wim\n"
        + _winpe_driver_initrd_lines()
    )


@app.get("/boot")
@limiter.limit("30/minute")
def get_boot_script(request: Request, mac: str | None = None):
    if not mac:
        script = "#!ipxe\n"
        script += f"chain {OSIRIS_BASE_URL}/boot?mac=${{mac}}\n"
        return Response(content=script, media_type="text/plain")

    clean_mac = validate_mac(mac)

    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()

        if not machine:
            # Aucune machine ne porte cette MAC. Avant de rendre la main au disque
            # local, on regarde s'il existe un déploiement en attente identifié par
            # numéro de série : avec un adaptateur USB-Ethernet, la MAC vue ici n'est
            # pas celle de la machine (adaptateur partagé, 'MAC Address Pass Through'),
            # donc l'identification ne peut se faire que plus tard, dans WinPE.
            # Sans risque : si le série ne correspond à rien, le script de secours
            # refuse et ne touche pas au disque.
            pending = session.exec(
                select(Machine).where(Machine.status == "pending", Machine.hw_serial != "")
            ).first()
            win_img = session.exec(
                select(OsImage)
                .where(OsImage.os == "windows", OsImage.status == "ready")
                .order_by(OsImage.created_at.desc())
            ).first() if pending else None

            if pending and win_img:
                script = "#!ipxe\n"
                script += f"echo [OSIRIS] MAC {clean_mac} inconnue - deploiement en attente detecte\n"
                script += "echo [OSIRIS] Demarrage de WinPE pour identification par numero de serie...\n"
                script += _winpe_chain_lines()
                # Ce return court-circuite le "boot" final du flux normal : il faut donc
                # l'émettre ici. Sans lui, iPXE télécharge tout puis ne démarre rien et
                # rend la main au firmware ("no more network devices" + bip).
                script += "boot\n"
                return Response(content=script, media_type="text/plain")

            script = "#!ipxe\n"
            script += "echo ==================================================\n"
            script += "echo   BIENVENUE SUR OSIRIS RESEAU (LAB LABORATOIRE)   \n"
            script += "echo ==================================================\n"
            script += f"echo [OSIRIS] Machine inconnue (MAC: {clean_mac}).\n"
            script += "echo [OSIRIS] Boot local dans 5 secondes...\n"
            script += "sleep 5\nexit\n"
            return Response(content=script, media_type="text/plain")

        # Mode capture prioritaire — même si déjà déployée, on boot WinPE pour capturer
        if clean_mac in _capture_jobs and _capture_jobs[clean_mac]["status"] == "waiting":
            pass  # on laisse tomber dans le bloc WinPE ci-dessous

        # Machine déjà déployée → boot sur le disque local, pas de réinstall
        elif machine.status == "deployed":
            script = "#!ipxe\n"
            script += f"echo [OSIRIS] {machine.hostname} est deploye - boot local\n"
            script += "exit 1\n"
            return Response(content=script, media_type="text/plain")

        machine.status = "deploying"
        _record_deploy_event(session, machine, "deploying")
        session.add(machine)
        session.commit()

        hostname = machine.hostname
        client   = machine.client
        os_type  = machine.os

    script = "#!ipxe\n"
    script += f"echo [OSIRIS] Configuration trouvee pour {hostname} ({client})\n"

    if os_type == "windows":
        with Session(engine) as img_session:
            win_img = img_session.exec(
                select(OsImage)
                .where(OsImage.os == "windows", OsImage.status == "ready")
                .order_by(OsImage.created_at.desc())
            ).first()
        if win_img:
            script += f"echo [OSIRIS] Chargement WinPE ({win_img.name})...\n"
            script += _winpe_chain_lines()
        else:
            script += "echo [OSIRIS] Aucune image Windows disponible - boot local\n"
            script += "exit\n"
    elif os_type == "ubuntu":
        # Cherche la dernière image Ubuntu prête — fallback sur les fichiers manuels
        with Session(engine) as img_session:
            active_img = img_session.exec(
                select(OsImage)
                .where(OsImage.os == "ubuntu", OsImage.status == "ready")
                .order_by(OsImage.created_at.desc())
            ).first()
        if active_img:
            vmlinuz = f"{OSIRIS_BASE_URL}/static/ubuntu-{active_img.version}/vmlinuz"
            initrd  = f"{OSIRIS_BASE_URL}/static/ubuntu-{active_img.version}/initrd"
            nfsroot = f"{OSIRIS_IP}:{active_img.nfs_path}"
            script += f"echo [OSIRIS] Chargement {active_img.name}...\n"
        else:
            vmlinuz = f"{OSIRIS_BASE_URL}/static/vmlinuz"
            initrd  = f"{OSIRIS_BASE_URL}/static/initrd"
            nfsroot = f"{OSIRIS_IP}:/srv/nfs/ubuntu"
            script += "echo [OSIRIS] Chargement Ubuntu (image manuelle)...\n"
        script += f"kernel {vmlinuz} initrd=initrd ip=dhcp autoinstall boot=casper netboot=nfs nfsroot={nfsroot} ds=nocloud-net;s={OSIRIS_BASE_URL}/cloud-init/{clean_mac}/\n"
        script += f"initrd {initrd}\n"
    elif os_type == "debian":
        script += "echo [OSIRIS] Chargement Debian Installer...\n"
        script += f"kernel {OSIRIS_BASE_URL}/static/debian-12/linux auto=true priority=critical "
        script += f"hostname={hostname} "
        script += f"url={OSIRIS_BASE_URL}/preseed/{clean_mac} "
        script += f"locale=fr_FR.UTF-8 keymap=fr\n"
        script += f"initrd {OSIRIS_BASE_URL}/static/debian-12/initrd.gz\n"

    script += "boot\n"
    return Response(content=script, media_type="text/plain")


# ── Unattend Windows ───────────────────────────────────────────────────────────

@app.get("/unattend.xml")
def get_unattend_xml(mac: str):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            return Response(
                content="<?xml version='1.0' encoding='utf-8'?><error>Machine inconnue</error>",
                media_type="application/xml", status_code=404,
            )
        profile = _resolve_profile(session, machine)
        profile_ctx = _profile_for_template(profile, session)

    content = jinja_env.get_template("unattend.xml.j2").render(
        hostname=escape(machine.hostname),
        client=escape(machine.client),
        ou=escape(machine.ou or ""),
        profile=profile_ctx,
        win_timezone=escape(_win_timezone(profile_ctx["timezone"])),
    )
    return Response(content=content, media_type="application/xml")


# ── Cloud-init Ubuntu ──────────────────────────────────────────────────────────

@app.get("/cloud-init/{mac}/meta-data")
def get_meta_data(mac: str):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine inconnue")
    return Response(
        content=f"instance-id: osiris-{clean_mac}\nlocal-hostname: {machine.hostname}\n",
        media_type="text/plain",
    )


@app.get("/cloud-init/{mac}/user-data")
def get_user_data(mac: str):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine or not machine.password_hash:
            raise HTTPException(status_code=404, detail="Machine inconnue ou non configurée")
        profile = _resolve_profile(session, machine)

    packages = [p.strip() for p in profile.extra_packages.split(",") if p.strip()]
    content = jinja_env.get_template("user-data.j2").render(
        machine=machine,
        profile=profile,
        ssh_pubkey=SSH_PUBKEY,
        packages=packages,
        mac=clean_mac,
        osiris_url=OSIRIS_BASE_URL,
        status_url=f"{OSIRIS_BASE_URL}/machines/{clean_mac}/status",
    )
    return Response(content=content, media_type="text/plain")


def _osiris_url_for(session: Session, machine: Machine) -> str:
    """
    Adresse d'OSIRIS à graver dans les scripts de CETTE machine.

    Une VM déployée sur un autre site ne voit pas forcément OSIRIS à la même
    adresse que celles du réseau de déploiement. L'hyperviseur peut donc porter
    sa propre URL de rappel ; sans elle, on garde la globale.
    """
    if machine.hypervisor_id:
        h = session.get(Hypervisor, machine.hypervisor_id)
        if h and h.callback_url:
            return h.callback_url.rstrip("/")
    return OSIRIS_BASE_URL


def _render_linux_firstboot(mac: str) -> Response:
    """Rend le script de premier démarrage Linux (Ubuntu et Debian partagent apt-get)."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine inconnue")
        profile = _resolve_profile(session, machine)
        app_id_list = [int(i) for i in (profile.app_ids or "").split(",") if i.strip().isdigit()]
        linux_apps = session.exec(select(Application).where(Application.id.in_(app_id_list), Application.apt_package != "")).all() if app_id_list else []
        org = session.get(Organization, machine.organization_id) if machine.organization_id else None
        profile_ctx = _profile_for_template(profile, session)
        osiris_url = _osiris_url_for(session, machine)
    tv_suffix = profile_ctx.get("tv_suffix", "")
    tv_password = f"{machine.hostname.upper()}{tv_suffix}" if tv_suffix else ""
    content = jinja_env.get_template("firstboot-ubuntu.sh.j2").render(
        machine=machine,
        profile=profile_ctx,
        tv_password=tv_password,
        linux_apps=list(linux_apps),
        zabbix=_zabbix_context(machine, org),
        # Le disque de données est une décision de PROFIL (« ce type de serveur a
        # un volume de données séparé »), sa taille une décision de formulaire.
        data_disk_gb=profile_ctx.get("vm_data_disk_gb", 0),
        osiris_url=osiris_url,
    )
    return Response(content=content, media_type="text/plain")


def _zabbix_context(machine: Machine, org: Optional[Organization]) -> Optional[dict]:
    """
    Paramètres de l'agent Zabbix pour cette machine, ou None s'il ne faut pas l'installer.

    Deux conditions : la machine est cochée « supervisée » ET son organisation
    déclare un collecteur. Sans organisation, pas d'adresse à qui parler — on
    n'installe rien plutôt que d'installer un agent muet.
    """
    if not machine.supervised or not org or not org.zabbix_server:
        return None
    return {
        "server": org.zabbix_server,
        "hostname": machine.hostname,
        # Lu par l'action d'auto-enregistrement côté Zabbix pour ranger l'hôte
        # dans le bon groupe / modèle sans avoir à le créer à la main.
        "metadata": f"osiris linux {org.slug}".strip(),
    }


@app.get("/bootstrap/linux")
def get_linux_bootstrap():
    """
    Installateur du mécanisme d'amorçage générique, à passer une fois dans la VM
    qui servira de template : `curl -sf <osiris>/bootstrap/linux | bash`.

    Pas d'authentification, et c'est volontaire : le script ne contient aucun
    secret — l'adresse d'OSIRIS et rien d'autre. Toute la configuration reste
    servie par les routes /firstboot-*, qui exigent de connaître une MAC déjà
    enregistrée. C'est ce qui permet de ne stocker aucun identifiant dans le
    template, contrairement à un compte Proxmox dédié.
    """
    content = jinja_env.get_template("bootstrap-linux.sh.j2").render(
        osiris_url=OSIRIS_BASE_URL,
    )
    return Response(content=content, media_type="text/plain")


@app.get("/firstboot-linux/{mac}")
def get_linux_firstboot(mac: str):
    """
    Point d'entrée générique du premier démarrage Linux — celui qu'appelle le
    mécanisme d'amorçage cuit dans les templates de VM, qui ignore la distribution.
    """
    return _render_linux_firstboot(mac)


@app.get("/firstboot-ubuntu/{mac}")
def get_ubuntu_firstboot(mac: str):
    """Script bash généré à la volée, exécuté au premier démarrage Ubuntu via systemd oneshot."""
    return _render_linux_firstboot(mac)


@app.get("/preseed/{mac}")
def get_preseed(mac: str):
    """Fichier preseed Debian généré à la volée pour l'installation automatique."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine or not machine.password_hash:
            raise HTTPException(status_code=404, detail="Machine inconnue ou non configurée")
        profile = _resolve_profile(session, machine)
    packages = [p.strip() for p in (profile.extra_packages or "").split(",") if p.strip()]
    content = jinja_env.get_template("preseed.cfg.j2").render(
        machine=machine,
        profile=_profile_for_template(profile, session),
        packages=packages,
        mac=clean_mac,
        osiris_url=OSIRIS_BASE_URL,
        status_url=f"{OSIRIS_BASE_URL}/machines/{clean_mac}/status",
    )
    return Response(content=content, media_type="text/plain")


@app.get("/firstboot-debian/{mac}")
def get_debian_firstboot(mac: str):
    """Réutilise le template Ubuntu — apt-get est identique sur Debian."""
    return _render_linux_firstboot(mac)


@app.get("/firstboot-windows/{mac}")
def get_windows_firstboot(mac: str):
    """Script PowerShell généré à la volée, exécuté au 1er démarrage Windows via unattend FirstLogonCommands."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine inconnue")
        profile = _resolve_profile(session, machine)
        app_id_list = [int(i) for i in (profile.app_ids or "").split(",") if i.strip().isdigit()]
        # Apps Windows : winget OU installeur custom (MSI/EXE heberge, ex: WithSecure)
        win_apps = session.exec(select(Application).where(
            Application.id.in_(app_id_list),
            (Application.winget_id != "") | (Application.installer_file != ""),
        )).all() if app_id_list else []
        # Reglages materiel imposes par le client (mot de passe BIOS, convention MAC).
        # Portes par l'organisation : ils ne dependent ni du profil ni du domaine AD.
        org = session.get(Organization, machine.organization_id) if machine.organization_id else None
        bios_password = decrypt(org.bios_password or "") if org else ""
        forced_mac = mac_from_hostname(machine.hostname, org.mac_prefix) if org else ""
    profile_ctx = _profile_for_template(profile, session)
    tv_suffix = profile_ctx.get("tv_suffix", "")
    tv_password = f"{machine.hostname.upper()}{tv_suffix}" if tv_suffix else ""
    content = jinja_env.get_template("firstboot-windows.ps1.j2").render(
        machine=machine,
        profile=profile_ctx,
        tv_password=tv_password,
        win_apps=list(win_apps),
        osiris_url=OSIRIS_BASE_URL,
        osiris_ip=OSIRIS_IP,
        bios_password=bios_password,
        forced_mac=forced_mac,
    )
    return Response(content=content, media_type="text/plain")


# ── CRUD machines ──────────────────────────────────────────────────────────────

@app.post("/machines", status_code=201)
def create_machine(machine: Machine, current_user: User = Depends(get_current_user)):
    clean_mac = validate_mac(machine.mac)
    machine.mac = clean_mac
    # MAC de l'adaptateur : facultative. Une chaîne vide vaut "pas de dongle" (None),
    # sinon on normalise comme la MAC du PC.
    raw_deploy_mac = (machine.deploy_mac or "").strip()
    machine.deploy_mac = validate_mac(raw_deploy_mac) if raw_deploy_mac else None
    if machine.deploy_mac == clean_mac:
        raise HTTPException(
            status_code=400, detail="L'adaptateur ne peut pas avoir la même MAC que le PC"
        )

    plaintext_password = secrets.token_urlsafe(16)
    machine.password_hash = sha512_crypt.using(rounds=100000).hash(plaintext_password)

    with Session(engine) as session:
        if session.exec(select(Machine).where(Machine.mac == clean_mac)).first():
            raise HTTPException(status_code=400, detail="Cette adresse MAC est déjà enregistrée.")
        if machine.deploy_mac:
            holder = session.exec(
                select(Machine).where(Machine.deploy_mac == machine.deploy_mac)
            ).first()
            if holder:
                raise HTTPException(
                    status_code=409,
                    detail=f"Adaptateur déjà affecté à {holder.hostname} ({holder.mac}) "
                           f"— le libérer d'abord",
                )
        session.add(machine)
        _log(session, current_user, "create_machine", target_mac=clean_mac,
             details={"hostname": machine.hostname, "client": machine.client, "os": machine.os})
        session.commit()
        session.refresh(machine)

    return {
        "id": machine.id, "mac": machine.mac, "deploy_mac": machine.deploy_mac,
        "client": machine.client,
        "os": machine.os, "hostname": machine.hostname, "ou": machine.ou,
        "status": machine.status, "organization_id": machine.organization_id,
        "profile_id": machine.profile_id, "supervised": machine.supervised,
        "password": plaintext_password,
    }


@app.post("/webhooks/new-machine", status_code=200)
def webhook_new_machine(data: WebhookNewMachine, current_user: User = Depends(get_current_user)):
    """
    Endpoint simplifié pour pré-enregistrer une machine depuis un outil externe.
    Idempotent : si la MAC existe déjà, retourne la machine existante sans erreur.
    Champs requis : mac. Tout le reste est optionnel avec des valeurs par défaut.
    """
    clean_mac = validate_mac(data.mac)
    with Session(engine) as session:
        existing = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if existing:
            return {"created": False, "mac": existing.mac, "hostname": existing.hostname,
                    "client": existing.client, "os": existing.os, "status": existing.status}
        machine = Machine(
            mac=clean_mac,
            hostname=data.hostname or clean_mac,
            client=data.client,
            os=data.os,
            status="pending",
            organization_id=data.organization_id,
            profile_id=data.profile_id,
            ou="",
            password_hash=sha512_crypt.using(rounds=100000).hash(secrets.token_urlsafe(16)),
        )
        session.add(machine)
        _log(session, current_user, "create_machine", target_mac=clean_mac,
             details={"hostname": machine.hostname, "client": machine.client,
                      "os": machine.os, "source": "webhook"})
        session.commit()
        session.refresh(machine)
    return {"created": True, "mac": machine.mac, "hostname": machine.hostname,
            "client": machine.client, "os": machine.os, "status": machine.status}


@app.get("/machines", dependencies=[Depends(get_current_user)])
def get_all_machines(org_id: Optional[int] = None):
    with Session(engine) as session:
        query = select(Machine)
        if org_id is not None:
            query = query.where(Machine.organization_id == org_id)
        machines = session.exec(query).all()
        return [
            {
                "id": m.id, "mac": m.mac, "deploy_mac": m.deploy_mac, "client": m.client,
                "os": m.os, "hostname": m.hostname, "ou": m.ou,
                "status": m.status, "organization_id": m.organization_id,
                "profile_id": m.profile_id, "driver_pack_id": m.driver_pack_id,
                "deployed_at": m.deployed_at.isoformat() if m.deployed_at else None,
                "hw_serial": m.hw_serial, "hw_model": m.hw_model, "hw_ram_gb": m.hw_ram_gb,
                "hw_disk_gb": m.hw_disk_gb, "hw_disk_type": m.hw_disk_type, "hw_cpu": m.hw_cpu,
                "notes": m.notes,
                "user_name": m.user_name, "user_email": m.user_email,
                "supervised": m.supervised,
                "ip_cidr": m.ip_cidr, "gateway": m.gateway, "dns_servers": m.dns_servers,
                "has_bitlocker": bool(m.bitlocker_key),
                "has_laps": bool(m.laps_password),
                "hypervisor_id": m.hypervisor_id,
                "proxmox_vm_id": m.proxmox_vm_id,
                "proxmox_node": m.proxmox_node,
            }
            for m in machines
        ]


# Champs de la fiche machine qu'un PATCH peut remettre à null (nullable en base).
# `deploy_mac` a son propre traitement, la chaîne vide y valant aussi libération.
_MACHINE_NULLABLE_FIELDS = {"organization_id", "profile_id", "driver_pack_id", "deploy_mac"}


@app.patch("/machines/{mac}")
def update_machine(mac: str, patch: MachinePatch, current_user: User = Depends(get_current_user)):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        # exclude_unset (et non exclude_none) : seuls les champs RÉELLEMENT présents
        # dans le corps de la requête sont pris en compte. Un `null` explicite devient
        # donc une demande de vidage, là où il était auparavant ignoré — retirer le
        # pack de pilotes d'une machine n'avait aucun effet et échouait en silence.
        # L'UI n'envoie que les champs modifiés, la sémantique se rejoint.
        changes = patch.model_dump(exclude_unset=True)
        # Un `null` n'a de sens que sur les champs qui l'acceptent en base (les
        # clés étrangères) : ailleurs il ferait échouer la mise à jour. Sur les
        # champs texte, on l'ignore comme avant.
        for field in [f for f, v in changes.items() if v is None]:
            if field not in _MACHINE_NULLABLE_FIELDS:
                changes.pop(field)
        # `deploy_mac` accepte en plus la chaîne vide comme demande de libération
        # (libérer le dongle à la main, sans attendre la fin d'un déploiement).
        audit_extra = {}
        if "deploy_mac" in changes:
            raw = (changes.pop("deploy_mac") or "").strip()
            new_deploy_mac = validate_mac(raw) if raw else None
            if new_deploy_mac:
                if new_deploy_mac == machine.mac:
                    raise HTTPException(
                        status_code=400,
                        detail="L'adaptateur ne peut pas avoir la même MAC que le PC",
                    )
                holder = session.exec(
                    select(Machine).where(
                        Machine.deploy_mac == new_deploy_mac, Machine.id != machine.id
                    )
                ).first()
                if holder:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Adaptateur déjà affecté à {holder.hostname} "
                               f"({holder.mac}) — le libérer d'abord",
                    )
            machine.deploy_mac = new_deploy_mac
            audit_extra["deploy_mac"] = new_deploy_mac
        for field, value in changes.items():
            setattr(machine, field, value)
        session.add(machine)
        _log(session, current_user, "update_machine", target_mac=clean_mac,
             details={**changes, **audit_extra})
        session.commit()
        session.refresh(machine)
        return {
            "id": machine.id, "mac": machine.mac, "client": machine.client,
            "os": machine.os, "hostname": machine.hostname, "ou": machine.ou,
            "status": machine.status, "organization_id": machine.organization_id,
            "deploy_mac": machine.deploy_mac, "supervised": machine.supervised,
        }


@app.delete("/machines/{mac}", status_code=204)
async def delete_machine(mac: str, destroy_proxmox: bool = False, current_user: User = Depends(require_admin)):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        vm_id = machine.proxmox_vm_id
        hv_id = machine.hypervisor_id
        node = machine.proxmox_node
        hostname = machine.hostname
        client = machine.client
        h = session.get(Hypervisor, hv_id) if (destroy_proxmox and vm_id and hv_id) else None

    if destroy_proxmox and vm_id and hv_id and h:
        # Par le provider : la destruction n'a rien de commun entre un appel
        # Proxmox et un Destroy_Task vSphere. Si la VM n'existe plus côté
        # hyperviseur, on supprime quand même la fiche d'OSIRIS.
        try:
            await _provider(h).destroy_vm(h, node, vm_id)
        except HTTPException:
            pass

    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if machine:
            _log(session, current_user, "delete_machine", target_mac=clean_mac,
                 details={"hostname": hostname, "client": client, "destroy_proxmox": destroy_proxmox})
            session.delete(machine)
            session.commit()


class VmPowerBody(SQLModel):
    action: str  # "start" | "shutdown" | "stop" | "reboot"


@app.post("/machines/{mac}/vm-power")
async def vm_power(mac: str, body: VmPowerBody, current_user: User = Depends(require_admin)):
    """Contrôle l'état d'alimentation d'une VM Proxmox (start/shutdown/stop/reboot)."""
    if body.action not in ("start", "shutdown", "stop", "reboot"):
        raise HTTPException(status_code=400, detail="Action invalide")
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine or not machine.proxmox_vm_id or not machine.hypervisor_id:
            raise HTTPException(status_code=404, detail="Machine introuvable ou non liée à Proxmox")
        h = session.get(Hypervisor, machine.hypervisor_id)
        if not h:
            raise HTTPException(status_code=404, detail="Hyperviseur introuvable")
        vm_id = machine.proxmox_vm_id
        node = machine.proxmox_node
    await _proxmox_post(h,
        f"/api2/json/nodes/{node}/qemu/{vm_id}/status/{body.action}")
    return {"ok": True, "action": body.action}


@app.get("/machines/{mac}/vm-status")
async def vm_status(mac: str, _: User = Depends(get_current_user)):
    """Retourne le statut d'alimentation live d'une VM Proxmox."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine or not machine.proxmox_vm_id or not machine.hypervisor_id:
            raise HTTPException(status_code=404, detail="Machine introuvable ou non liée à Proxmox")
        h = session.get(Hypervisor, machine.hypervisor_id)
        if not h:
            raise HTTPException(status_code=404, detail="Hyperviseur introuvable")
        vm_id = machine.proxmox_vm_id
        node = machine.proxmox_node
    data = await _proxmox_get(h,
        f"/api2/json/nodes/{node}/qemu/{vm_id}/status/current")
    return {
        "vm_id":  vm_id,
        "node":   node,
        "status": data.get("status", "unknown"),  # "running" | "stopped" | "paused"
        "cpu":    round(data.get("cpu", 0) * 100, 1),
        "mem_mb": round(data.get("mem", 0) / 1048576),
        "uptime": data.get("uptime", 0),
    }


class SnapshotCreateBody(SQLModel):
    name: str
    description: str = ""


def _get_vm_and_hypervisor(mac: str) -> tuple:
    """Retourne (h, vm_id, node) pour une machine VM, ou lève 404."""
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == mac)).first()
        if not machine or not machine.proxmox_vm_id or not machine.hypervisor_id:
            raise HTTPException(status_code=404, detail="Machine introuvable ou non liée à Proxmox")
        h = session.get(Hypervisor, machine.hypervisor_id)
        if not h:
            raise HTTPException(status_code=404, detail="Hyperviseur introuvable")
        return h, machine.proxmox_vm_id, machine.proxmox_node


@app.get("/machines/{mac}/snapshots")
async def list_snapshots(mac: str, _: User = Depends(require_admin)):
    clean_mac = validate_mac(mac)
    h, vm_id, node = _get_vm_and_hypervisor(clean_mac)
    data = await _proxmox_get(h, f"/api2/json/nodes/{node}/qemu/{vm_id}/snapshot")
    return data if isinstance(data, list) else []


@app.post("/machines/{mac}/snapshots", status_code=201)
async def create_snapshot(mac: str, body: SnapshotCreateBody, current_user: User = Depends(require_admin)):
    import re as _re
    if not body.name or not _re.match(r'^[a-zA-Z0-9_\-]{1,40}$', body.name):
        raise HTTPException(status_code=400, detail="Nom de snapshot invalide (alphanumérique, tirets, underscores, max 40 chars)")
    clean_mac = validate_mac(mac)
    h, vm_id, node = _get_vm_and_hypervisor(clean_mac)
    upid = await _proxmox_post(h, f"/api2/json/nodes/{node}/qemu/{vm_id}/snapshot", {
        "snapname": body.name,
        "description": body.description,
    })
    if isinstance(upid, str):
        await _proxmox_wait_task(h, node, upid)
    return {"ok": True, "name": body.name}


@app.post("/machines/{mac}/snapshots/{name}/rollback")
async def rollback_snapshot(mac: str, name: str, _: User = Depends(require_admin)):
    clean_mac = validate_mac(mac)
    h, vm_id, node = _get_vm_and_hypervisor(clean_mac)
    upid = await _proxmox_post(h, f"/api2/json/nodes/{node}/qemu/{vm_id}/snapshot/{name}/rollback", {"start": 0})
    if isinstance(upid, str):
        await _proxmox_wait_task(h, node, upid)
    return {"ok": True}


@app.delete("/machines/{mac}/snapshots/{name}", status_code=204)
async def delete_snapshot(mac: str, name: str, _: User = Depends(require_admin)):
    clean_mac = validate_mac(mac)
    h, vm_id, node = _get_vm_and_hypervisor(clean_mac)
    upid = await _proxmox_delete(h, f"/api2/json/nodes/{node}/qemu/{vm_id}/snapshot/{name}")
    if isinstance(upid, str):
        await _proxmox_wait_task(h, node, upid)


@app.post("/machines/{mac}/hardware")
def post_hardware(mac: str, data: dict):
    """Remonte les infos materiel collectees au premier demarrage (sans auth - appele par la machine)."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        machine.hw_serial = (data.get("serial") or "")[:128]
        machine.hw_model  = (data.get("model") or "")[:128]
        machine.hw_ram_gb = int(data.get("ram_gb") or 0)
        machine.hw_disk_gb = int(data.get("disk_gb") or 0)
        machine.hw_disk_type = (data.get("disk_type") or "")[:64]
        machine.hw_cpu    = (data.get("cpu") or "")[:128]
        session.add(machine)
        session.commit()
    return {"detail": "ok"}


@app.post("/machines/{mac}/bitlocker-key")
def post_bitlocker_key(mac: str, data: dict):
    """Stocke la cle de recuperation et/ou le PIN BitLocker chiffres (sans auth - appele par la machine en firstboot)."""
    clean_mac = validate_mac(mac)
    key = (data.get("key") or "").strip()
    pin = (data.get("pin") or "").strip()
    if not key and not pin:
        raise HTTPException(status_code=400, detail="Cle ou PIN manquant")
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        if key:
            machine.bitlocker_key = encrypt(key)
        if pin:
            machine.bitlocker_pin = encrypt(pin)
        session.add(machine)
        session.commit()
    return {"detail": "ok"}


@app.get("/machines/{mac}/bitlocker-key")
def get_bitlocker_key(mac: str, current_user: User = Depends(require_admin)):
    """Retourne la cle de recuperation et le PIN BitLocker en clair (admins uniquement)."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        if not machine.bitlocker_key and not machine.bitlocker_pin:
            raise HTTPException(status_code=404, detail="Aucune donnee BitLocker enregistree")
        return {
            "key": decrypt(machine.bitlocker_key) if machine.bitlocker_key else None,
            "pin": decrypt(machine.bitlocker_pin) if machine.bitlocker_pin else None,
            "hostname": machine.hostname,
        }


@app.post("/machines/{mac}/laps-password")
def post_laps_password(mac: str, data: dict):
    """Stocke le mot de passe admin local (LAPS) chiffre (sans auth - appele par la machine en firstboot ou rotation)."""
    clean_mac = validate_mac(mac)
    password = (data.get("password") or "").strip()
    if not password:
        raise HTTPException(status_code=400, detail="Mot de passe manquant")
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        machine.laps_password = encrypt(password)
        machine.laps_rotated_at = datetime.now(timezone.utc)
        session.add(machine)
        session.commit()
    return {"detail": "ok"}


@app.get("/machines/{mac}/laps-due")
def laps_due(mac: str):
    """
    Verifie si la rotation LAPS est due pour cette machine.
    Sans auth : appele par le script de renouvellement au demarrage Windows.
    Retourne {due: true} si la rotation est activee sur le profil et que la
    periode est ecoulee depuis la derniere rotation (ou depuis le deploiement).
    """
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine or not machine.profile_id:
            return {"due": False}
        profile = session.get(Profile, machine.profile_id)
        if not profile or profile.laps_rotation_days == 0:
            return {"due": False}
        # Partir de la date de derniere rotation, ou du deploiement, ou de l'epoque
        last = machine.laps_rotated_at or machine.deployed_at
        if not last:
            return {"due": True}
        last_utc = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
        due_at = last_utc + timedelta(days=profile.laps_rotation_days)
        return {"due": datetime.now(timezone.utc) >= due_at, "due_at": due_at.isoformat()}


@app.get("/machines/{mac}/laps-password")
def get_laps_password(mac: str, current_user: User = Depends(require_admin)):
    """Retourne le mot de passe admin local en clair (admins uniquement)."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        if not machine.laps_password:
            raise HTTPException(status_code=404, detail="Aucun mot de passe LAPS enregistre")
        return {
            "password": decrypt(machine.laps_password),
            "hostname": machine.hostname,
        }


@app.post("/machines/{mac}/smoke-tests")
def post_smoke_tests(mac: str, data: dict):
    """
    Recoit le rapport de smoke tests envoye par le script firstboot en fin de deploiement.
    Pas d'auth : appele par la machine elle-meme comme les autres callbacks firstboot.
    Payload : {"tests": [{"name": "...", "ok": true/false, "detail": "..."}]}
    """
    clean_mac = validate_mac(mac)
    tests = data.get("tests", [])
    if not isinstance(tests, list):
        raise HTTPException(status_code=400, detail="Format invalide : 'tests' doit etre une liste")
    overall = "ok" if all(t.get("ok", False) for t in tests) else "warnings"
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        machine.smoke_status = overall
        machine.smoke_results = json.dumps(tests, ensure_ascii=False)
        session.add(machine)
        session.commit()
    import threading
    def _ws_notify():
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                manager.broadcast(clean_mac, {"type": "smoke", "status": overall, "tests": tests})
            )
            loop.close()
        except Exception:
            pass
    threading.Thread(target=_ws_notify, daemon=True).start()
    return {"detail": "ok", "status": overall, "tests_count": len(tests),
            "failed": sum(1 for t in tests if not t.get("ok", False))}


@app.post("/machines/{mac}/redeploy-now", dependencies=[Depends(get_current_user)])
def redeploy_now(mac: str):
    """Remet la machine en pending ET envoie un magic packet WoL en une seule action."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        _open_new_deploy_run(machine)
        session.add(machine)
        session.commit()
    formatted = ":".join(clean_mac[i:i+2] for i in range(0, 12, 2))
    try:
        wakeonlan.send_magic_packet(formatted, ip_address="10.0.0.255", port=9)
    except Exception:
        pass
    return {"detail": f"Machine {clean_mac} repassee en pending + WoL envoye"}


@app.get("/dashboard", dependencies=[Depends(get_current_user)])
def get_dashboard():
    """Statistiques globales pour le tableau de bord."""
    now = datetime.now(timezone.utc)
    stuck_deploying_threshold = now - timedelta(minutes=30)
    failed_threshold = now - timedelta(hours=24)

    with Session(engine) as session:
        machines = session.exec(select(Machine)).all()
        orgs = {o.id: o.name for o in session.exec(select(Organization)).all()}

        # Stats globales par statut
        status_counts = {"pending": 0, "deploying": 0, "deployed": 0, "failed": 0}
        for m in machines:
            status_counts[m.status] = status_counts.get(m.status, 0) + 1

        # Stats par organisation
        org_stats: dict = {}
        for m in machines:
            oid = m.organization_id or 0
            if oid not in org_stats:
                org_stats[oid] = {
                    "org_id": oid,
                    "org_name": orgs.get(oid, "Sans organisation"),
                    "pending": 0, "deploying": 0, "deployed": 0, "failed": 0, "total": 0,
                }
            org_stats[oid][m.status] = org_stats[oid].get(m.status, 0) + 1
            org_stats[oid]["total"] += 1

        # Alertes : machines bloquees
        alerts = []
        for m in machines:
            if m.status == "deploying":
                # On cherche le dernier evenement deploying
                last_ev = session.exec(
                    select(DeploymentEvent)
                    .where(DeploymentEvent.mac == m.mac, DeploymentEvent.status == "deploying")
                    .order_by(DeploymentEvent.timestamp.desc())
                ).first()
                if last_ev and last_ev.timestamp.replace(tzinfo=timezone.utc) < stuck_deploying_threshold:
                    alerts.append({"type": "stuck_deploying", "hostname": m.hostname, "mac": m.mac,
                                   "since": last_ev.timestamp.isoformat()})
            elif m.status == "failed":
                last_ev = session.exec(
                    select(DeploymentEvent)
                    .where(DeploymentEvent.mac == m.mac, DeploymentEvent.status == "failed")
                    .order_by(DeploymentEvent.timestamp.desc())
                ).first()
                if last_ev and last_ev.timestamp.replace(tzinfo=timezone.utc) > failed_threshold:
                    alerts.append({"type": "failed_recent", "hostname": m.hostname, "mac": m.mac,
                                   "since": last_ev.timestamp.isoformat()})

        # Derniers deploiements termines
        recent_events = session.exec(
            select(DeploymentEvent)
            .where(DeploymentEvent.status.in_(["deployed", "failed"]))
            .order_by(DeploymentEvent.timestamp.desc())
            .limit(15)
        ).all()

        return {
            "status_counts": status_counts,
            "total_machines": len(machines),
            "org_stats": list(org_stats.values()),
            "alerts": alerts,
            "recent_deployments": [
                {
                    "hostname": e.hostname, "mac": e.mac, "status": e.status,
                    "os": e.os, "profile_name": e.profile_name,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in recent_events
            ],
        }


@app.get("/audit-logs", dependencies=[Depends(require_admin)])
def get_audit_logs(
    limit: int = 100,
    skip: int = 0,
    action: str = "",
    user_email: str = "",
    mac: str = "",
):
    with Session(engine) as session:
        q = select(AuditLog).order_by(AuditLog.timestamp.desc())
        if action:
            q = q.where(AuditLog.action == action)
        if user_email:
            q = q.where(AuditLog.user_email.contains(user_email))
        if mac:
            clean = mac.replace(":", "").replace("-", "").lower()
            q = q.where(AuditLog.target_mac == clean)
        q = q.offset(skip).limit(limit)
        logs = session.exec(q).all()
        return [
            {
                "id": l.id,
                "timestamp": l.timestamp.isoformat(),
                "user_email": l.user_email,
                "action": l.action,
                "target_mac": l.target_mac,
                "details": json.loads(l.details) if l.details else None,
            }
            for l in logs
        ]


@app.post("/machines/{mac}/status")
@limiter.limit("10/minute")
def report_machine_status(request: Request, mac: str, status: str, background_tasks: BackgroundTasks):
    """Appelé par la machine elle-même via curl pendant l'installation."""
    clean_mac = validate_mac(mac)
    valid = {"pending", "deploying", "deployed", "failed"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"Statut invalide. Valeurs : {valid}")
    deployed_at = None
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        # Le meme statut peut etre poste plusieurs fois (ex: "deployed" par WinPE
        # juste avant le reboot PUIS par le firstboot apres l'OOBE). On ne journalise
        # l'evenement et n'envoie le webhook que sur un VRAI changement de statut,
        # pour eviter les doublons dans "Deploiements recents" / les notifications.
        status_changed = (machine.status != status)
        machine.status = status
        if status == "deployed":
            machine.deployed_at = datetime.now(timezone.utc)
            deployed_at = machine.deployed_at.isoformat()
            # OUBLI DU DONGLE : l'adaptateur USB-Ethernet n'a servi qu'à ce déploiement.
            # On le libère dès la fin pour qu'il puisse être déclaré sur la machine
            # suivante sans conflit (l'index unique refuserait un doublon). L'identité
            # du poste reste intacte : elle tient à `mac` et `hw_serial`.
            if machine.deploy_mac:
                _append_log_line(
                    session, clean_mac, machine.deploy_log_run,
                    _stamp(f"Adaptateur {machine.deploy_mac} libere : "
                           f"reutilisable sur une autre machine"),
                )
                machine.deploy_mac = None
        if status == "pending":
            # Un redeploiement ouvre un NOUVEAU journal au lieu d'effacer le precedent :
            # c'est justement apres une tentative ratee qu'on relance, et c'est cette
            # trace-la qu'on veut encore pouvoir lire.
            _open_new_deploy_run(machine)
        if status_changed:
            _record_deploy_event(session, machine, status)
        elif status == "deployed":
            # "deployed" est poste 2x : par WinPE juste avant le reboot (pour eviter
            # une boucle de redeploiement au reboot) PUIS par le firstboot a la vraie
            # fin. On garde UN seul evenement, mais on avance son horodatage au dernier
            # post (firstboot = vraie fin) au lieu de celui, premature, de WinPE.
            last_dep = session.exec(
                select(DeploymentEvent)
                .where(DeploymentEvent.mac == clean_mac, DeploymentEvent.status == "deployed")
                .order_by(DeploymentEvent.timestamp.desc())
            ).first()
            if last_dep:
                last_dep.timestamp = datetime.now(timezone.utc)
                session.add(last_dep)
            else:
                _record_deploy_event(session, machine, status)
        session.add(machine)
        # Récupère le webhook de l'org avant le commit pour éviter session expirée
        webhook_url = ""
        if status_changed and status in ("deployed", "failed") and machine.organization_id:
            org = session.get(Organization, machine.organization_id)
            if org:
                webhook_url = org.webhook_url
        machine_snapshot = machine  # référence avant commit
        session.commit()
    background_tasks.add_task(
        manager.broadcast,
        {"mac": clean_mac, "status": status, "deployed_at": deployed_at},
    )
    if webhook_url:
        background_tasks.add_task(_send_webhook, webhook_url, machine_snapshot, status)
    return {"detail": "Statut mis à jour"}


@app.get("/machines/{mac}/history", dependencies=[Depends(get_current_user)])
def get_machine_history(mac: str):
    """Retourne les 20 derniers événements de déploiement pour une machine."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        events = session.exec(
            select(DeploymentEvent)
            .where(DeploymentEvent.mac == clean_mac)
            .order_by(DeploymentEvent.timestamp.desc())
            .limit(20)
        ).all()
        return [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat(),
                "status": e.status,
                "os": e.os,
                "profile_name": e.profile_name,
                "hostname": e.hostname,
            }
            for e in events
        ]


@app.post("/machines/{mac}/deploy-progress")
@limiter.limit("60/minute")
async def report_deploy_progress(request: Request, mac: str, p: int):
    """Appelé par WinPE à chaque étape pour mettre à jour la progression DISM."""
    clean_mac = validate_mac(mac)
    progress = max(0, min(100, p))
    _deploy_progress[clean_mac] = progress
    await manager.broadcast({"mac": clean_mac, "dism_progress": progress})
    return {"ok": True}


def _a_un_lecteur_cloudinit(config: dict) -> bool:
    """Cette config de VM Proxmox porte-t-elle deja un lecteur cloud-init ?

    On balaie toutes les valeurs plutot que le seul `ide2` : le lecteur peut vivre
    sur n'importe quel emplacement IDE/SATA/SCSI selon la main qui a fabrique le
    template, et un doublon a un autre emplacement casserait tout autant.
    """
    return any("cloudinit" in str(v) for v in config.values())


def _open_new_deploy_run(machine: Machine) -> None:
    """Repasse une machine en attente et ouvre un nouveau journal de déploiement.

    À appeler PARTOUT où une machine retourne en "pending" — le statut est remis à
    zéro depuis quatre endroits (rapport de la machine, redeploy-now, lot, capture),
    et un seul qui incrémenterait le compteur suffirait à mélanger les journaux de
    deux tentatives.
    """
    machine.status = "pending"
    machine.deploy_log_run += 1
    _deploy_progress.pop(machine.mac, None)


def _stamp(msg: str) -> str:
    """Horodate une ligne de journal (UTC, comme tout le reste de l'API)."""
    return f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"


def _current_run(session: Session, clean_mac: str) -> int:
    """Numéro du déploiement en cours pour cette MAC.

    Porté par la fiche machine ; les lignes postées par une MAC inconnue (machine
    supprimée en plein déploiement, par exemple) atterrissent dans le run 1 plutôt
    que d'être perdues.
    """
    machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
    return machine.deploy_log_run if machine else 1


def _append_log_line(session: Session, clean_mac: str, run: int, line: str) -> None:
    """Ajoute une ligne au journal, en s'arrêtant net au-delà du plafond.

    N'appelle pas `commit()` : la ligne part avec la transaction de l'appelant.
    """
    written = session.exec(
        select(func.count()).select_from(DeployLogLine)
        .where(DeployLogLine.mac == clean_mac, DeployLogLine.run == run)
    ).one()
    if written > DEPLOY_LOG_MAX_LINES:
        return
    if written == DEPLOY_LOG_MAX_LINES:
        line = _stamp(f"journal tronque : plus de {DEPLOY_LOG_MAX_LINES} lignes "
                      f"pour ce deploiement")
    session.add(DeployLogLine(mac=clean_mac, run=run, line=line))


@app.post("/machines/{mac}/log")
@limiter.limit("120/minute")
async def append_deploy_log(request: Request, mac: str, msg: str):
    """Appelé par WinPE et le firstboot pour envoyer une ligne de log en temps réel."""
    clean_mac = validate_mac(mac)
    line = _stamp(msg)
    with Session(engine) as session:
        _append_log_line(session, clean_mac, _current_run(session, clean_mac), line)
        session.commit()
    await manager.broadcast({"mac": clean_mac, "log_line": line})
    return {"ok": True}


@app.get("/machines/{mac}/logs", dependencies=[Depends(get_current_user)])
def get_deploy_logs(mac: str):
    """Journal du déploiement EN COURS — celui qu'affiche le terminal live."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        lines = session.exec(
            select(DeployLogLine)
            .where(DeployLogLine.mac == clean_mac,
                   DeployLogLine.run == _current_run(session, clean_mac))
            .order_by(DeployLogLine.id)
        ).all()
        return {"logs": [entry.line for entry in lines]}


@app.get("/machines/{mac}/logs.txt", dependencies=[Depends(get_current_user)])
def download_deploy_logs(mac: str):
    """Journal complet en texte brut, TOUS déploiements confondus.

    C'est la réponse à la demande d'origine : récupérer la console de déploiement
    dans un .txt, la fenêtre WinPE disparaissant avec le reboot de la machine. On
    sert l'historique entier et pas seulement le déploiement courant — sur une
    machine qu'on a dû reprendre plusieurs fois, c'est la comparaison entre les
    tentatives qui a de la valeur.
    """
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        lines = session.exec(
            select(DeployLogLine)
            .where(DeployLogLine.mac == clean_mac)
            .order_by(DeployLogLine.run, DeployLogLine.id)
        ).all()

    hostname = machine.hostname if machine else clean_mac
    body, run = [f"# OSIRIS — journal de déploiement de {hostname} ({clean_mac})"], None
    for entry in lines:
        if entry.run != run:
            run = entry.run
            body.append(f"\n--- Déploiement n°{run} — {entry.timestamp:%Y-%m-%d %H:%M:%S} UTC ---")
        body.append(entry.line)
    if not lines:
        body.append("\n(aucune ligne enregistrée)")

    return Response(
        content="\n".join(body) + "\n",
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="osiris-{hostname}-{clean_mac}.txt"'},
    )


def _ip_to_mac(ip: str) -> Optional[str]:
    """Résout une IP en MAC via les leases dnsmasq."""
    leases_file = "/var/lib/misc/dnsmasq.leases"
    try:
        with open(leases_file) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3 and parts[2] == ip:
                    return parts[1].replace(":", "").replace("-", "").lower()
    except FileNotFoundError:
        pass
    return None


def _mac_from_serial(serial: str) -> Optional[str]:
    """Résout un numéro de série SMBIOS en MAC de la machine enregistrée."""
    clean = (serial or "").strip()
    if not clean:
        return None
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.hw_serial == clean)).first()
    return machine.mac if machine else None


def _mac_from_wire_mac(wire_mac: Optional[str]) -> Optional[str]:
    """Résout la MAC vue sur le réseau en MAC CANONIQUE de la machine enregistrée.

    La MAC vue par le DHCP est celle de l'adaptateur USB-Ethernet quand il y en a un,
    et celle du PC sinon. On cherche donc d'abord dans `deploy_mac` (l'adaptateur
    explicitement déclaré pour ce déploiement, donc l'indication la plus précise),
    puis dans `mac` (déploiement sans adaptateur : la MAC vue EST celle du PC).

    Renvoie toujours `machine.mac` : c'est cette valeur qui est gravée dans les scripts
    générés et qui sert de clé à tous les endpoints /machines/{mac}/... . Le reste de
    la chaîne n'a donc jamais à connaître l'existence du dongle.
    """
    if not wire_mac:
        return None
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.deploy_mac == wire_mac)).first()
        if not machine:
            machine = session.exec(select(Machine).where(Machine.mac == wire_mac)).first()
    return machine.mac if machine else None


@app.get("/winpe-auto")
def get_winpe_script_auto(request: Request, serial: str = "", sysid: str = ""):
    """Identifie la machine et retourne son script de déploiement.

    Trois voies, dans cet ordre :
      1. le numéro de série SMBIOS remonté par WinPE — identité STABLE, attachée à
         la machine elle-même ;
      2. à défaut, IP source → MAC (baux dnsmasq) → `deploy_mac` : l'adaptateur
         USB-Ethernet explicitement déclaré sur la fiche pour ce déploiement ;
      3. à défaut, cette même MAC comparée à `mac` : déploiement sans adaptateur,
         la MAC vue sur le réseau est directement celle du PC (cas historique).

    Le série prime car la MAC n'identifie plus la machine dès qu'on passe par un
    adaptateur USB-Ethernet : le firmware peut présenter la MAC système (option
    'MAC Address Pass Through') tandis que WinPE présente la MAC gravée de
    l'adaptateur, et un même adaptateur sert à déployer plusieurs machines.
    """
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.client.host
    )
    mac = _mac_from_serial(serial) or _mac_from_wire_mac(_ip_to_mac(client_ip))
    if not mac:
        detail = f"serie {serial!r} inconnue et IP {client_ip} absente des baux DHCP" \
            if serial.strip() else f"IP {client_ip} inconnue dans les leases DHCP"
        return Response(
            content=f"echo [OSIRIS] Machine non identifiee : {detail}\r\npause\r\nexit /b 1",
            media_type="text/plain", status_code=404,
        )
    # Tant qu'un job de capture existe pour cette MAC (quel que soit son statut -
    # waiting, capturing, ou meme failed suite a une tentative interrompue), on
    # reste en mode capture. Ne JAMAIS retomber sur le deploiement normal, qui
    # repartitionnerait le disque de la machine de reference. La seule sortie du
    # mode capture est la suppression explicite du job (bouton dans l'UI).
    # Identifiant matériel : mémorisé dès WinPE, donc disponible pour choisir le
    # pack de pilotes de CE déploiement — pas seulement du suivant.
    if sysid.strip():
        with Session(engine) as session:
            machine = session.exec(select(Machine).where(Machine.mac == mac)).first()
            if machine and machine.hw_sysid != sysid.strip():
                machine.hw_sysid = sysid.strip()[:100]
                session.add(machine)
                session.commit()

    if mac in _capture_jobs:
        return _build_capture_script(mac)
    return _build_winpe_script(mac)


def _build_winpe_script(mac: str) -> Response:
    """Construit le script CMD de déploiement pour une MAC donnée (normalisée)."""
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == mac)).first()
        if not machine:
            return Response(
                content=f"echo [OSIRIS] Machine {mac} inconnue\r\npause\r\nexit /b 1",
                media_type="text/plain", status_code=404,
            )
        # Garde-fou anti-réinstallation. La route /boot en pose déjà un (une machine
        # `deployed` repart sur son disque), mais il ne s'arme QUE si la MAC vue sur le
        # fil correspond à `Machine.mac` — ce que ni un adaptateur USB-Ethernet ni
        # l'option Dell « MAC Address Pass Through » ne garantissent. Dans ce cas WinPE
        # démarre par le repli « un déploiement est en attente » puis identifie CETTE
        # machine-ci par son numéro de série : sans ce test, on lui servirait un script
        # qui repartitionne le disque d'un poste déjà en production.
        # Redéployer reste possible : l'UI repasse explicitement la fiche en `pending`.
        if machine.status == "deployed":
            # 200 volontaire : `curl -sf` de startnet jette le corps d'une réponse >= 400
            # et retomberait sur le script générique « machine non reconnue », message
            # trompeur ici. On veut que l'opérateur lise la vraie raison à l'écran.
            return Response(
                content=(
                    f"echo [OSIRIS] {machine.hostname} est deja deployee - DEPLOIEMENT REFUSE.\r\n"
                    "echo [OSIRIS] Le disque n'a PAS ete modifie.\r\n"
                    "echo [OSIRIS] Pour la reinstaller : bouton Redeployer dans OSIRIS,\r\n"
                    "echo [OSIRIS] qui repasse la fiche en attente, puis redemarrer en PXE.\r\n"
                    "pause\r\nexit /b 1"
                ),
                media_type="text/plain",
            )
        profile = _resolve_profile(session, machine)

    with Session(engine) as img_session:
        win_img = img_session.exec(
            select(OsImage)
            .where(OsImage.os == "windows", OsImage.status == "ready")
            .order_by(OsImage.created_at.desc())
        ).first()

    if not win_img:
        return Response(
            content="echo [OSIRIS] Aucune image Windows disponible\r\npause\r\nexit /b 1",
            media_type="text/plain", status_code=503,
        )

    # Dossier de drivers a injecter (relatif au partage Z:).
    # Par defaut "drivers" = tout le dossier (comportement historique, fallback sur).
    # Si la machine a un pack explicite ET telecharge : injection ciblee de ce seul pack.
    driver_dir = _resolve_driver_dir(machine)

    profile_ctx = _profile_for_template(profile, session)
    locale = profile_ctx["locale"].replace("_", "-")[:5]
    content = jinja_env.get_template("winpe-deploy.cmd.j2").render(
        machine=machine,
        profile=profile_ctx,
        mac=mac,
        osiris_url=OSIRIS_BASE_URL,
        osiris_ip=OSIRIS_IP,
        win_index=profile_ctx["win_index"],
        locale=locale,
        driver_dir=driver_dir,
    )
    return Response(content=content, media_type="text/plain")


def _pack_for_sysid(session: Session, sysid: str) -> Optional[DriverPack]:
    """Pack prêt dont le catalogue revendique cet identifiant matériel.

    Les constructeurs publient un identifiant qui lève l'ambiguïté des noms
    commerciaux : chez Lenovo, un ThinkPad T15 est un Machine Type 20S6/20S7 et
    un T15**g** un 20UR/20US. Le MTM remonté par la machine ("20S6CTO1WW")
    commence par ce code — on compare donc sur le préfixe de 4 caractères.
    """
    sysid = (sysid or "").strip().lower()
    if not sysid:
        return None
    candidates = [sysid]
    if len(sysid) > 4:
        candidates.append(sysid[:4])   # MTM Lenovo -> Machine Type

    packs = session.exec(
        select(DriverPack)
        .where(DriverPack.status == "ready", DriverPack.hw_ids != "")
        .order_by(DriverPack.os_code.desc())   # Windows11 avant Windows10
    ).all()
    for pack in packs:
        ids = {i for i in pack.hw_ids.split(",") if i}
        if ids & set(candidates):
            return pack
    return None


def _pack_for_model_name(session: Session, name: str) -> Optional[DriverPack]:
    """Pack pret dont le nom de modele correspond a celui remonte par la machine.

    Chez Dell et HP, le catalogue publie un CODE comme identifiant materiel (systemID
    "0cf9" chez Dell, SystemId de carte mere chez HP) alors que la machine remonte son
    NOM COMMERCIAL via Win32_ComputerSystemProduct.Name ("Dell Pro 14 Plus PB14250").
    Les deux ne se rencontrent jamais dans `hw_ids`, d'ou ce repli. Chez Lenovo la
    question ne se pose pas : le MTM est deja un identifiant, `_pack_for_sysid` suffit.

    Volontairement STRICT (egalite, ou l'un prefixe de l'autre) la ou /drivers/suggest
    raccourcit le prefixe pour proposer un pack : la, un humain tranche ; ici l'injection
    est silencieuse. Or DISM n'installe que les .inf dont l'identifiant materiel
    correspond, donc un pack "presque bon" ne fait pas de degats, il installe des
    pilotes INCOMPLETS — un peripherique muet qu'on ne decouvre qu'a la livraison.
    Le repli historique (tout le dossier) ne coute lui que du temps. Dans le doute, on
    ne cible donc rien.
    """
    key = normalize_model(name)
    if len(key) < 6:      # trop court pour discriminer quoi que ce soit
        return None
    packs = session.exec(
        select(DriverPack)
        .where(DriverPack.status == "ready", DriverPack.local_path != "",
               DriverPack.model_key != "")
        .order_by(DriverPack.os_code.desc())   # Windows11 avant Windows10
    ).all()
    # L'egalite l'emporte toujours sur un prefixe, quel que soit l'ordre des packs.
    return next((p for p in packs if p.model_key == key), None) or next(
        (p for p in packs
         if p.model_key.startswith(key) or key.startswith(p.model_key)), None)


def _resolve_driver_dir(machine: Machine) -> str:
    """Chemin du dossier de drivers a injecter, relatif au partage SMB (Z:), en
    notation Windows (backslashes). 'drivers' = tout le dossier (fallback historique) ;
    'drivers\\<vendor>\\<key>' = injection ciblee du pack explicite de la machine."""
    with Session(engine) as session:
        pack = (
            session.get(DriverPack, machine.driver_pack_id)
            if machine.driver_pack_id
            # Aucun pack choisi a la main : plutot que de deverser les ~36 GB du
            # dossier entier, on tente d'abord l'identifiant materiel remonte par
            # WinPE, puis son nom commercial — c'est ce que vaut `hw_sysid` chez
            # Dell et HP. `hw_model` en dernier : il n'est renseigne qu'au firstboot,
            # donc absent du tout premier deploiement.
            else (_pack_for_sysid(session, machine.hw_sysid)
                  or _pack_for_model_name(session, machine.hw_sysid)
                  or _pack_for_model_name(session, machine.hw_model))
        )
    if not pack or pack.status != "ready" or not pack.local_path:
        return "drivers"
    share = WIN_SHARE_PATH.rstrip("/")
    if not pack.local_path.startswith(share):
        return "drivers"
    rel = pack.local_path[len(share):].lstrip("/")
    return rel.replace("/", "\\") or "drivers"


@app.get("/winpe-script/{mac}")
def get_winpe_script(mac: str):
    """Script CMD retourné à WinPE pour déployer Windows sur la machine."""
    return _build_winpe_script(validate_mac(mac))


def _build_capture_script(mac: str) -> Response:
    """Script de capture automatique retourné à WinPE quand la machine est en mode capture."""
    job = _capture_jobs.get(mac, {})
    wim_name = job.get("wim_name", "golden.wim")
    _capture_jobs[mac]["status"] = "capturing"
    content = jinja_env.get_template("winpe-capture.cmd.j2").render(
        mac=mac,
        wim_name=wim_name,
        osiris_ip=OSIRIS_IP,
    )
    return Response(content=content, media_type="text/plain")


# ── Navigateur WIM ────────────────────────────────────────────────────────────

@app.get("/wims", dependencies=[Depends(get_current_user)])
def list_wims():
    """Liste les fichiers .wim disponibles sur le partage Windows."""
    import glob
    wim_dir = WIN_SHARE_PATH
    results = []
    for path in sorted(glob.glob(f"{wim_dir}/*.wim")):
        name = os.path.basename(path)
        if name == "boot.wim":
            continue  # fichier système WinPE, pas une image déployable
        try:
            stat = os.stat(path)
            results.append({
                "name": name,
                "size_mb": round(stat.st_size / 1_048_576),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "is_golden": name != "install.wim",
            })
        except OSError:
            pass
    return results


# ── Import CSV machines ────────────────────────────────────────────────────────

@app.get("/machines/export", dependencies=[Depends(get_current_user)])
def export_machines():
    """Exporte toutes les machines en CSV (UTF-8-BOM pour compatibilite Excel)."""
    import csv, io
    with Session(engine) as session:
        machines = session.exec(select(Machine)).all()
        profiles = {p.id: p.name for p in session.exec(select(Profile)).all()}
        orgs     = {o.id: o.name for o in session.exec(select(Organization)).all()}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["mac", "hostname", "client", "os", "status", "organisation", "profil", "modele", "ram_go", "numero_serie", "notes", "deploye_le"])
    for m in machines:
        deployed = m.deployed_at.strftime("%d/%m/%Y %H:%M") if m.deployed_at else ""
        writer.writerow([
            m.mac, m.hostname, m.client, m.os, m.status,
            orgs.get(m.organization_id, ""), profiles.get(m.profile_id, ""),
            m.hw_model, m.hw_ram_gb or "", m.hw_serial, m.notes, deployed,
        ])
    bom = "﻿"
    return Response(content=bom + out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=osiris-machines.csv"})


@app.post("/machines/import", dependencies=[Depends(require_admin)])
async def import_machines(request: Request, current_user: User = Depends(require_admin)):
    """Importe des machines depuis un CSV (mac,hostname,client,os,profile_name).
    Ligne d'en-tête obligatoire. Les machines existantes sont ignorées."""
    import csv, io
    body = await request.body()
    text = body.decode("utf-8-sig").strip()  # utf-8-sig gère le BOM Excel
    reader = csv.DictReader(io.StringIO(text))
    created, skipped, errors = 0, 0, []
    with Session(engine) as session:
        profiles = {p.name.lower(): p for p in session.exec(select(Profile)).all()}
        for i, row in enumerate(reader, start=2):
            try:
                raw_mac  = (row.get("mac") or "").strip()
                hostname = (row.get("hostname") or "").strip()
                client   = (row.get("client") or "").strip()
                os_name  = (row.get("os") or "ubuntu").strip().lower()
                profile_name = (row.get("profile_name") or "").strip()
                if not raw_mac or not hostname or not client:
                    errors.append(f"Ligne {i} : champs obligatoires manquants")
                    continue
                clean_mac = validate_mac(raw_mac)
                if session.exec(select(Machine).where(Machine.mac == clean_mac)).first():
                    skipped += 1
                    continue
                if os_name not in ("ubuntu", "windows", "debian"):
                    os_name = "ubuntu"
                profile = profiles.get(profile_name.lower()) if profile_name else None
                machine = Machine(
                    mac=clean_mac, hostname=hostname, client=client, os=os_name,
                    profile_id=profile.id if profile else None,
                )
                session.add(machine)
                created += 1
            except HTTPException as e:
                errors.append(f"Ligne {i} : {e.detail}")
        session.commit()
    return {"created": created, "skipped": skipped, "errors": errors}


# ── Capture d'image golden ─────────────────────────────────────────────────────

@app.post("/capture/register", dependencies=[Depends(require_admin)])
def register_capture(mac: str, wim_name: str):
    """Enregistre une MAC en mode capture. Au prochain boot WinPE elle recevra le script de capture."""
    clean_mac = validate_mac(mac)
    if not wim_name.endswith(".wim"):
        wim_name = wim_name + ".wim"
    _capture_jobs[clean_mac] = {
        "mac": clean_mac,
        "wim_name": wim_name,
        "status": "waiting",
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    # Passe la machine en pending pour que le boot route la laisse accéder à WinPE
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if machine and machine.status == "deployed":
            _open_new_deploy_run(machine)
            session.add(machine)
            session.commit()
    return {"mac": clean_mac, "wim_name": wim_name, "status": "waiting"}


@app.get("/capture", dependencies=[Depends(require_admin)])
def list_captures():
    """Liste les jobs de capture en cours."""
    return {"jobs": list(_capture_jobs.values())}


@app.post("/capture/{mac}/done")
async def capture_done(mac: str, success: bool = True):
    """Appelé par le script WinPE à la fin de la capture."""
    clean_mac = validate_mac(mac)
    if clean_mac in _capture_jobs:
        _capture_jobs[clean_mac]["status"] = "done" if success else "failed"
        _capture_jobs[clean_mac]["finished_at"] = datetime.now(timezone.utc).isoformat()
    await manager.broadcast({"type": "capture_done", "mac": clean_mac, "success": success})
    return {"ok": True}


@app.delete("/capture/{mac}", dependencies=[Depends(require_admin)])
def delete_capture(mac: str):
    """Supprime un job de capture (terminé ou annulé)."""
    clean_mac = validate_mac(mac)
    _capture_jobs.pop(clean_mac, None)
    return {"ok": True}


# ── Drivers constructeurs ──────────────────────────────────────────────────────

@app.get("/drivers", dependencies=[Depends(get_current_user)])
def list_driver_packs(vendor: Optional[str] = None, os_code: Optional[str] = None):
    """Liste les packs de drivers connus (après sync catalogue)."""
    with Session(engine) as session:
        query = select(DriverPack)
        if vendor:
            query = query.where(DriverPack.vendor == vendor.lower())
        if os_code:
            query = query.where(DriverPack.os_code == os_code)
        packs = session.exec(query.order_by(DriverPack.vendor, DriverPack.model)).all()
        return [
            {
                "id": p.id, "vendor": p.vendor, "model": p.model,
                "os_code": p.os_code, "size_mb": p.size_mb,
                "status": p.status, "local_path": p.local_path,
                "error": p.error, "hw_ids": p.hw_ids,
                "download_url": p.download_url,
                "catalog_updated": p.catalog_updated.isoformat(),
            }
            for p in packs
        ]


@app.post("/drivers/sync/dell", status_code=202)
async def sync_dell(current_user: User = Depends(require_admin)):
    await arq_pool.enqueue_job("sync_dell_catalog")
    return {"detail": "Synchronisation catalogue Dell lancée"}


@app.post("/drivers/sync/hp", status_code=202)
async def sync_hp(current_user: User = Depends(require_admin)):
    await arq_pool.enqueue_job("sync_hp_catalog")
    return {"detail": "Synchronisation catalogue HP lancée"}


@app.post("/drivers/sync/lenovo", status_code=202)
async def sync_lenovo(current_user: User = Depends(require_admin)):
    await arq_pool.enqueue_job("sync_lenovo_catalog")
    return {"detail": "Synchronisation catalogue Lenovo lancée"}


@app.post("/drivers/{pack_id}/download", status_code=202)
async def download_pack(pack_id: int, current_user: User = Depends(require_admin)):
    """
    Lance le téléchargement d'un pack de drivers spécifique en tâche de fond.
    Durée : 5-30 min selon la taille (300 MB à 3 GB) et la bande passante.
    Le pack est extrait dans /srv/data/windows/drivers/<vendor>/<model_key>/
    et sera automatiquement injecté par WinPE lors du prochain déploiement.
    """
    with Session(engine) as session:
        pack = session.get(DriverPack, pack_id)
        if not pack:
            raise HTTPException(404, "Pack introuvable")
        if pack.status == "downloading":
            raise HTTPException(409, "Ce pack est déjà en cours de téléchargement")
    await arq_pool.enqueue_job("download_driver_pack", pack_id)
    return {"detail": f"Téléchargement lancé pour le pack #{pack_id}"}


@app.get("/drivers/suggest")
def suggest_driver(vendor: str, model: str, sysid: str = ""):
    """
    Retourne le meilleur pack de drivers pour un couple vendeur+modèle.
    Appelé par osiris-firstboot.ps1 avec les infos matériel détectées par Windows.
    Préfère Windows 11 à Windows 10, et les packs déjà téléchargés (ready).

    `sysid` (identifiant matériel constructeur) prime sur le nom quand il est
    fourni : c'est le seul critère qui distingue un ThinkPad T15 d'un T15g.
    """
    key = normalize_model(model)
    with Session(engine) as session:
        exact = _pack_for_sysid(session, sysid)
        if exact:
            return {
                "id": exact.id, "vendor": exact.vendor, "model": exact.model,
                "os_code": exact.os_code, "size_mb": exact.size_mb,
                "status": exact.status, "download_url": exact.download_url,
                "local_path": exact.local_path, "matched_on": "hw_id",
            }
        # Stratégie de recherche bidirectionnelle :
        # 1. catalog_key.startswith(query)  → "optiplex7090tower" pour query "optiplex7090"
        # 2. query.startswith(catalog_key)  → "optiplex7090" pour query "optiplex7090tower"
        # On essaie du plus précis au plus large (on raccourcit le préfixe si pas de résultat).
        results = []
        # On ne dégrade le préfixe que de 4 caractères max pour éviter les faux positifs.
        # ex: "optiplex7090" → essaie jusqu'à "optiplex70" (4 de moins) mais pas "opti".
        min_prefix = max(6, len(key) - 4)
        for prefix_len in range(len(key), min_prefix - 1, -1):
            prefix = key[:prefix_len]
            results = session.exec(
                select(DriverPack)
                .where(
                    DriverPack.vendor == vendor.lower(),
                    DriverPack.model_key.startswith(prefix),
                )
                .order_by(
                    DriverPack.os_code.desc(),   # Windows11 avant Windows10
                    DriverPack.status.desc(),     # "ready" avant "available"
                )
            ).all()
            if results:
                break

        if not results:
            raise HTTPException(404, f"Aucun driver pack pour {vendor} {model!r}")

        p = results[0]
        return {
            "id": p.id, "vendor": p.vendor, "model": p.model,
            "os_code": p.os_code, "size_mb": p.size_mb,
            "status": p.status, "download_url": p.download_url,
            "local_path": p.local_path, "matched_on": "model_name",
        }


import wakeonlan

_honeypot_log = logging.getLogger("osiris.honeypot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class BatchStatusBody(SQLModel):
    macs: list[str]
    status: str = "pending"


@app.post("/machines/batch-status")
async def batch_status(body: BatchStatusBody, current_user: User = Depends(get_current_user)):
    """Passe une liste de machines au statut donné (ex: pending pour un redéploiement en lot)."""
    if body.status not in ("pending", "deploying", "deployed", "failed"):
        raise HTTPException(status_code=400, detail="Statut invalide")
    updated = []
    with Session(engine) as session:
        for raw_mac in body.macs:
            try:
                clean_mac = validate_mac(raw_mac)
            except HTTPException:
                continue
            machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
            if machine:
                if body.status == "pending":
                    _open_new_deploy_run(machine)
                else:
                    machine.status = body.status
                _record_deploy_event(session, machine, body.status)
                session.add(machine)
                updated.append(clean_mac)
        if updated:
            _log(session, current_user, "batch_status", details={"macs": updated, "status": body.status})
        session.commit()
    for mac in updated:
        await manager.broadcast({"type": "status", "mac": mac, "status": body.status})
    return {"updated": updated}


@app.post("/machines/{mac}/wol", dependencies=[Depends(get_current_user)])
@limiter.limit("10/minute")
def wake_on_lan(request: Request, mac: str):
    """Envoie un magic packet WOL à la machine (doit être éteinte mais connectée au réseau)."""
    clean_mac = validate_mac(mac)
    formatted = ":".join(clean_mac[i:i+2] for i in range(0, 12, 2))
    wakeonlan.send_magic_packet(formatted, ip_address="10.0.0.255", port=9)
    return {"detail": f"Magic packet envoyé à {formatted}"}


_HONEYPOT_ART = """\
::  ====================================================================
::                    STOP ! ATTENTION HACKERMAN !
::  ====================================================================
::
::       .---.
::      /     \\       Tu es fier de toi ? Tu as sniffé le réseau
::      \\.---./       et fouillé dans nos partages SMB ?
::       |o_o|
::       |:_/|        Sache que ce compte 'osiris_technicien' :
::      //   \\\\       1. Est restreint en LECTURE SEULE.
::     (|     |)      2. N'a accès qu'à des fichiers ISO publics.
::    /'\\\\_ _/`\\\\     3. Ne te permettra JAMAIS de pivoter sur l'infra.
::    \\___)=(___)
::
::  Bref, tu as perdu ton temps. Bisous de l'équipe OSIRIS. 😎
::  ====================================================================
"""


@app.get("/admin-backup")
@app.post("/admin-backup")
@app.get("/admin-credentials")
@app.post("/admin-credentials")
@app.get("/.env")
@app.get("/config/database")
@limiter.limit("5/minute")
async def honeypot(request: Request):
    ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.client.host
    )
    _honeypot_log.warning(
        "HONEYPOT HIT — method=%s path=%s ip=%s ua=%s",
        request.method, request.url.path, ip,
        request.headers.get("User-Agent", "—"),
    )
    body = (
        _HONEYPOT_ART
        + f":: IP enregistrée : {ip}\n"
        + ":: Cadeau de consolation : https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
    )
    return Response(content=body, media_type="text/plain; charset=utf-8", status_code=418)


# ── Hyperviseurs (Proxmox) ────────────────────────────────────────────────────

class HypervisorCreate(SQLModel):
    name: str
    type: str = "proxmox"
    url: str
    token_id: str = ""
    token_secret: str = ""
    tls_verify: bool = False
    snippets_storage: str = ""
    callback_url: str = ""
    organization_id: Optional[int] = None

class HypervisorPatch(SQLModel):
    name: Optional[str] = None
    url: Optional[str] = None
    token_id: Optional[str] = None
    token_secret: Optional[str] = None
    type: Optional[str] = None
    tls_verify: Optional[bool] = None
    snippets_storage: Optional[str] = None
    callback_url: Optional[str] = None
    organization_id: Optional[int] = None


def _hypervisor_dict(h: Hypervisor) -> dict:
    return {
        "id": h.id,
        "name": h.name,
        "type": h.type,
        "url": h.url,
        "token_id": h.token_id,
        "token_secret": "***" if h.token_secret else "",
        "tls_verify": h.tls_verify,
        "snippets_storage": h.snippets_storage or "",
        "callback_url": h.callback_url or "",
        "organization_id": h.organization_id,
        "created_at": h.created_at.isoformat(),
    }


async def _proxmox_request(h: Hypervisor, method: str, path: str, data: dict | None = None) -> dict:
    """Appel HTTP sur l'API Proxmox. Lève HTTPException si échec."""
    import aiohttp
    secret = decrypt(h.token_secret or "")
    if not secret:
        raise HTTPException(status_code=502, detail="Token Proxmox non déchiffrable - vérifier FERNET_KEY ou reconfigurer le secret")
    headers = {"Authorization": f"PVEAPIToken={h.token_id}={secret}"}
    url = h.url.rstrip("/") + path
    connector = aiohttp.TCPConnector(ssl=False) if not h.tls_verify else None
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            req = getattr(session, method.lower())
            kwargs: dict = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=30)}
            if data is not None:
                kwargs["json"] = data
            async with req(url, **kwargs) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise HTTPException(status_code=502, detail=f"Proxmox {resp.status}: {text[:300]}")
                body = await resp.json()
                return body.get("data", body)
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=502, detail=f"Impossible de joindre Proxmox : {e}")


async def _proxmox_get(h: Hypervisor, path: str) -> dict:
    return await _proxmox_request(h, "GET", path)


async def _proxmox_post(h: Hypervisor, path: str, data: dict | None = None) -> dict:
    return await _proxmox_request(h, "POST", path, data)


async def _proxmox_put(h: Hypervisor, path: str, data: dict) -> dict:
    return await _proxmox_request(h, "PUT", path, data)


async def _proxmox_delete(h: Hypervisor, path: str) -> dict:
    return await _proxmox_request(h, "DELETE", path)


async def _proxmox_upload_snippet(h: Hypervisor, node: str, storage: str, filename: str, content: str) -> None:
    """Upload un fichier texte dans le stockage snippets de Proxmox."""
    import aiohttp
    secret = decrypt(h.token_secret or "")
    headers = {"Authorization": f"PVEAPIToken={h.token_id}={secret}"}
    url = h.url.rstrip("/") + f"/api2/json/nodes/{node}/storage/{storage}/upload"
    connector = aiohttp.TCPConnector(ssl=False) if not h.tls_verify else None
    form = aiohttp.FormData()
    form.add_field("content", "snippets")
    form.add_field("filename", filename)
    form.add_field("file", content.encode("utf-8"), filename=filename, content_type="text/yaml")
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url, headers=headers, data=form,
                                    timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise HTTPException(status_code=502, detail=f"Upload snippet Proxmox: {text[:200]}")
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=502, detail=f"Impossible d'uploader le snippet : {e}")


async def _proxmox_wait_task(h: Hypervisor, node: str, upid: str, max_wait: int = 120) -> None:
    """Attend la fin d'une tâche Proxmox (polling toutes les 2 secondes)."""
    import asyncio, urllib.parse
    upid_encoded = urllib.parse.quote(upid, safe="")
    for _ in range(max_wait // 2):
        await asyncio.sleep(2)
        data = await _proxmox_get(h, f"/api2/json/nodes/{node}/tasks/{upid_encoded}/status")
        if data.get("status") == "stopped":
            if data.get("exitstatus") == "OK":
                return
            raise HTTPException(status_code=502, detail=f"Tâche Proxmox échouée : {data.get('exitstatus')}")
    raise HTTPException(status_code=504, detail="Timeout attente tâche Proxmox (clone VM)")


@app.get("/hypervisors", dependencies=[Depends(require_admin)])
def get_hypervisors():
    with Session(engine) as session:
        return [_hypervisor_dict(h) for h in session.exec(select(Hypervisor)).all()]


@app.post("/hypervisors", status_code=201)
def create_hypervisor(body: HypervisorCreate, current_user: User = Depends(require_admin)):
    data = body.model_dump()
    if data.get("token_secret"):
        data["token_secret"] = encrypt(data["token_secret"])
    with Session(engine) as session:
        h = Hypervisor(**data)
        session.add(h)
        _log(session, current_user, "create_hypervisor", details={"name": body.name, "url": body.url})
        session.commit()
        session.refresh(h)
        return _hypervisor_dict(h)


@app.patch("/hypervisors/{hv_id}")
def update_hypervisor(hv_id: int, patch: HypervisorPatch, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        h = session.get(Hypervisor, hv_id)
        if not h:
            raise HTTPException(status_code=404, detail="Hyperviseur introuvable")
        data = patch.model_dump(exclude_unset=True)
        if "token_secret" in data and data["token_secret"]:
            data["token_secret"] = encrypt(data["token_secret"])
        for field, value in data.items():
            setattr(h, field, value)
        session.add(h)
        _log(session, current_user, "update_hypervisor", details={"id": hv_id})
        session.commit()
        session.refresh(h)
        return _hypervisor_dict(h)


@app.delete("/hypervisors/{hv_id}", status_code=204)
def delete_hypervisor(hv_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        h = session.get(Hypervisor, hv_id)
        if not h:
            raise HTTPException(status_code=404, detail="Hyperviseur introuvable")
        _log(session, current_user, "delete_hypervisor", details={"name": h.name})
        session.delete(h)
        session.commit()


# ── Aiguillage par type d'hyperviseur ─────────────────────────────────────────
# `Hypervisor.type` existait depuis le début mais n'était lu NULLE PART : toutes
# les routes appelaient Proxmox en dur. Ce module d'aiguillage est désormais le
# seul endroit où l'on choisit l'implémentation — en ajouter une revient à écrire
# une classe et une entrée dans `_PROVIDERS`.
#
# Le vocabulaire reste celui de Proxmox (« nœud », « stockage »), parce que c'est
# celui de l'UI : côté vSphere, un nœud est un cluster et un stockage un datastore.

class ProxmoxProvider:
    """Hyperviseur Proxmox VE, piloté par jeton d'API."""

    label = "Proxmox VE"

    @staticmethod
    async def test(h: Hypervisor) -> dict:
        version = await _proxmox_get(h, "/api2/json/version")
        return {
            "ok": True,
            "type": h.type,
            "version": version.get("version", "?"),
            "proxmox_version": version.get("version", "?"),   # compat UI
            "nodes": await ProxmoxProvider.list_nodes(h),
        }

    @staticmethod
    async def list_nodes(h: Hypervisor) -> list[dict]:
        nodes = await _proxmox_get(h, "/api2/json/nodes")
        return [
            {
                "node":       n["node"],
                "status":     n.get("status", "unknown"),
                "cpu":        round(n.get("cpu", 0) * 100, 1),
                "maxcpu":     n.get("maxcpu", 0),
                "mem_gb":     round(n.get("mem", 0) / 1073741824, 1),
                "maxmem_gb":  round(n.get("maxmem", 0) / 1073741824, 1),
            }
            for n in nodes
        ]

    @staticmethod
    async def list_storages(h: Hypervisor, node: str) -> list[dict]:
        storages = await _proxmox_get(h, f"/api2/json/nodes/{node}/storage")
        return [
            {
                "storage":   s["storage"],
                "type":      s.get("type", "?"),
                "active":    s.get("active", 0) == 1,
                "avail_gb":  round(s.get("avail", 0) / 1073741824, 1),
                "total_gb":  round(s.get("total", 0) / 1073741824, 1),
                "content":   s.get("content", ""),
            }
            for s in storages
            if "images" in s.get("content", "")  # ceux qui acceptent des disques VM
        ]

    @staticmethod
    async def list_networks(h: Hypervisor, node: str) -> list[dict]:
        networks = await _proxmox_get(h, f"/api2/json/nodes/{node}/network")
        return [
            {
                "iface":    n["iface"],
                "type":     n.get("type", "?"),
                "address":  n.get("address", ""),
                "comments": n.get("comments", ""),
            }
            for n in networks
            if n.get("type") in ("bridge", "bond")
        ]

    @staticmethod
    async def list_templates(h: Hypervisor, node: str) -> list[dict]:
        vms = await _proxmox_get(h, f"/api2/json/nodes/{node}/qemu")
        return [
            {
                "vmid":      int(v["vmid"]),
                "name":      v.get("name", f"VM {v['vmid']}"),
                "status":    v.get("status", "unknown"),
                "cores":     v.get("cpus", 0),
                "maxmem_gb": round(v.get("maxmem", 0) / 1073741824, 1),
            }
            for v in vms
            if v.get("template") == 1
        ]

    @staticmethod
    def generate_mac() -> str:
        """MAC dans la plage « locally administered » (02:…), libre d'usage."""
        return "02" + secrets.token_bytes(5).hex()

    @staticmethod
    async def next_vm_id(h: Hypervisor) -> int:
        data = await _proxmox_get(h, "/api2/json/cluster/nextid")
        return int(data) if isinstance(data, (str, int)) else int(data.get("nextid", 100))

    @staticmethod
    async def provision_vm(h: Hypervisor, body, vm_id: int, mac_colons: str,
                           mac_plain: str, user_data: str = "",
                           render_user_data=None) -> Optional[dict]:
        await _provision_vm(h, body, vm_id, mac_colons, mac_plain, user_data)
        # Proxmox : identifiant et MAC étaient connus d'avance, rien à corriger.
        return None

    @staticmethod
    async def destroy_vm(h: Hypervisor, node: str, vm_id: int) -> None:
        await _destroy_vm_quietly(h, node, vm_id)


_PROVIDERS = {
    "proxmox": ProxmoxProvider,
    "vsphere": vsphere.VSphereProvider,
}


def _provider(h: Hypervisor):
    provider = _PROVIDERS.get((h.type or "proxmox").lower())
    if not provider:
        raise HTTPException(
            status_code=400,
            detail=f"Type d'hyperviseur non supporté : {h.type} "
                   f"(connus : {', '.join(sorted(_PROVIDERS))})",
        )
    return provider


def _get_hypervisor(hv_id: int) -> Hypervisor:
    with Session(engine) as session:
        h = session.get(Hypervisor, hv_id)
        if not h:
            raise HTTPException(status_code=404, detail="Hyperviseur introuvable")
        return h


@app.post("/hypervisors/{hv_id}/test")
async def test_hypervisor(hv_id: int, _: User = Depends(require_admin)):
    """Teste la connexion à l'hyperviseur et retourne sa version + ses nœuds."""
    h = _get_hypervisor(hv_id)
    return await _provider(h).test(h)


@app.get("/hypervisors/{hv_id}/nodes")
async def get_hypervisor_nodes(hv_id: int, _: User = Depends(require_admin)):
    """Nœuds (Proxmox) ou clusters (vSphere) avec leurs ressources, en direct."""
    h = _get_hypervisor(hv_id)
    return await _provider(h).list_nodes(h)


@app.get("/hypervisors/{hv_id}/nodes/{node}/storages")
async def get_node_storages(hv_id: int, node: str, _: User = Depends(require_admin)):
    """Stockages acceptant des disques de VM (pools Proxmox / datastores vSphere)."""
    h = _get_hypervisor(hv_id)
    return await _provider(h).list_storages(h, node)


@app.get("/hypervisors/{hv_id}/nodes/{node}/networks")
async def get_node_networks(hv_id: int, node: str, _: User = Depends(require_admin)):
    """Réseaux disponibles (bridges Proxmox / port groups vSphere)."""
    h = _get_hypervisor(hv_id)
    return await _provider(h).list_networks(h, node)


@app.get("/hypervisors/{hv_id}/nodes/{node}/templates")
async def get_node_templates(hv_id: int, node: str, _: User = Depends(require_admin)):
    """Templates clonables."""
    h = _get_hypervisor(hv_id)
    return await _provider(h).list_templates(h, node)


class VmCreateBody(SQLModel):
    # Identité OSIRIS
    hostname: str
    client: str
    os: str                          # "ubuntu" | "debian" | "windows"
    # Windows uniquement : type d'OS Proxmox. "win11" couvre Server 2022/2025 + Win10/11 ;
    # "win10" pour Server 2016/2019. Sans effet pour Linux.
    win_ostype: str = "win11"
    profile_id: Optional[int] = None
    organization_id: Optional[int] = None
    ou: str = ""
    # Ressources VM
    node: str                        # noeud Proxmox cible
    storage: str                     # pool de stockage (ex: local-lvm)
    bridge: str = "vmbr0"            # bridge réseau
    vcpus: int = 2
    ram_mb: int = 2048               # RAM en Mo
    disk_gb: int = 20                # disque système en Go
    # Second disque, monté sur /data au premier démarrage. 0 = pas de disque de
    # données. Le formulaire propose par défaut la valeur du profil.
    data_disk_gb: int = 0
    # Adressage IP. Vide = DHCP. À renseigner sur les VLAN serveurs, qui n'ont
    # généralement pas de DHCP : sans adresse, la VM démarre et ne rappelle
    # jamais OSIRIS.
    ip_cidr: str = ""        # ex. "203.0.113.60/24"
    gateway: str = ""
    dns_servers: str = ""    # séparés par des virgules
    # Mode de boot
    boot_mode: str = "pxe"          # "pxe" | "cloudinit"
    # PXE : ISO a booter (ex: "local:iso/ubuntu-24.04.iso") — optionnel
    iso: str = ""
    # Cloud-init : VMID du template Proxmox a cloner
    cloud_template_id: Optional[int] = None


def _rollback_vm_machine(user: User, body, hv_id: int, vm_id: int,
                         mac: str, exc: Exception) -> None:
    """
    Retire la fiche d'une VM dont la création a échoué, en laissant l'audit.

    Best-effort par construction : on est déjà dans un chemin d'erreur, une
    exception ici masquerait la vraie.
    """
    try:
        with Session(engine) as session:
            machine = session.exec(select(Machine).where(Machine.mac == mac)).first()
            # On ne supprime que SI la fiche est bien celle qu'on vient de créer :
            # une fiche qui pointerait ailleurs appartient à quelqu'un d'autre.
            if machine and machine.proxmox_vm_id == vm_id:
                session.delete(machine)
            _log(session, user, "create_vm_failed", target_mac=mac, details={
                "hostname": body.hostname, "vm_id": vm_id, "node": body.node,
                "hypervisor_id": hv_id, "boot_mode": body.boot_mode,
                "error": str(exc)[:500], "vm_destroyed": True,
            })
            session.commit()
    except Exception:
        _hv_log.exception("Echec du nettoyage de la fiche de la VM %s", vm_id)


async def _destroy_vm_quietly(h: Hypervisor, node: str, vm_id: int) -> None:
    """Détruit une VM après un échec, sans jamais masquer l'erreur d'origine.

    Utilisé pour ne pas laisser de VM à moitié configurée sur l'hyperviseur : ses
    volumes bloqueraient la réutilisation de l'identifiant par `nextid`.
    """
    try:
        await _proxmox_post(h, f"/api2/json/nodes/{node}/qemu/{vm_id}/status/stop")
    except Exception:
        pass   # la VM n'était probablement pas démarrée
    try:
        await _proxmox_request(h, "DELETE", f"/api2/json/nodes/{node}/qemu/{vm_id}?purge=1")
        _hv_log.warning("VM %s détruite après échec de sa configuration", vm_id)
    except Exception as exc:
        # Le nettoyage a échoué : on le signale fort, mais on laisse remonter
        # l'erreur d'origine, qui est celle qui intéresse l'appelant.
        _hv_log.error(
            "VM %s laissée sur l'hyperviseur %s — la supprimer à la main et libérer "
            "ses volumes (« pvesm free <storage>:vm-%s-cloudinit ») : %s",
            vm_id, node, vm_id, str(exc)[:200],
        )


def _resolve_profile_for_vm(body) -> Profile:
    """Profil d'une VM en cours de création : celui demandé, sinon le premier de l'OS."""
    with Session(engine) as session:
        profile = session.get(Profile, body.profile_id) if body.profile_id else None
        if not profile:
            profile = session.exec(select(Profile).where(Profile.os == body.os)).first()
    return profile or Profile(name="_fallback", os=body.os)


def _render_cloud_init_user_data(h: Hypervisor, body, mac_plain: str) -> str:
    """
    User-data cloud-init d'une VM à créer, indépendant de l'hyperviseur.

    Proxmox le dépose en snippet, vSphere l'injecte en `guestinfo` : même
    contenu, deux véhicules. L'URL de rappel est celle de l'hyperviseur quand
    elle est renseignée — une VM d'un autre site ne voit pas forcément OSIRIS
    à la même adresse que le réseau de déploiement.
    """
    profile_obj = _resolve_profile_for_vm(body)
    profile_tpl = _profile_for_template(profile_obj)
    linux_apps = []
    if profile_obj.app_ids:
        with Session(engine) as session:
            ids = [int(i) for i in profile_obj.app_ids.split(",") if i.strip().isdigit()]
            linux_apps = [a for a in session.exec(select(Application)).all()
                          if a.id in ids and a.apt_package]
    osiris_url = (h.callback_url or "").rstrip("/") \
        or os.environ.get("OSIRIS_BASE_URL", "http://osiris:8000")
    return jinja_env.get_template("cloud-init-user-data.j2").render(
        machine={"hostname": body.hostname, "password_hash": "", "mac": mac_plain},
        profile=profile_tpl,
        linux_apps=linux_apps,
        mac=mac_plain,
        osiris_url=osiris_url,
    )


@app.post("/hypervisors/{hv_id}/create-vm", status_code=201)
async def create_vm(hv_id: int, body: VmCreateBody, current_user: User = Depends(require_admin)):
    """
    Crée une VM sur Proxmox via PXE ou cloud-init (clone de template).
    - PXE : crée une VM vierge qui boote sur le réseau OSIRIS.
    - Cloud-init : clone un template existant, injecte le user-data via snippets Proxmox.
    """
    if body.boot_mode not in ("pxe", "cloudinit"):
        raise HTTPException(status_code=400, detail="boot_mode invalide (pxe ou cloudinit)")
    if body.boot_mode == "cloudinit" and not body.cloud_template_id:
        raise HTTPException(status_code=400, detail="cloud_template_id requis pour le mode cloud-init")
    # Windows = PXE uniquement : le chemin cloud-init est spécifique Linux (user-data, apt).
    # Le déploiement Windows passe par WinPE (booté en PXE), piloté par MAC comme un poste physique.
    if body.os == "windows" and body.boot_mode != "pxe":
        raise HTTPException(status_code=400, detail="Windows nécessite le mode PXE (cloud-init est Linux uniquement)")

    with Session(engine) as session:
        h = session.get(Hypervisor, hv_id)
        if not h:
            raise HTTPException(status_code=404, detail="Hyperviseur introuvable")

    provider = _provider(h)

    # Identifiant de VM libre côté hyperviseur (0 sur vSphere, qui l'attribue lui-même)
    vm_id = await provider.next_vm_id(h)

    # MAC générée par le provider : chaque hyperviseur impose sa plage. VMware
    # n'accepte une MAC imposée que dans 00:50:56:00:00:00–00:50:56:3F:FF:FF ;
    # une MAC « locally administered » y serait refusée.
    mac_plain  = provider.generate_mac()
    mac_colons = ":".join(mac_plain[i:i + 2] for i in range(0, 12, 2))

    # Le user-data cloud-init est rendu ici, pour les deux hyperviseurs : Proxmox
    # le dépose en snippet, vSphere l'injecte en guestinfo. Même contenu.
    user_data = ""
    if body.boot_mode == "cloudinit":
        user_data = _render_cloud_init_user_data(h, body, mac_plain)

    # ── Fiche + audit AVANT le moindre appel à l'hyperviseur ───────────────────
    # Ils étaient écrits après le démarrage de la VM. Tout ce qui interrompait la
    # requête entre les deux laissait une VM qui tourne sans AUCUNE trace : ni
    # dans l'inventaire, ni dans l'audit — donc invisible et non redéployable.
    # Pas seulement une erreur de base : surtout l'annulation de la requête quand
    # le client raccroche pendant un clone qui dure des minutes (`CancelledError`
    # n'est même pas une `Exception`, aucun `except` métier ne la rattrape).
    # C'est ce qui est arrivé à la VM 101 le 2026-07-29 à 16:31.
    # En inversant l'ordre, le pire résidu devient une fiche sans VM : visible
    # dans l'UI et supprimable en un clic. On préfère nettement cette erreur-là.
    try:
        with Session(engine) as session:
            machine = Machine(
                mac=mac_plain,
                hostname=body.hostname,
                client=body.client,
                os=body.os,
                ou=body.ou,
                status="pending",
                profile_id=body.profile_id,
                organization_id=body.organization_id,
                hypervisor_id=hv_id,
                proxmox_vm_id=vm_id,
                proxmox_node=body.node,
                ip_cidr=body.ip_cidr.strip(),
                gateway=body.gateway.strip(),
                dns_servers=body.dns_servers.strip(),
            )
            session.add(machine)
            _log(session, current_user, "create_vm", target_mac=mac_plain, details={
                "hostname": body.hostname, "vm_id": vm_id, "boot_mode": body.boot_mode,
                "node": body.node, "hypervisor_id": hv_id,
            })
            session.commit()
            session.refresh(machine)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Impossible d'enregistrer la machine dans OSIRIS ({exc}) — "
                   f"aucune VM n'a été créée sur l'hyperviseur.",
        )

    try:
        created = await provider.provision_vm(
            h, body, vm_id, mac_colons, mac_plain, user_data,
            lambda mac: _render_cloud_init_user_data(h, body, mac),
        )
        if created:
            # vSphere décide de l'identifiant ET de la MAC au moment du clone.
            # La fiche existe déjà (écrite avant tout appel à l'hyperviseur) :
            # on la corrige avec ce que la plateforme a réellement attribué,
            # sans quoi la machine s'annoncerait sous une MAC inconnue d'OSIRIS.
            vm_id = created.get("vm_id") or vm_id
            real_mac = created.get("mac") or mac_plain
            with Session(engine) as session:
                m = session.exec(select(Machine).where(Machine.mac == mac_plain)).first()
                if m:
                    m.proxmox_vm_id = vm_id
                    if real_mac != mac_plain:
                        m.mac = real_mac
                        _log(session, current_user, "update_machine", target_mac=real_mac,
                             details={"mac_provisoire": mac_plain,
                                      "mac_attribuee_par_hyperviseur": real_mac})
                    session.add(m)
                    session.commit()
            mac_plain = real_mac
    except Exception as exc:
        # Échec côté hyperviseur : on détruit ce qui a pu être créé et on retire
        # la fiche, mais la ligne d'audit `create_vm_failed` reste.
        await provider.destroy_vm(h, body.node, vm_id)
        _rollback_vm_machine(current_user, body, hv_id, vm_id, mac_plain, exc)
        raise

    return {
        "mac": mac_plain,
        "vm_id": vm_id,
        "node": body.node,
        "hostname": body.hostname,
        "boot_mode": body.boot_mode,
        "status": "pending",
    }


async def _provision_vm(h: Hypervisor, body, vm_id: int, mac_colons: str,
                        mac_plain: str, user_data: str = "") -> None:
    """Crée et démarre la VM côté Proxmox (PXE : VM vierge ; cloud-init : clone de template)."""
    import urllib.parse

    if body.boot_mode == "pxe":
        # ── Chemin PXE ──────────────────────────────────────────────────────────
        if body.os == "windows":
            # VM Windows : matériel compatible pilotes *inbox* (aucune injection virtio).
            #  - SATA (sata0) + NIC e1000  => WinPE voit disque et réseau sans driver.
            #  - OVMF/q35 + efidisk0       => le déploiement WinPE fait du GPT/UEFI
            #    (bcdboot /f UEFI) : le firmware DOIT être UEFI, pas SeaBIOS.
            #  - SecureBoot désactivé (pre-enrolled-keys=0) pour ne pas bloquer le boot PXE/WinPE.
            #    TPM non nécessaire : DISM applique le WIM sans passer par setup.exe.
            vm_config: dict = {
                "vmid": vm_id, "name": body.hostname,
                "cores": body.vcpus, "sockets": 1, "memory": body.ram_mb,
                "net0": f"e1000={mac_colons},bridge={body.bridge}",
                "ostype": body.win_ostype or "win11",
                "bios": "ovmf", "machine": "q35",
                "efidisk0": f"{body.storage}:1,efitype=4m,pre-enrolled-keys=0,format=qcow2",
                "agent": "enabled=1", "onboot": 1,
                "boot": "order=net0;sata0",
                "sata0": f"{body.storage}:{body.disk_gb},format=qcow2",
            }
        else:
            vm_config = {
                "vmid": vm_id, "name": body.hostname,
                "cores": body.vcpus, "sockets": 1, "memory": body.ram_mb,
                "net0": f"virtio={mac_colons},bridge={body.bridge}",
                "ostype": "l26", "agent": "enabled=1", "onboot": 1,
                "boot": "order=net0;scsi0;ide2",
                "scsihw": "virtio-scsi-pci",
                "scsi0": f"{body.storage}:{body.disk_gb},format=qcow2",
            }
        if body.data_disk_gb:
            # Disque de donnees, laisse VIERGE : c'est le premier demarrage qui le
            # formate et le monte sur /data. Sur le materiel Windows (SATA), il
            # prend la place suivante sur le meme controleur.
            if body.os == "windows":
                vm_config["sata1"] = f"{body.storage}:{body.data_disk_gb},format=qcow2"
            else:
                vm_config["scsi1"] = f"{body.storage}:{body.data_disk_gb},format=qcow2"
        if body.iso:
            vm_config["ide2"] = f"{body.iso},media=cdrom"
        await _proxmox_post(h, f"/api2/json/nodes/{body.node}/qemu", vm_config)
        await _proxmox_post(h, f"/api2/json/nodes/{body.node}/qemu/{vm_id}/status/start")

    else:
        # ── Chemin cloud-init (clone de template) ────────────────────────────────
        clone_result = await _proxmox_post(h, f"/api2/json/nodes/{body.node}/qemu/{body.cloud_template_id}/clone", {
            "newid":   vm_id,
            "name":    body.hostname,
            "full":    1,            # clone complet (indépendant du template)
            "storage": body.storage,
        })
        # Attendre la fin du clone (tâche asynchrone Proxmox)
        upid = clone_result if isinstance(clone_result, str) else str(clone_result)
        await _proxmox_wait_task(h, body.node, upid)

        # Le clone EXISTE desormais sur l'hyperviseur. Toute erreur au-dela doit le
        # detruire : sinon on laisse une VM fantome et ses volumes derriere soi, et
        # `nextid` reattribue le meme identifiant a la tentative suivante — qui
        # echoue alors sur « disk already exists ». Constate 3 fois le 2026-07-29.
        # La destruction est faite par l'appelant, qui couvre AUSSI l'echec du
        # clone lui-meme et retire la fiche au passage.
        # Le user-data est rendu par l'appelant (commun aux deux hyperviseurs).
        # Le profil reste nécessaire ici pour le repli sans snippets.
        profile_tpl = _profile_for_template(_resolve_profile_for_vm(body))

        # Configurer le clone : MAC, cloud-init drive, redimensionner le disque
        cloud_config: dict = {
            "net0":   f"virtio={mac_colons},bridge={body.bridge}",
            "cores":  body.vcpus,
            "memory": body.ram_mb,
            "agent":  "enabled=1",
            "onboot": 1,
            "boot":   "order=scsi0",
        }
        # Le lecteur cloud-init n'est ajoute QUE s'il manque. Un template qui a deja
        # le sien voit son image recopiee par le clone ; en redemander une au meme nom
        # fait echouer Proxmox sur « rbd create 'vm-<id>-cloudinit' : File exists »,
        # et le clone est detruit dans la foulee. Un template porte son lecteur des
        # qu'il a ete regenere une fois (un simple `qm set --ipconfig0` materialise
        # l'image), donc supposer qu'il n'en a pas ne tient pas.
        if not _a_un_lecteur_cloudinit(await _proxmox_get(
            h, f"/api2/json/nodes/{body.node}/qemu/{vm_id}/config"
        )):
            cloud_config["ide2"] = f"{body.storage}:cloudinit"

        if body.data_disk_gb:
            # Le template n'a qu'un disque : celui-ci s'ajoute, vierge, et sera
            # formate puis monte sur /data au premier demarrage.
            cloud_config["scsi1"] = f"{body.storage}:{body.data_disk_gb}"

        # Adressage : cloud-init applique `ipconfig0` au premier demarrage.
        # Sans lui, Proxmox laisse la carte en DHCP.
        if body.ip_cidr:
            ipconfig = f"ip={body.ip_cidr}"
            if body.gateway:
                ipconfig += f",gw={body.gateway}"
            cloud_config["ipconfig0"] = ipconfig
            if body.dns_servers:
                cloud_config["nameserver"] = body.dns_servers.replace(",", " ")
        else:
            cloud_config["ipconfig0"] = "ip=dhcp"

        if h.snippets_storage:
            snippet_name = f"osiris-{vm_id}-user-data.yaml"
            await _proxmox_upload_snippet(h, body.node, h.snippets_storage, snippet_name, user_data)
            cloud_config["cicustom"] = f"user={h.snippets_storage}:snippets/{snippet_name}"
        else:
            # Fallback : paramètres cloud-init basiques sans cicustom
            cloud_config["ciuser"] = profile_tpl.get("default_user", "osiris")
            ssh_keys = profile_tpl.get("ssh_authorized_keys", "")
            if ssh_keys:
                cloud_config["sshkeys"] = urllib.parse.quote(ssh_keys.strip(), safe="")

        await _proxmox_put(h, f"/api2/json/nodes/{body.node}/qemu/{vm_id}/config", cloud_config)

        # Redimensionner le disque si nécessaire.
        # ⚠️ resize est un PUT, PAS un POST : en POST, Proxmox répond
        # « Method not implemented » (501) et toute création cloud-init échoue.
        await _proxmox_request(h, "PUT", f"/api2/json/nodes/{body.node}/qemu/{vm_id}/resize", {
            "disk": "scsi0", "size": f"{body.disk_gb}G",
        })

        await _proxmox_post(h, f"/api2/json/nodes/{body.node}/qemu/{vm_id}/status/start")



@app.websocket("/ws/machines")
async def ws_machines(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # maintient la connexion ouverte
    except WebSocketDisconnect:
        manager.disconnect(websocket)
