# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy import Index, text
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
    # Adresse du serveur/proxy Zabbix qui collecte les machines de cette organisation
    # (ex. "192.0.2.130"). Les agents sont configurés en mode ACTIF : ils sortent
    # vers cette adresse en TCP 10051, le collecteur n'a jamais à les joindre.
    # Vide = pas de supervision pour cette organisation.
    zabbix_server: str = Field(default="")
    # Mot de passe administrateur BIOS pose sur les machines de cette organisation,
    # chiffre Fernet comme DomainConfig.join_password. Vide = on ne touche pas au BIOS.
    bios_password: str = Field(default="")
    # Prefixe des 4 premiers octets de la MAC imposee par le client, en hexa sans
    # separateur (ex. "02aabbcc"). Les 2 derniers octets sont derives des 3 derniers
    # chiffres du hostname. Vide = on ne reecrit pas la MAC. Voir _mac_from_hostname().
    mac_prefix: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str = Field(default="technician")   # "admin" ou "technician"
    totp_secret: str = Field(default="")      # secret TOTP chiffre Fernet - vide = 2FA desactive
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_key"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str                              # label choisi par l'utilisateur
    prefix: str = Field(index=True)        # 16 premiers caracteres de la cle (pour lookup rapide)
    key_hash: str                          # SHA-256 de la cle complete
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used_at: Optional[datetime] = Field(default=None)


class DomainConfig(SQLModel, table=True):
    __tablename__ = "domain_config"

    id: Optional[int] = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", index=True)
    name: str                              # label affiche dans l'UI, ex: "Siege principal"
    domain: str                            # "corp.example.local"
    join_user: str = Field(default="")    # compte de jonction (clair)
    join_password: str = Field(default="")  # chiffre Fernet
    default_ou: str = Field(default="")   # OU par defaut pour les machines
    wifi_ssid: str = Field(default="")    # SSID WiFi pousse aux machines qui joignent ce domaine
    wifi_password: str = Field(default="")  # mot de passe WiFi chiffre Fernet


class VpnTunnel(SQLModel, table=True):
    __tablename__ = "vpn_tunnel"

    id: Optional[int] = Field(default=None, primary_key=True)
    organization_id: int = Field(foreign_key="organization.id", index=True, unique=True)
    name: str                              # label affiche dans l'UI, ex: "Tunnel Midi2i"
    slug: str = Field(unique=True)         # nom de fichier / instance systemd, ex: "midi2i"
    ovpn_config: str = Field(default="")   # contenu du .ovpn chiffre Fernet
    remote_dns: str = Field(default="")    # IP(s) du DNS interne du client, separees par des virgules
    route_cidr: str = Field(default="")    # reseau du client joignable via le tunnel, ex: "10.8.0.0/16"
    vpn_username: str = Field(default="")  # compte auth-user-pass cote client (clair, comme DomainConfig.join_user)
    vpn_password: str = Field(default="")  # mot de passe auth-user-pass, chiffre Fernet
    requires_totp: bool = Field(default=False)  # si True, un code TOTP saisi par un humain est requis a chaque Apply (jamais stocke)
    enabled: bool = Field(default=True)
    status: str = Field(default="unknown")            # unknown | active | inactive | failed
    last_applied_at: Optional[datetime] = Field(default=None)
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
    enable_bitlocker: bool = Field(default=True)    # Activer BitLocker au premier demarrage Windows
    bitlocker_pin: bool = Field(default=False)      # True = TPM+PIN (redemarrage manuel), False = TPM seul (auto)
    network_drives: str = Field(default="")         # JSON : [{"letter":"Z","path":"\\\\srv\\share"}]
    printers: str = Field(default="")              # JSON : ["\\\\srv\\imprimante1"]
    post_script: str = Field(default="")
    domain_config_id: Optional[int] = Field(default=None, foreign_key="domain_config.id")  # si set, prend le dessus sur les champs domain/join_* inline
    tv_suffix: str = Field(default="")              # Suffixe TeamViewer chiffré Fernet
    app_ids: str   = Field(default="")              # IDs d'apps séparés par virgule : "1,3,7"
    laps_rotation_days: int = Field(default=0)      # 0 = rotation desactivee
    machine_type: str = Field(default="workstation")       # "workstation" | "server"
    ssh_authorized_keys: str = Field(default="")           # clés SSH (une par ligne)
    # Gabarit materiel des VM creees avec ce profil. Sert de valeur par defaut au
    # formulaire de creation : un profil « serveur de fichiers » n'a pas les memes
    # besoins qu'un poste, et les resaisir a chaque VM est une source d'erreur.
    vm_vcpus: int = Field(default=2)
    vm_ram_mb: int = Field(default=2048)
    vm_disk_gb: int = Field(default=20)
    # Second disque, monte sur /data au premier demarrage. 0 = pas de disque de
    # donnees. Separer systeme et donnees est la norme sur un serveur : on peut
    # redimensionner, sauvegarder ou reinstaller l'un sans toucher a l'autre.
    vm_data_disk_gb: int = Field(default=0)
    # Linux : poser un mot de passe root aleatoire, stocke chiffre cote OSIRIS.
    # Acces de SECOURS par la console quand le reseau ou SSH est tombe. Root
    # reste interdit en SSH : ce mot de passe ne sert qu'en local.
    set_root_password: bool = Field(default=False)


class Hypervisor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id")
    name: str                              # "Proxmox Production"
    type: str = Field(default="proxmox")   # extensible : "proxmox" pour l'instant
    url: str                               # "https://proxmox.local:8006"
    token_id: str = Field(default="")     # "osiris@pve!osiris-token"
    token_secret: str = Field(default="") # chiffré Fernet
    # Verification du certificat TLS. Par defaut ACTIVEE : le jeton porte des droits
    # de vie et de mort sur les VM, et sur une session non verifiee il suffit de se
    # placer sur le chemin OSIRIS↔hyperviseur pour le recolter. La desactiver reste
    # possible (Proxmox s'installe avec un certificat auto-signe) mais c'est un choix
    # explicite, journalise a chaque appel.
    tls_verify: bool = Field(default=True)
    # Pool Proxmox d'accueil des VM creees par OSIRIS. Vide = pas de pool.
    #
    # C'est le BORNAGE du rayon d'action : en attribuant le role du jeton sur
    # `/pool/<ce pool>` plutot que sur `/`, l'hyperviseur refuse lui-meme toute
    # action sur une VM qu'OSIRIS n'a pas creee. Un bug d'OSIRIS ne peut alors plus
    # toucher une VM de production, meme en visant le bon numero. Defense en
    # profondeur : c'est la meme garantie que `vm_uuid`, mais rendue par la
    # plateforme au lieu du code.
    pool: str = Field(default="")
    snippets_storage: str = Field(default="")    # nom du stockage Proxmox avec content-type "snippets" (ex: "local")
    # Adresse d'OSIRIS telle que la voient les VM DE CET HYPERVISEUR. Vide = la
    # variable globale OSIRIS_BASE_URL. Indispensable des qu'on deploie sur un
    # second site : l'URL est gravee dans les scripts de premier demarrage, et
    # une VM qui ne l'atteint pas ne rappelle jamais OSIRIS — elle reste
    # eternellement « en attente » sans que rien n'explique pourquoi.
    callback_url: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                              # "Google Chrome"
    winget_id: str   = Field(default="")  # "Google.Chrome" — vide si pas de package Windows
    apt_package: str = Field(default="")  # "google-chrome-stable" — vide si pas de package Linux
    category: str    = Field(default="tools")  # browser | tools | security | office | media | dev | comm | remote
    icon: str        = Field(default="📦")
    # Installeur custom Windows (au lieu de winget) : pour les apps a licence/enrolement
    # comme WithSecure. Le MSI/EXE est heberge sous backend/static/installers/ et servi
    # par OSIRIS ; le firstboot le telecharge et lance la commande silencieuse.
    install_type: str    = Field(default="winget")  # "winget" | "msi" | "exe"
    installer_file: str  = Field(default="")        # nom du fichier sous static/installers/
    install_args: str    = Field(default="")        # args silencieux (ex: "/qn VOUCHER=... LANGUAGE=fr")
    installer_config_file: str = Field(default="")  # fichier compagnon telecharge a cote (ex: config XML de l'ODT Office)
    detect_name: str     = Field(default="")        # chaine cherchee dans le registre pour le smoke test (si le nom installe differe du nom affiche)
    # Crochet de post-installation LINUX : script bash execute juste apres l'apt-get
    # install du paquet, dans le firstboot. Pendant Linux de installer_config_file,
    # qui est exclusivement Windows. Sans lui on sait poser un paquet mais pas le
    # configurer — bloquant pour tout ce qui a besoin d'un fichier de conf (agent
    # Zabbix, exporters, VPN...). Le script tourne en root, `set -e` non impose.
    linux_post_install: str = Field(default="")


class Machine(SQLModel, table=True):
    # RESERVATION de l'identifiant de VM : deux fiches ne peuvent pas revendiquer le
    # meme numero sur le meme hyperviseur. `cluster/nextid` rend le plus petit
    # identifiant libre SANS le reserver ; deux creations simultanees recevaient donc
    # le meme numero, la premiere creait la VM, et le rollback de la seconde purgeait
    # la VM de la premiere. Cet index fait echouer la seconde fiche AVANT le moindre
    # appel a l'hyperviseur — c'est la reservation qui manquait.
    # Partiel (`> 0`) : les machines physiques portent toutes `proxmox_vm_id = 0` et
    # doivent rester aussi nombreuses qu'on veut.
    __table_args__ = (
        Index(
            "ix_machine_vm_reservation", "hypervisor_id", "proxmox_vm_id",
            unique=True,
            postgresql_where=text("proxmox_vm_id > 0"),
            sqlite_where=text("proxmox_vm_id > 0"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # MAC PROPRE AU PC : identite permanente, obligatoire. C'est elle qui sert de cle
    # a toute l'API (/machines/{mac}/...) et qui est gravee dans les scripts generes.
    mac: str = Field(index=True, unique=True)
    # MAC de l'ADAPTATEUR USB-Ethernet utilise pour CE deploiement : facultative, et
    # TRANSITOIRE. Un meme dongle sert a deployer plusieurs machines a la suite, donc
    # OSIRIS l'OUBLIE (remise a None) des que la machine passe en "deployed" : le
    # dongle redevient immediatement reutilisable sur une autre fiche.
    # Unique + nullable : Postgres autorise plusieurs NULL, donc autant de machines
    # sans dongle qu'on veut, mais un dongle donne ne peut etre revendique que par
    # une seule machine a la fois (evite une identification ambigue en WinPE).
    deploy_mac: Optional[str] = Field(default=None, index=True, unique=True, nullable=True)
    client: str
    os: str
    hostname: str
    ou: str = Field(default="")
    password_hash: Optional[str] = Field(default=None)
    status: str = Field(default="pending")
    deployed_at: Optional[datetime] = Field(default=None)
    organization_id: Optional[int] = Field(default=None, foreign_key="organization.id")
    profile_id: Optional[int] = Field(default=None, foreign_key="profile.id")
    # Inventaire materiel (collecte au premier demarrage)
    # Indexé : sert d'identité STABLE au déploiement (lookup depuis WinPE), la MAC
    # n'identifiant plus la machine dès qu'on passe par un adaptateur USB-Ethernet.
    hw_serial: str = Field(default="", index=True)
    hw_model: str = Field(default="")
    # Identifiant matériel constructeur (Win32_ComputerSystemProduct.Name). Chez
    # Lenovo c'est le MTM ("20S6CTO1WW") dont les 4 premiers caractères désignent
    # le Machine Type — la seule façon fiable de distinguer un T15 d'un T15g, que
    # le nom commercial confond. Chez Dell/HP il vaut le nom commercial, sans mal :
    # le rapprochement par nom y fonctionne déjà.
    hw_sysid: str = Field(default="", index=True)
    hw_ram_gb: int = Field(default=0)
    hw_disk_gb: int = Field(default=0)     # taille du disque systeme (Go)
    hw_disk_type: str = Field(default="")  # type de disque (SSD NVMe, SSD (SATA), HDD...)
    hw_cpu: str = Field(default="")        # type/modele du processeur
    # BitLocker (Windows uniquement) - chiffres Fernet
    bitlocker_key: str = Field(default="")
    bitlocker_pin: str = Field(default="")
    # Mot de passe administrateur local (LAPS) - chiffre Fernet
    laps_password: str = Field(default="")
    laps_rotated_at: Optional[datetime] = Field(default=None)
    # Utilisateur final affecte a cette machine (optionnel)
    user_name: str = Field(default="")
    user_email: str = Field(default="")
    # Adressage IP fixe, applique par cloud-init au premier demarrage. Vide =
    # DHCP. Indispensable des qu'on deploie sur un VLAN serveur : ils sont
    # rarement servis par un DHCP, et une VM sans bail demarre, tourne, et ne
    # rappelle jamais OSIRIS sans que rien ne l'explique.
    ip_cidr: str = Field(default="")        # ex. "203.0.113.60/24"
    gateway: str = Field(default="")        # ex. "203.0.113.1"
    dns_servers: str = Field(default="")    # separes par des virgules

    # Supervision Zabbix : activee par defaut, l'agent n'est reellement installe que
    # si l'organisation de la machine a un zabbix_server renseigne.
    supervised: bool = Field(default=True)
    # Notes libres
    notes: str = Field(default="")
    # Smoke tests post-deploiement
    smoke_status: str = Field(default="")   # "" | "ok" | "warnings"
    smoke_results: str = Field(default="")  # JSON : [{"name": "...", "ok": true, "detail": "..."}]
    # Pack de drivers a injecter au deploiement (choisi/confirme par l'operateur).
    # Si defini + pack telecharge : injection ciblee ; sinon fallback = tout le dossier drivers.
    driver_pack_id: Optional[int] = Field(default=None, foreign_key="driver_pack.id")
    # VM (Proxmox) - vide pour les machines physiques
    hypervisor_id: Optional[int] = Field(default=None, foreign_key="hypervisor.id")
    proxmox_vm_id: int = Field(default=0)   # ID de la VM dans Proxmox (ex: 101), 0 = physique
    proxmox_node: str = Field(default="")   # noeud Proxmox sur lequel tourne la VM
    # ANCRE D'IDENTITE de la VM : l'UUID SMBIOS que l'hyperviseur lui a genere.
    #
    # `proxmox_vm_id` ne suffit PAS a designer une VM dans le temps : `nextid` rend
    # le plus petit identifiant libre, donc Proxmox RECYCLE les numeros. Une VM
    # supprimee a la main sans retirer la fiche laisse un numero qui repart au
    # tourniquet, et la fiche se met alors a designer la VM de quelqu'un d'autre.
    # Toute action destructrice (purge, rollback de snapshot, retour sur le CD
    # WinPE = reinstallation) frapperait la mauvaise machine.
    #
    # L'UUID, lui, est genere a la creation, unique, et un clone en recoit un neuf.
    # On le compare avant CHAQUE ecriture : c'est ce qui rend l'identifiant sur
    # lequel on agit verifiable. Vide sur les fiches anterieures a ce garde-fou et
    # sur les machines physiques : on retombe alors sur le nom (cf. `_ident_vm`).
    vm_uuid: str = Field(default="")
    # Numero du deploiement en cours, incremente a chaque repassage en "pending".
    # Sert a regrouper les lignes de DeployLogLine : relancer un deploiement ouvre un
    # nouveau journal sans effacer celui de la tentative precedente.
    deploy_log_run: int = Field(default=1)


class OsImage(SQLModel, table=True):
    __tablename__ = "os_image"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                              # "Ubuntu 24.04 LTS"
    version: str                           # "24.04"
    os: str                                # "ubuntu"
    iso_url: str                           # URL de téléchargement
    nfs_path: str  = Field(default="")    # /srv/nfs/ubuntu-24.04
    wim_name: str  = Field(default="")    # Windows : nom du .wim cible sur le partage SMB
                                          # (vide = install.wim). Permet de faire coexister
                                          # plusieurs images Windows (client / Server) sur le partage.
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
    status: str = Field(default="available")  # available / downloading / ready / error
    error: str = Field(default="")        # raison de l'échec quand status == "error"
    # Identifiants matériel publiés par le constructeur, en minuscules, séparés par
    # des virgules. Dell = systemID ("092f") ; HP = SystemId carte mère ("81c3,8396") ;
    # Lenovo = Machine Type ("20s6,20s7"). Permet de désigner le bon pack sans passer
    # par le nom commercial — c'est une lettre qui sépare un T15 d'un T15g.
    hw_ids: str = Field(default="", index=True)
    catalog_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeployLogLine(SQLModel, table=True):
    """Une ligne du journal de deploiement, postee en direct par WinPE ou le firstboot.

    Persistee, et non plus gardee dans un dict en memoire : le journal survit ainsi au
    redemarrage du backend comme a un simple F5, et surtout il reste consultable APRES
    le deploiement — c'est precisement la qu'on en a besoin, la fenetre WinPE ayant
    disparu avec la machine qui reboote.
    """
    __tablename__ = "deploy_log_line"

    id: Optional[int] = Field(default=None, primary_key=True)
    mac: str = Field(index=True)
    # Deploiement auquel appartient la ligne (cf. Machine.deploy_log_run).
    run: int = Field(default=1, index=True)
    # UTC *naif*, et pas `datetime.now(timezone.utc)` : la colonne Postgres est un
    # TIMESTAMP WITHOUT TIME ZONE, dans lequel un datetime avise est converti vers le
    # fuseau de la session — on y stockait donc l'heure LOCALE, alors que le texte de
    # `line` est horodate en UTC. Deux heures d'ecart dans le meme fichier, et un
    # export .txt qui annoncait « UTC » en affichant autre chose (constate le 04/08).
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    line: str


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


# ── Connexion base de données ─────────────────────────────────────────────────
# DATABASE_URL peut etre defini directement (tests, Docker, Heroku...).
# Sinon, reconstruit depuis les variables individuelles.
if os.environ.get("DATABASE_URL"):
    DATABASE_URL = os.environ["DATABASE_URL"]
    engine = create_engine(DATABASE_URL, echo=False,
                           connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
else:
    db_password  = urllib.parse.quote_plus(os.environ["DB_PASSWORD"])
    db_user      = os.environ["DB_USER"]
    db_host      = os.environ["DB_HOST"]
    db_name      = os.environ["DB_NAME"]
    DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}/{db_name}"
    engine       = create_engine(DATABASE_URL, echo=False)


def init_db():
    # Les migrations de schema sont gerees par Alembic (alembic upgrade head).
    # create_all reste ici comme filet de securite pour le dev local sans Alembic.
    SQLModel.metadata.create_all(engine)
