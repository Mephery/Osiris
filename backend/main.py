import json
import os
import re
import secrets
from datetime import datetime
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

from models import AuditLog, Machine, Organization, OsImage, Profile, User, engine, init_db
from auth import (
    hash_password, verify_password, create_token,
    get_current_user, require_admin
)


# ── Démarrage ──────────────────────────────────────────────────────────────────

arq_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global arq_pool
    init_db()
    _seed_admin()
    _seed_default_profiles()
    arq_pool = await create_pool(RedisSettings())
    yield
    await arq_pool.aclose()

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Config ─────────────────────────────────────────────────────────────────────

OSIRIS_BASE_URL = os.environ.get("OSIRIS_BASE_URL", "http://10.0.0.1:8000")
OSIRIS_IP       = os.environ.get("OSIRIS_IP", "192.168.1.18")
SSH_PUBKEY      = os.environ.get("OSIRIS_SSH_PUBKEY", "").strip()
ADMIN_EMAIL     = os.environ.get("ADMIN_EMAIL", "admin@osiris.local")
ADMIN_PASSWORD  = os.environ.get("ADMIN_PASSWORD", "changeme")

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


jinja_env = Environment(
    loader=FileSystemLoader("templates"),
    trim_blocks=True,    # supprime le saut de ligne après un bloc {% %}
    lstrip_blocks=True,  # supprime les espaces avant un bloc {% %} en début de ligne
    autoescape=False,    # on gère l'échappement XML manuellement
)


# ── Validation MAC ─────────────────────────────────────────────────────────────

MAC_REGEX = re.compile(r'^[0-9a-f]{12}$')

def validate_mac(raw: str) -> str:
    clean = raw.lower().replace(":", "").replace("-", "")
    if not MAC_REGEX.match(clean):
        raise HTTPException(status_code=400, detail=f"Format MAC invalide : {raw!r}")
    return clean


# ── Schémas de requête ─────────────────────────────────────────────────────────

class MachinePatch(SQLModel):
    hostname: Optional[str] = None
    client: Optional[str] = None
    os: Optional[str] = None
    ou: Optional[str] = None
    organization_id: Optional[int] = None
    profile_id: Optional[int] = None

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

class ProfilePatch(SQLModel):
    name: Optional[str] = None
    locale: Optional[str] = None
    keyboard: Optional[str] = None
    timezone: Optional[str] = None
    default_user: Optional[str] = None
    extra_packages: Optional[str] = None
    join_domain: Optional[bool] = None
    domain: Optional[str] = None

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
        session.add(Profile(name="Ubuntu — par défaut", os="ubuntu"))
        session.add(Profile(name="Windows — par défaut", os="windows", locale="fr-FR"))
        session.commit()
        print("[OSIRIS] Profils par défaut créés")


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
    token = create_token(user_id, user_role)
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
        return [{"id": o.id, "name": o.name, "slug": o.slug} for o in orgs]


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
        return {"id": org.id, "name": org.name, "slug": org.slug}


@app.delete("/organizations/{org_id}", status_code=204)
def delete_organization(org_id: int, current_user: User = Depends(require_admin)):
    with Session(engine) as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation introuvable")
        _log(session, current_user, "delete_org", details={"name": org.name, "slug": org.slug})
        session.delete(org)
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


# ── Profils de déploiement ─────────────────────────────────────────────────────

def _profile_dict(p: Profile) -> dict:
    return {
        "id": p.id, "name": p.name, "os": p.os,
        "locale": p.locale, "keyboard": p.keyboard, "timezone": p.timezone,
        "default_user": p.default_user, "extra_packages": p.extra_packages,
        "join_domain": p.join_domain, "domain": p.domain,
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
    if body.os not in ("ubuntu", "windows"):
        raise HTTPException(status_code=400, detail="OS invalide : ubuntu ou windows")
    with Session(engine) as session:
        profile = Profile(**body.model_dump())
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


# ── Images OS ─────────────────────────────────────────────────────────────────

class ImageCreate(SQLModel):
    name: str
    version: str
    os: str = "ubuntu"
    iso_url: str


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
    if body.os not in ("ubuntu", "windows"):
        raise HTTPException(status_code=400, detail="OS invalide : ubuntu ou windows")
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

        # Machine déjà déployée → boot sur le disque local, pas de réinstall
        if machine.status == "deployed":
            script = "#!ipxe\n"
            script += f"echo [OSIRIS] {machine.hostname} est deploye - boot local\n"
            script += "exit\n"
            return Response(content=script, media_type="text/plain")

        machine.status = "deploying"
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

    content = jinja_env.get_template("unattend.xml.j2").render(
        hostname=escape(machine.hostname),
        client=escape(machine.client),
        ou=escape(machine.ou),
        profile=profile,
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
        status_url=f"{OSIRIS_BASE_URL}/machines/{clean_mac}/status",
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
            machine.deployed_at = datetime.utcnow()
            deployed_at = machine.deployed_at.isoformat()
        session.add(machine)
        session.commit()
    background_tasks.add_task(
        manager.broadcast,
        {"mac": clean_mac, "status": status, "deployed_at": deployed_at},
    )
    return {"detail": "Statut mis à jour"}


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
    client_ip = request.client.host
    mac = _ip_to_mac(client_ip)
    if not mac:
        return Response(
            content=f"echo [OSIRIS] IP {client_ip} inconnue dans les leases DHCP\r\npause\r\nexit /b 1",
            media_type="text/plain", status_code=404,
        )
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

    locale = getattr(profile, "locale", "fr_FR").replace("_", "-")[:5]
    content = jinja_env.get_template("winpe-deploy.cmd.j2").render(
        machine=machine,
        profile=profile,
        mac=mac,
        osiris_url=OSIRIS_BASE_URL,
        osiris_ip=OSIRIS_IP,
        win_index=1,
        locale=locale,
    )
    return Response(content=content, media_type="text/plain")


@app.get("/winpe-script/{mac}")
def get_winpe_script(mac: str):
    """Script CMD retourné à WinPE pour déployer Windows sur la machine."""
    return _build_winpe_script(validate_mac(mac))


@app.websocket("/ws/machines")
async def ws_machines(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # maintient la connexion ouverte
    except WebSocketDisconnect:
        manager.disconnect(websocket)
