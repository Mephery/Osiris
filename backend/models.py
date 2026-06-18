import os
import urllib.parse
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
from sqlmodel import Field, SQLModel, create_engine, Session

load_dotenv()

# 1. Définition du modèle de données (La table PostgreSQL)
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

# 2. Configuration de la connexion PostgreSQL
db_password = urllib.parse.quote_plus(os.environ["DB_PASSWORD"])
db_user     = os.environ["DB_USER"]
db_host     = os.environ["DB_HOST"]
db_name     = os.environ["DB_NAME"]

DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}/{db_name}"

# Engine = moteur qui gère les connexions à la BDD
engine = create_engine(DATABASE_URL, echo=False)

# 3. Fonction pour créer les tables si elles n'existent pas
def init_db():
    SQLModel.metadata.create_all(engine)