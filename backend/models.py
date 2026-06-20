import os
import urllib.parse
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from sqlmodel import Field, SQLModel, create_engine, Session

load_dotenv()


class Organization(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                          # "Acme Corp"
    slug: str = Field(unique=True)     # "acme-corp"  — utilisé dans les URLs plus tard
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str = Field(default="technician")   # "admin" ou "technician"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Profile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    os: str                                          # "ubuntu" ou "windows"
    locale: str   = Field(default="fr_FR.UTF-8")    # ex. en_US.UTF-8 pour Ubuntu, fr-FR pour Windows
    keyboard: str = Field(default="fr")
    timezone: str = Field(default="Europe/Paris")
    default_user: str  = Field(default="osiris")    # Ubuntu : nom de l'utilisateur local créé
    extra_packages: str = Field(default="")         # Ubuntu : paquets séparés par virgule
    join_domain: bool  = Field(default=True)        # Windows : joindre l'AD
    domain: str = Field(default="entreprise.local") # Windows : domaine AD


class Machine(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    mac: str = Field(index=True, unique=True)
    client: str
    os: str
    hostname: str
    ou: str = Field(default="")
    password_hash: Optional[str] = Field(default=None)
    status: str = Field(default="pending")
    deployed_at: Optional[datetime] = Field(default=None)
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id")
    profile_id: Optional[int] = Field(default=None, foreign_key="profile.id")


class OsImage(SQLModel, table=True):
    __tablename__ = "os_image"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                              # "Ubuntu 24.04 LTS"
    version: str                           # "24.04"
    os: str                                # "ubuntu"
    iso_url: str                           # URL de téléchargement
    nfs_path: str  = Field(default="")    # /srv/nfs/ubuntu-24.04
    status: str    = Field(default="queued")   # queued/downloading/extracting/ready/failed
    progress: int  = Field(default=0)     # 0-100 pendant le téléchargement
    error: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    user_id: Optional[int] = Field(default=None)       # pas de FK : si l'user est supprimé, le log reste
    user_email: str                                     # dénormalisé pour la même raison
    action: str = Field(index=True)                    # "login", "create_machine", etc.
    target_mac: Optional[str] = Field(default=None)   # pour les actions sur une machine
    details: Optional[str] = Field(default=None)       # JSON sérialisé


# ── Connexion PostgreSQL ───────────────────────────────────────────────────────
db_password  = urllib.parse.quote_plus(os.environ["DB_PASSWORD"])
db_user      = os.environ["DB_USER"]
db_host      = os.environ["DB_HOST"]
db_name      = os.environ["DB_NAME"]

DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}/{db_name}"
engine       = create_engine(DATABASE_URL, echo=False)


def init_db():
    SQLModel.metadata.create_all(engine)
