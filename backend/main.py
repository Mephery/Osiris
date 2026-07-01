# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
from typing import Optional
from xml.sax.saxutils import escape
from passlib.hash import sha512_crypt
from fastapi import HTTPException, FastAPI, Request, Response, Depends, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlmodel import SQLModel, Session, select

from arq import create_pool
from arq.connections import RedisSettings
from jinja2 import Environment, FileSystemLoader

import pyotp
import qrcode
from models import ApiKey, Application, AuditLog, DeploymentEvent, DriverPack, DomainConfig, Machine, Organization, OsImage, Profile, User, engine, init_db, normalize_model
from auth import (
    hash_password, verify_password, create_token,
    get_current_user, require_admin
)
from crypto import encrypt, decrypt


# ── Démarrage ──────────────────────────────────────────────────────────────────

arq_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global arq_pool
    init_db()
    _seed_admin()
    _seed_default_profiles()
    _seed_apps()
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    arq_pool = await create_pool(RedisSettings.from_dsn(redis_url))
    yield
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
OSIRIS_IP       = os.environ.get("OSIRIS_IP", "192.168.1.18")
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
_deploy_logs: dict[str, list[str]] = {}

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
    organization_id: Optional[int] = None
    profile_id: Optional[int] = None
    notes: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None

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
    {"name": "Microsoft Office 365", "winget_id": "Microsoft.Office",                     "apt_package": "",                     "category": "office",   "icon": "🏢"},
    {"name": "Adobe Acrobat Reader", "winget_id": "Adobe.Acrobat.Reader.64-bit",          "apt_package": "",                     "category": "tools",    "icon": "📋"},
    {"name": "Audacity",             "winget_id": "Audacity.Audacity",                    "apt_package": "audacity",             "category": "media",    "icon": "🎙️"},
    {"name": "VS Code",              "winget_id": "Microsoft.VisualStudioCode",           "apt_package": "",                     "category": "dev",      "icon": "💻"},
    {"name": "Java OpenJDK 21",      "winget_id": "Eclipse.Temurin.21",                   "apt_package": "openjdk-21-jre",       "category": "tools",    "icon": "☕"},
    {"name": ".NET Runtime 8",       "winget_id": "Microsoft.DotNet.DesktopRuntime.8",    "apt_package": "",                     "category": "tools",    "icon": "⚡"},
    {"name": "Nextcloud Client",     "winget_id": "Nextcloud.Nextcloud",                  "apt_package": "nextcloud-desktop",    "category": "office",   "icon": "☁️"},
    {"name": "NetExplorer",          "winget_id": "NetExplorer.NetExplorer",              "apt_package": "",                     "category": "office",   "icon": "📁"},
    {"name": "Citrix Workspace",     "winget_id": "Citrix.Workspace",                     "apt_package": "",                     "category": "remote",   "icon": "🖥️"},
    {"name": "OpenVPN",              "winget_id": "OpenVPNTechnologies.OpenVPN",          "apt_package": "openvpn",              "category": "security", "icon": "🔑"},
    {"name": "WithSecure",           "winget_id": "WithSecure.ElementsAgent",             "apt_package": "",                     "category": "security", "icon": "🛡️"},
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

@app.get("/organizations", dependencies=[Depends(get_current_user)])
def get_organizations():
    with Session(engine) as session:
        orgs = session.exec(select(Organization)).all()
        return [{"id": o.id, "name": o.name, "slug": o.slug, "webhook_url": o.webhook_url} for o in orgs]


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
        return {"id": org.id, "name": org.name, "slug": org.slug, "webhook_url": org.webhook_url}


@app.patch("/organizations/{org_id}")
async def patch_organization(org_id: int, request: Request, current_user: User = Depends(require_admin)):
    """Met à jour les champs d'une organisation (ex: webhook_url)."""
    data = await request.json()
    with Session(engine) as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation introuvable")
        if "webhook_url" in data:
            org.webhook_url = data["webhook_url"]
        if "name" in data:
            org.name = data["name"]
        session.add(org)
        session.commit()
        session.refresh(org)
        return {"id": org.id, "name": org.name, "slug": org.slug, "webhook_url": org.webhook_url}


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

class DomainConfigPatch(SQLModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    join_user: Optional[str] = None
    join_password: Optional[str] = None
    default_ou: Optional[str] = None

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
                # join_password jamais retourne en clair
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
        )
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return {"id": cfg.id, "name": cfg.name, "domain": cfg.domain, "join_user": cfg.join_user, "default_ou": cfg.default_ou}

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
    }


def _profile_for_template(p: Profile, session: Session | None = None) -> dict:
    """Profil avec secrets déchiffrés — uniquement pour les templates Jinja2, jamais renvoyé au client."""
    # Résolution du domaine AD : DomainConfig en priorité sur les champs inline
    domain = p.domain
    domain_join_user = p.domain_join_user
    domain_join_password = decrypt(p.domain_join_password or "")
    if p.domain_config_id and session:
        dc = session.get(DomainConfig, p.domain_config_id)
        if dc:
            domain = dc.domain
            domain_join_user = dc.join_user
            domain_join_password = decrypt(dc.join_password or "")
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
        "network_drives": json.loads(p.network_drives) if p.network_drives else [],
        "printers": json.loads(p.printers) if p.printers else [],
        "post_script": p.post_script or "",
        "tv_suffix": decrypt(p.tv_suffix or ""),
        "app_ids": p.app_ids or "",
        "domain_config_id": p.domain_config_id,
        "machine_type": p.machine_type or "workstation",
        "ssh_authorized_keys": p.ssh_authorized_keys or "",
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


# ── Applications (winget / apt) ───────────────────────────────────────────────

class ApplicationCreate(SQLModel):
    name: str
    winget_id: str = ""
    apt_package: str = ""
    category: str = "tools"
    icon: str = "📦"


def _app_dict(a: Application) -> dict:
    return {"id": a.id, "name": a.name, "winget_id": a.winget_id,
            "apt_package": a.apt_package, "category": a.category, "icon": a.icon}


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
        "nfs_path": img.nfs_path, "error": img.error,
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
            script += f"kernel {OSIRIS_BASE_URL}/static/wimboot\n"
            script += f"initrd --name bootmgr {OSIRIS_BASE_URL}/static/winpe/bootmgr bootmgr\n"
            script += f"initrd --name BCD {OSIRIS_BASE_URL}/static/winpe/boot/bcd BCD\n"
            script += f"initrd --name boot.sdi {OSIRIS_BASE_URL}/static/winpe/boot/boot.sdi boot.sdi\n"
            script += f"initrd --name boot.wim {OSIRIS_BASE_URL}/static/winpe/sources/boot.wim boot.wim\n"
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


@app.get("/firstboot-ubuntu/{mac}")
def get_ubuntu_firstboot(mac: str):
    """Script bash généré à la volée, exécuté au premier démarrage Ubuntu via systemd oneshot."""
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine inconnue")
        profile = _resolve_profile(session, machine)
        app_id_list = [int(i) for i in (profile.app_ids or "").split(",") if i.strip().isdigit()]
        linux_apps = session.exec(select(Application).where(Application.id.in_(app_id_list), Application.apt_package != "")).all() if app_id_list else []
    profile_ctx = _profile_for_template(profile, session)
    tv_suffix = profile_ctx.get("tv_suffix", "")
    tv_password = f"{machine.hostname.upper()}{tv_suffix}" if tv_suffix else ""
    content = jinja_env.get_template("firstboot-ubuntu.sh.j2").render(
        machine=machine,
        profile=profile_ctx,
        tv_password=tv_password,
        linux_apps=list(linux_apps),
        osiris_url=OSIRIS_BASE_URL,
    )
    return Response(content=content, media_type="text/plain")


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
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine inconnue")
        profile = _resolve_profile(session, machine)
        app_id_list = [int(i) for i in (profile.app_ids or "").split(",") if i.strip().isdigit()]
        linux_apps = session.exec(select(Application).where(Application.id.in_(app_id_list), Application.apt_package != "")).all() if app_id_list else []
    profile_ctx = _profile_for_template(profile, session)
    tv_suffix = profile_ctx.get("tv_suffix", "")
    tv_password = f"{machine.hostname.upper()}{tv_suffix}" if tv_suffix else ""
    content = jinja_env.get_template("firstboot-ubuntu.sh.j2").render(
        machine=machine,
        profile=profile_ctx,
        tv_password=tv_password,
        linux_apps=list(linux_apps),
        osiris_url=OSIRIS_BASE_URL,
    )
    return Response(content=content, media_type="text/plain")


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
        win_apps = session.exec(select(Application).where(Application.id.in_(app_id_list), Application.winget_id != "")).all() if app_id_list else []
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
    )
    return Response(content=content, media_type="text/plain")


# ── CRUD machines ──────────────────────────────────────────────────────────────

@app.post("/machines", status_code=201)
def create_machine(machine: Machine, current_user: User = Depends(get_current_user)):
    clean_mac = validate_mac(machine.mac)
    machine.mac = clean_mac

    plaintext_password = secrets.token_urlsafe(16)
    machine.password_hash = sha512_crypt.using(rounds=100000).hash(plaintext_password)

    with Session(engine) as session:
        if session.exec(select(Machine).where(Machine.mac == clean_mac)).first():
            raise HTTPException(status_code=400, detail="Cette adresse MAC est déjà enregistrée.")
        session.add(machine)
        _log(session, current_user, "create_machine", target_mac=clean_mac,
             details={"hostname": machine.hostname, "client": machine.client, "os": machine.os})
        session.commit()
        session.refresh(machine)

    return {
        "id": machine.id, "mac": machine.mac, "client": machine.client,
        "os": machine.os, "hostname": machine.hostname, "ou": machine.ou,
        "status": machine.status, "organization_id": machine.organization_id,
        "profile_id": machine.profile_id, "password": plaintext_password,
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
                "id": m.id, "mac": m.mac, "client": m.client,
                "os": m.os, "hostname": m.hostname, "ou": m.ou,
                "status": m.status, "organization_id": m.organization_id,
                "profile_id": m.profile_id,
                "deployed_at": m.deployed_at.isoformat() if m.deployed_at else None,
                "hw_serial": m.hw_serial, "hw_model": m.hw_model, "hw_ram_gb": m.hw_ram_gb,
                "notes": m.notes,
                "user_name": m.user_name, "user_email": m.user_email,
                "has_bitlocker": bool(m.bitlocker_key),
                "has_laps": bool(m.laps_password),
            }
            for m in machines
        ]


@app.patch("/machines/{mac}")
def update_machine(mac: str, patch: MachinePatch, current_user: User = Depends(get_current_user)):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        changes = patch.model_dump(exclude_none=True)
        for field, value in changes.items():
            setattr(machine, field, value)
        session.add(machine)
        _log(session, current_user, "update_machine", target_mac=clean_mac, details=changes)
        session.commit()
        session.refresh(machine)
        return {
            "id": machine.id, "mac": machine.mac, "client": machine.client,
            "os": machine.os, "hostname": machine.hostname, "ou": machine.ou,
            "status": machine.status, "organization_id": machine.organization_id,
        }


@app.delete("/machines/{mac}", status_code=204)
def delete_machine(mac: str, current_user: User = Depends(require_admin)):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        _log(session, current_user, "delete_machine", target_mac=clean_mac,
             details={"hostname": machine.hostname, "client": machine.client})
        session.delete(machine)
        session.commit()


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
        machine.status = "pending"
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
def get_audit_logs(limit: int = 200):
    with Session(engine) as session:
        logs = session.exec(
            select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
        ).all()
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
        machine.status = status
        if status == "deployed":
            machine.deployed_at = datetime.now(timezone.utc)
            deployed_at = machine.deployed_at.isoformat()
        if status == "pending":
            _deploy_logs.pop(clean_mac, None)
            _deploy_progress.pop(clean_mac, None)
        _record_deploy_event(session, machine, status)
        session.add(machine)
        # Récupère le webhook de l'org avant le commit pour éviter session expirée
        webhook_url = ""
        if status in ("deployed", "failed") and machine.organization_id:
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


@app.post("/machines/{mac}/log")
@limiter.limit("120/minute")
async def append_deploy_log(request: Request, mac: str, msg: str):
    """Appelé par WinPE pour envoyer une ligne de log en temps réel."""
    clean_mac = validate_mac(mac)
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    _deploy_logs.setdefault(clean_mac, []).append(line)
    await manager.broadcast({"mac": clean_mac, "log_line": line})
    return {"ok": True}


@app.get("/machines/{mac}/logs", dependencies=[Depends(get_current_user)])
def get_deploy_logs(mac: str):
    """Retourne les logs de déploiement en mémoire pour une machine."""
    clean_mac = validate_mac(mac)
    return {"logs": _deploy_logs.get(clean_mac, [])}


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


@app.get("/winpe-auto")
def get_winpe_script_auto(request: Request):
    """Identifie la machine par son IP source (lookup dnsmasq), retourne le script de déploiement."""
    client_ip = (
        request.headers.get("X-Real-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.client.host
    )
    mac = _ip_to_mac(client_ip)
    if not mac:
        return Response(
            content=f"echo [OSIRIS] IP {client_ip} inconnue dans les leases DHCP\r\npause\r\nexit /b 1",
            media_type="text/plain", status_code=404,
        )
    if mac in _capture_jobs and _capture_jobs[mac]["status"] == "waiting":
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
    )
    return Response(content=content, media_type="text/plain")


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
            machine.status = "pending"
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
def suggest_driver(vendor: str, model: str):
    """
    Retourne le meilleur pack de drivers pour un couple vendeur+modèle.
    Appelé par osiris-firstboot.ps1 avec les infos matériel détectées par Windows.
    Préfère Windows 11 à Windows 10, et les packs déjà téléchargés (ready).
    """
    key = normalize_model(model)
    with Session(engine) as session:
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
            "local_path": p.local_path,
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


@app.websocket("/ws/machines")
async def ws_machines(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # maintient la connexion ouverte
    except WebSocketDisconnect:
        manager.disconnect(websocket)
