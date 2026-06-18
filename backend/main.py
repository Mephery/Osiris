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
from models import Machine, engine, init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

OSIRIS_BASE_URL = os.environ.get("OSIRIS_BASE_URL", "http://10.0.0.1:8000")
OSIRIS_IP       = os.environ.get("OSIRIS_IP", "192.168.1.18")
API_KEY         = os.environ.get("API_KEY", "")
SSH_PUBKEY      = os.environ.get("OSIRIS_SSH_PUBKEY", "").strip()

allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Auth ───────────────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(key: str = Depends(api_key_header)):
    if not API_KEY or key != API_KEY:
        raise HTTPException(status_code=401, detail="Clé API manquante ou invalide")

# ── Validation MAC ─────────────────────────────────────────────────────────────
MAC_REGEX = re.compile(r'^[0-9a-f]{12}$')

def validate_mac(raw: str) -> str:
    clean = raw.lower().replace(":", "").replace("-", "")
    if not MAC_REGEX.match(clean):
        raise HTTPException(status_code=400, detail=f"Format MAC invalide : {raw!r}")
    return clean

# ── Schéma de mise à jour partielle ───────────────────────────────────────────
class MachinePatch(SQLModel):
    hostname: Optional[str] = None
    client: Optional[str] = None
    os: Optional[str] = None
    ou: Optional[str] = None


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {"status": "Osiris API is running v2026 with PostgreSQL"}


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
            script += f"echo [OSIRIS] Machine inconnue en BDD (MAC: {clean_mac}).\n"
            script += "echo [OSIRIS] Boot standard sur le disque local dans 5 secondes...\n"
            script += "sleep 5\n"
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
        script += "echo [OSIRIS] Chargement de l'environnement d'installation Windows 11...\n"
        script += f"kernel {OSIRIS_BASE_URL}/static/wimboot\n"
        script += f"imgfetch {OSIRIS_BASE_URL}/unattend.xml?mac={clean_mac}\n"
    elif os_type == "ubuntu":
        script += "echo [OSIRIS] Chargement de l'installateur automatique Ubuntu 22.04...\n"
        script += f"kernel {OSIRIS_BASE_URL}/static/vmlinuz initrd=initrd ip=dhcp autoinstall boot=casper netboot=nfs nfsroot={OSIRIS_IP}:/srv/nfs/ubuntu ds=nocloud-net;s={OSIRIS_BASE_URL}/cloud-init/{clean_mac}/\n"
        script += f"initrd {OSIRIS_BASE_URL}/static/initrd\n"

    script += "boot\n"
    return Response(content=script, media_type="text/plain")


@app.get("/unattend.xml")
def get_unattend_xml(mac: str):
    clean_mac = validate_mac(mac)

    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()

    if not machine:
        return Response(
            content="<?xml version='1.0' encoding='utf-8'?><error>Machine inconnue</error>",
            media_type="application/xml",
            status_code=404,
        )

    xml_template = f"""<?xml version="1.0" encoding="utf-8"?>
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
    return Response(content=xml_template, media_type="application/xml")


@app.get("/cloud-init/{mac}/meta-data")
def get_meta_data(mac: str):
    clean_mac = validate_mac(mac)

    with Session(engine) as session:
        machine = session.exec(select(Machine).where(Machine.mac == clean_mac)).first()

    if not machine:
        raise HTTPException(status_code=404, detail="Machine inconnue")

    content = f"instance-id: osiris-{clean_mac}\nlocal-hostname: {machine.hostname}\n"
    return Response(content=content, media_type="text/plain")


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

@app.post("/machines", status_code=201, dependencies=[Depends(require_api_key)])
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
        "id": machine.id,
        "mac": machine.mac,
        "client": machine.client,
        "os": machine.os,
        "hostname": machine.hostname,
        "ou": machine.ou,
        "status": machine.status,
        "password": plaintext_password,
    }


@app.get("/machines", dependencies=[Depends(require_api_key)])
def get_all_machines():
    with Session(engine) as session:
        machines = session.exec(select(Machine)).all()
        return [
            {
                "id": m.id,
                "mac": m.mac,
                "client": m.client,
                "os": m.os,
                "hostname": m.hostname,
                "ou": m.ou,
                "status": m.status,
                "deployed_at": m.deployed_at.isoformat() if m.deployed_at else None,
            }
            for m in machines
        ]


@app.patch("/machines/{mac}", dependencies=[Depends(require_api_key)])
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
            "status": machine.status,
        }


@app.delete("/machines/{mac}", status_code=204, dependencies=[Depends(require_api_key)])
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
    """Appelé par la machine elle-même pendant l'installation (via curl dans user-data)."""
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
