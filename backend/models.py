import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv
from sqlmodel import Field, SQLModel, create_engine, Session


def normalize_model(name: str) -> str:
    """'OptiPlex 7090' → 'optiplex7090' — clé de recherche insensible à la casse/espaces."""
    return re.sub(r'[^a-z0-9]', '', name.lower())

load_dotenv()


class Organization(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                          # "Acme Corp"
    slug: str = Field(unique=True)     # "acme-corp"  — utilisé dans les URLs plus tard
    webhook_url: str = Field(default="")   # URL webhook (Teams, Slack, Discord…)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str = Field(default="technician")   # "admin" ou "technician"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    domain_join_user: str = Field(default="")       # Compte de jonction AD (ex: svc-joinpc)
    domain_join_password: str = Field(default="")   # Mot de passe chiffré Fernet
    win_image: str = Field(default="")              # Golden image : nom du .wim sur le partage (vide = install.wim auto)
    win_index: int = Field(default=1)               # Index de l'édition Windows dans le WIM (1=Home, 6=Pro typiquement)
    tv_suffix: str = Field(default="")              # Suffixe TeamViewer chiffré Fernet
    app_ids: str   = Field(default="")              # IDs d'apps séparés par virgule : "1,3,7"


class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                              # "Google Chrome"
    winget_id: str   = Field(default="")  # "Google.Chrome" — vide si pas de package Windows
    apt_package: str = Field(default="")  # "google-chrome-stable" — vide si pas de package Linux
    category: str    = Field(default="tools")  # browser | tools | security | office | media | dev | comm | remote
    icon: str        = Field(default="📦")


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DriverPack(SQLModel, table=True):
    __tablename__ = "driver_pack"

    id: Optional[int] = Field(default=None, primary_key=True)
    vendor: str = Field(index=True)       # "dell", "hp", "lenovo"
    model: str = Field(index=True)        # "OptiPlex 7090" (nom original Dell)
    model_key: str = Field(index=True)    # "optiplex7090" (normalisé pour la recherche)
    os_code: str                          # "Windows11" ou "Windows10"
    download_url: str                     # URL complète chez Dell
    size_mb: int = Field(default=0)
    local_path: str = Field(default="")  # /srv/data/windows/drivers/dell/optiplex7090/
    status: str = Field(default="available")  # available / downloading / ready
    catalog_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeploymentEvent(SQLModel, table=True):
    __tablename__ = "deployment_event"

    id: Optional[int] = Field(default=None, primary_key=True)
    mac: str = Field(index=True)
    hostname: str = Field(default="")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    status: str   # "pending" | "deploying" | "deployed" | "failed"
    os: str       = Field(default="")
    profile_name: str = Field(default="")


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
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
    from sqlalchemy import text
    SQLModel.metadata.create_all(engine)
    # Migrations légères : ajout de colonnes sans recréer les tables
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE profile ADD COLUMN IF NOT EXISTS app_ids VARCHAR NOT NULL DEFAULT ''"))
        conn.execute(text("ALTER TABLE organization ADD COLUMN IF NOT EXISTS webhook_url VARCHAR NOT NULL DEFAULT ''"))
        conn.commit()
