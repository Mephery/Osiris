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


# ── Connexion PostgreSQL ───────────────────────────────────────────────────────
db_password  = urllib.parse.quote_plus(os.environ["DB_PASSWORD"])
db_user      = os.environ["DB_USER"]
db_host      = os.environ["DB_HOST"]
db_name      = os.environ["DB_NAME"]

DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}/{db_name}"
engine       = create_engine(DATABASE_URL, echo=False)


def init_db():
    SQLModel.metadata.create_all(engine)
