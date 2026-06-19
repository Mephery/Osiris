import os
import re
import secrets
from datetime import datetime
from typing import Optional
from xml.sax.saxutils import escape
from passlib.hash import sha512_crypt
from fastapi import HTTPException, FastAPI, Response, Depends
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlmodel import SQLModel, Session, select

from models import Machine, Organization, User, engine, init_db
from auth import (
    hash_password, verify_password, create_token,
    get_current_user, require_admin
)


# ── Démarrage ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _seed_admin()
    yield

app = FastAPI(lifespan=lifespan)


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


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {"status": "Osiris API v2026"}


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.post("/auth/login")
def login(body: LoginRequest):
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == body.email)).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    token = create_token(user.id, user.role)
    return {"access_token": token, "token_type": "bearer", "role": user.role, "email": user.email}


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


@app.post("/organizations", status_code=201, dependencies=[Depends(require_admin)])
def create_organization(body: OrgCreate):
    with Session(engine) as session:
        if session.exec(select(Organization).where(Organization.slug == body.slug)).first():
            raise HTTPException(status_code=400, detail="Ce slug est déjà utilisé")
        org = Organization(name=body.name, slug=body.slug)
        session.add(org)
        session.commit()
        session.refresh(org)
        return {"id": org.id, "name": org.name, "slug": org.slug}


@app.delete("/organizations/{org_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_organization(org_id: int):
    with Session(engine) as session:
        org = session.get(Organization, org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation introuvable")
        session.delete(org)
        session.commit()


# ── Utilisateurs ───────────────────────────────────────────────────────────────

@app.get("/users", dependencies=[Depends(require_admin)])
def get_users():
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        return [{"id": u.id, "email": u.email, "role": u.role} for u in users]


@app.post("/users", status_code=201, dependencies=[Depends(require_admin)])
def create_user(body: UserCreate):
    if body.role not in ("admin", "technician"):
        raise HTTPException(status_code=400, detail="Rôle invalide : admin ou technician")
    with Session(engine) as session:
        if session.exec(select(User).where(User.email == body.email)).first():
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
        user = User(email=body.email, hashed_password=hash_password(body.password), role=body.role)
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"id": user.id, "email": user.email, "role": user.role}


@app.delete("/users/{user_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_user(user_id: int, current_user: User = Depends(require_admin)):
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas supprimer votre propre compte")
    with Session(engine) as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable")
        session.delete(user)
        session.commit()


# ── Boot iPXE ──────────────────────────────────────────────────────────────────

@app.get("/boot")
def get_boot_script(mac: str | None = None):
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

        machine.status = "deploying"
        session.add(machine)
        session.commit()

        hostname = machine.hostname
        client   = machine.client
        os_type  = machine.os

    script = "#!ipxe\n"
    script += f"echo [OSIRIS] Configuration trouvee pour {hostname} ({client})\n"

    if os_type == "windows":
        script += "echo [OSIRIS] Chargement Windows 11...\n"
        script += f"kernel {OSIRIS_BASE_URL}/static/wimboot\n"
        script += f"imgfetch {OSIRIS_BASE_URL}/unattend.xml?mac={clean_mac}\n"
    elif os_type == "ubuntu":
        script += "echo [OSIRIS] Chargement Ubuntu 22.04...\n"
        script += f"kernel {OSIRIS_BASE_URL}/static/vmlinuz initrd=initrd ip=dhcp autoinstall boot=casper netboot=nfs nfsroot={OSIRIS_IP}:/srv/nfs/ubuntu ds=nocloud-net;s={OSIRIS_BASE_URL}/cloud-init/{clean_mac}/\n"
        script += f"initrd {OSIRIS_BASE_URL}/static/initrd\n"

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

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
    <settings pass="specialize">
        <component name="Microsoft-Windows-Shell-Setup">
            <ComputerName>{escape(machine.hostname)}</ComputerName>
            <RegisteredOwner>{escape(machine.client)}</RegisteredOwner>
        </component>
        <component name="Microsoft-Windows-UnattendedJoin">
            <Identification>
                <JoinDomain>entreprise.local</JoinDomain>
                <MachineObjectOU>{escape(machine.ou)}</MachineObjectOU>
            </Identification>
        </component>
    </settings>
</unattend>
"""
    return Response(content=xml, media_type="application/xml")


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

    ssh_section = (
        "  ssh:\n"
        "    install-server: true\n"
        "    allow-pw: true\n"
        + (f"    authorized-keys:\n      - {SSH_PUBKEY}\n" if SSH_PUBKEY else "")
    )
    status_url = f"{OSIRIS_BASE_URL}/machines/{clean_mac}/status"

    user_data = (
        "#cloud-config\n"
        "autoinstall:\n"
        "  version: 1\n"
        "  locale: fr_FR.UTF-8\n"
        "  keyboard:\n"
        "    layout: fr\n"
        "  storage:\n"
        "    layout:\n"
        "      name: direct\n"
        "  identity:\n"
        f"    hostname: {machine.hostname}\n"
        "    username: osiris\n"
        f"    hashed_passwd: '{machine.password_hash}'\n"
        f"{ssh_section}"
        "  early-commands:\n"
        f"    - curl -sf -X POST '{status_url}?status=deploying' || true\n"
        "  late-commands:\n"
        f"    - curl -sf -X POST '{status_url}?status=deployed' || true\n"
    )
    return Response(content=user_data, media_type="text/plain")


# ── CRUD machines ──────────────────────────────────────────────────────────────

@app.post("/machines", status_code=201, dependencies=[Depends(get_current_user)])
def create_machine(machine: Machine):
    clean_mac = validate_mac(machine.mac)
    machine.mac = clean_mac

    plaintext_password = secrets.token_urlsafe(16)
    machine.password_hash = sha512_crypt.using(rounds=100000).hash(plaintext_password)

    with Session(engine) as session:
        if session.exec(select(Machine).where(Machine.mac == clean_mac)).first():
            raise HTTPException(status_code=400, detail="Cette adresse MAC est déjà enregistrée.")
        session.add(machine)
        session.commit()
        session.refresh(machine)

    return {
        "id": machine.id, "mac": machine.mac, "client": machine.client,
        "os": machine.os, "hostname": machine.hostname, "ou": machine.ou,
        "status": machine.status, "organization_id": machine.organization_id,
        "password": plaintext_password,
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
                "deployed_at": m.deployed_at.isoformat() if m.deployed_at else None,
            }
            for m in machines
        ]


@app.patch("/machines/{mac}", dependencies=[Depends(get_current_user)])
def update_machine(mac: str, patch: MachinePatch):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        for field, value in patch.model_dump(exclude_none=True).items():
            setattr(machine, field, value)
        session.add(machine)
        session.commit()
        session.refresh(machine)
        return {
            "id": machine.id, "mac": machine.mac, "client": machine.client,
            "os": machine.os, "hostname": machine.hostname, "ou": machine.ou,
            "status": machine.status, "organization_id": machine.organization_id,
        }


@app.delete("/machines/{mac}", status_code=204, dependencies=[Depends(require_admin)])
def delete_machine(mac: str):
    clean_mac = validate_mac(mac)
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        session.delete(machine)
        session.commit()


@app.post("/machines/{mac}/status")
def report_machine_status(mac: str, status: str):
    """Appelé par la machine elle-même via curl pendant l'installation."""
    clean_mac = validate_mac(mac)
    valid = {"pending", "deploying", "deployed", "failed"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"Statut invalide. Valeurs : {valid}")
    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()
        if not machine:
            raise HTTPException(status_code=404, detail="Machine introuvable")
        machine.status = status
        if status == "deployed":
            machine.deployed_at = datetime.utcnow()
        session.add(machine)
        session.commit()
    return {"detail": "Statut mis à jour"}
