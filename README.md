# OSIRIS - Serveur de déploiement réseau

OSIRIS est un serveur de déploiement PXE pensé pour les équipes d'infogérance.
Il remplace les outils comme MDT/WDS avec une interface web moderne, une API REST et une automatisation complète du cycle de vie des postes.

> **Statut :** Production-ready en environnement lab - Windows 11 et Ubuntu 24.04 LTS validés bout-en-bout.

**Philosophie :** brancher un câble RJ45 suffit. La machine PXE-boot, OSIRIS la déploie, configure TeamViewer, installe les apps, joint le domaine, active BitLocker, tout depuis l'interface.

**Le logo** est le scarabée de Khepri, qui pousse un processeur à la place du disque solaire : le renouvellement d'un cycle, soit exactement ce que fait un serveur qui réinstalle une machine. Tracé en `currentColor` (`frontend/public/favicon.svg`), il suit le thème clair ou sombre sans variante à maintenir.

---

## Fonctionnalités

| Fonctionnalité | Windows | Ubuntu | Debian |
|---|---|---|---|
| Déploiement PXE automatique | WinPE + wimboot | cloud-init / subiquity | preseed |
| Partitionnement GPT automatique | oui | oui | oui |
| Jonction domaine AD automatique | oui (unattend + firstboot) | oui (realmd + sssd) | - |
| Multi-domaine AD par organisation | oui | oui | - |
| Sélecteur d'applications (winget / apt) | 24 apps | 24 apps | - |
| Configuration TeamViewer automatique | oui | oui | - |
| Barre de progression DISM temps réel | oui | - | - |
| Drivers Dell / HP / Lenovo | oui | - | - |
| BitLocker (TPM seul ou TPM+PIN) | oui | - | - |
| LAPS - mot de passe admin local unique | oui | - | - |
| Rotation LAPS automatique (30/60/90/180j) | oui | - | - |
| Smoke tests post-déploiement | oui | oui | - |
| Inventaire matériel automatique | oui | oui | - |
| Mapping lecteurs réseau au démarrage | oui | - | - |
| Imprimantes réseau au démarrage | oui | - | - |
| Script post-install personnalisé | PowerShell | Bash | - |
| Notification échec firstboot | oui | oui | - |
| Wake-on-LAN | oui | oui | oui |
| Redéployer maintenant (WoL + pending) | oui | oui | oui |
| Déploiement en lot | oui | oui | oui |
| Historique de déploiement par machine | oui | oui | oui |
| Notifications webhook structurées (Teams / Slack) | oui | oui | oui |
| Capture golden image | oui (WIM) | - | - |
| Navigateur WIM | oui | - | - |
| Import / export CSV machines | oui | oui | oui |
| Notes libres sur les machines | oui | oui | oui |
| Utilisateur affecté à une machine | oui | oui | oui |
| Tableau de bord par organisation | oui | oui | oui |
| Filtres avancés (OS, smoke, recherche) | oui | oui | oui |
| Clonage de profil | oui | oui | oui |
| 2FA TOTP (optionnel par compte) | - | - | - |
| Clés API personnelles | - | - | - |

---

## Flux de déploiement

```
Machine vierge
     |
     |  boot réseau : DHCP -> iPXE
     v
GET  /boot?mac=aa:bb:cc:...
     |  OSIRIS reconnaît la MAC, génère un script iPXE à la volée
     v
 Ubuntu --> kernel casper via NFS + user-data (cloud-init)
 Windows -> wimboot + WinPE + unattend.xml
     |
     |  pendant l'install, la machine appelle :
     |  POST /machines/{mac}/status?status=deploying
     |  POST /machines/{mac}/log?msg=...
     |  POST /machines/{mac}/status?status=deployed
     v
 Premier démarrage (firstboot)
     |  Windows : firstboot-windows.ps1 (inventaire, LAPS, BitLocker,
     |            TeamViewer, winget, lecteurs, imprimantes, script perso,
     |            smoke tests, tâche planifiée rotation LAPS si activée)
     |  Ubuntu  : firstboot-ubuntu.sh  (inventaire, TeamViewer, apt,
     |            jonction AD, script perso, smoke tests)
     v
 POST /machines/{mac}/smoke-tests -> résultats stockés, badge dans l'UI
 Statut mis à jour en temps réel via WebSocket
 Webhook envoyé si une URL est configurée sur l'organisation
 Si le script échoue, callback automatique status=failed
```

---

## Pile technique

| Composant | Technologie |
|---|---|
| Backend | Python 3.11 - FastAPI - SQLModel |
| Base de données | PostgreSQL |
| Migrations | Alembic |
| File de tâches | ARQ - Redis |
| Proxy | Caddy (HTTPS auto via mkcert en local) |
| Frontend | React 19 - TypeScript - Tailwind CSS v4 - sonner |
| Auth | JWT (python-jose) + clés API + 2FA TOTP (pyotp) |
| Chiffrement | Fernet (AES-128-CBC) pour les secrets - SHA-256 pour les clés API |
| Boot réseau | iPXE - dnsmasq (DHCP/TFTP) |
| Autoinstall Ubuntu | cloud-init / subiquity |
| Autoinstall Windows | WinPE - wimboot - unattend.xml |
| Partage fichiers Windows | Samba (NT1 pour WinPE) |
| Drivers constructeurs | Dell / HP / Lenovo (catalogue XML) |
| Apps Windows | winget (firstboot) |
| Apps Ubuntu | apt (cloud-init packages + firstboot) |

---

## Installation

### Option A - Docker Compose (recommandé)

Nécessite Docker Engine et Docker Compose v2. Les services dnsmasq et Samba restent sur l'hôte car ils requièrent un accès réseau de bas niveau (broadcasts DHCP, TFTP).

```bash
git clone https://github.com/Mephery/Osiris.git
cd osiris

cp .env.example .env
# Éditer .env : DB_PASSWORD, JWT_SECRET, ADMIN_PASSWORD, OSIRIS_BASE_URL, OSIRIS_IP...

# Compiler le frontend (nécessite Node.js 22+)
chmod +x build.sh && ./build.sh

# Démarrer tous les services (postgres, redis, backend, worker, caddy)
docker compose up -d

# Vérifier l'état
docker compose logs -f backend
```

Au premier démarrage, le backend applique automatiquement les migrations Alembic avant de lancer l'API.

### Option B - Installation directe (développement)

Prérequis : Python 3.11+, Node.js 22+, PostgreSQL 14+, Redis.

Outils système utilisés par le worker :

```bash
sudo apt install p7zip-full innoextract xorriso wimtools
```

`innoextract` est indispensable aux packs de pilotes **Lenovo** : ils sont livrés
en installeurs Inno Setup, que 7-Zip ne sait pas ouvrir. Sans lui, l'extraction
ne produit que les ressources du binaire Windows et le pack ne contient aucun
pilote (le worker le refuse alors explicitement, cf. contrôle « 0 fichier .inf »).

```bash
git clone https://github.com/Mephery/Osiris.git
cd osiris/backend

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Éditer .env avec vos valeurs

# Appliquer les migrations de schéma
alembic upgrade head

# Démarrer l'API
uvicorn main:app --host 0.0.0.0 --port 8000
```

Dans un second terminal :

```bash
cd backend && source venv/bin/activate
arq worker.WorkerSettings
```

Frontend :

```bash
cd frontend
cp .env.example .env   # renseigner VITE_API_URL
npm install
npm run build          # génère dist/ servi par Caddy
```

Au premier démarrage (Docker ou direct), OSIRIS crée automatiquement :
- Un compte admin depuis `ADMIN_EMAIL` / `ADMIN_PASSWORD`
- Deux profils par défaut (Ubuntu + Windows)
- 24 applications courantes dans le catalogue

**Changez le mot de passe admin immédiatement** (icône paramètres en haut à droite).

---

## Variables d'environnement

Le fichier `.env.example` à la racine du projet documente toutes les variables. Voici les principales :

```env
# PostgreSQL
DB_USER=osiris_user
DB_PASSWORD=votre_mot_de_passe
DB_HOST=localhost          # "postgres" en Docker Compose
DB_NAME=osiris

# JWT - générer avec : python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=changeme

# Compte admin créé au premier démarrage (si aucun user en base)
ADMIN_EMAIL=admin@osiris.local
ADMIN_PASSWORD=changeme

# Réseau PXE - IP vue par les machines qui bootent (pas l'IP d'accès à l'UI !)
OSIRIS_BASE_URL=http://10.0.0.1:8000
OSIRIS_IP=10.0.0.1

# CORS - origines autorisées pour le frontend
ALLOWED_ORIGINS=https://osiris.local,https://192.168.1.x

# Redis (ARQ)
REDIS_URL=redis://localhost:6379   # "redis://redis:6379" en Docker Compose

# Frontend (build Vite)
VITE_API_URL=https://osiris.local
```

> **Note réseau :** `OSIRIS_BASE_URL` doit être l'IP du réseau PXE (celle que voient les machines qui bootent). Ne pas confondre avec l'URL d'accès à l'UI.

---

## Migrations de schéma (Alembic)

OSIRIS utilise Alembic pour versionner les migrations de base de données.

### Workflow quotidien

```bash
cd backend

# Après avoir modifié un modèle dans models.py :
alembic revision --autogenerate -m "add colonne_truc to machine"

# Relire et vérifier le fichier généré dans alembic/versions/
# Puis appliquer :
alembic upgrade head

# Vérifier l'état courant :
alembic current
```

### Mise à jour depuis une version sans Alembic

Les installations créées avant l'introduction d'Alembic peuvent être mises à niveau sans perte de données. La migration initiale (`0001`) est entièrement idempotente :

```bash
cd backend && source venv/bin/activate
alembic upgrade head
# "Running upgrade -> 0001, Initial schema" - les tables existantes ne sont pas touchées
```

### Règle à respecter en écrivant une migration

La `0001` fait un `SQLModel.metadata.create_all()`. Sur une base **vierge**, elle crée donc
d'emblée *toutes* les tables déclarées dans `models.py` au jour où on l'exécute — y compris
celles ajoutées par des migrations bien plus récentes. Chaque migration ultérieure doit donc
tolérer que son objet existe déjà :

```python
# OUI - le style de toute la chaîne
bind.execute(sa.text("ALTER TABLE machine ADD COLUMN IF NOT EXISTS truc VARCHAR NOT NULL DEFAULT ''"))
bind.execute(sa.text("CREATE TABLE IF NOT EXISTS bidule (...)"))

# NON - passe en production (déjà migrée), casse toute installation neuve
op.add_column("machine", sa.Column("truc", sa.String()))
op.create_table("bidule", ...)
```

Le piège est sournois : la base de production, déjà à jour, ne montre jamais rien.

### Tester la chaîne sur une base vierge

`backend/tests/test_migrations.py` rejoue `alembic upgrade head` sur une base neuve et compare
le schéma obtenu à `models.py`. Il ne tourne que si on lui fournit une base Postgres **jetable**
(les migrations sont du Postgres pur, le reste de la suite est sur SQLite) :

```bash
cd backend
export OSIRIS_MIGRATION_TEST_DB="postgresql://user:motdepasse@localhost/osiris_migtest"
python -m pytest tests/test_migrations.py
```

⚠️ Ce test fait un `DROP SCHEMA public CASCADE` sur la base visée. Il refuse de démarrer si le
nom de la base ne contient pas `test`. La CI lui fournit un conteneur Postgres dédié.

---

## Tableau de bord

L'onglet **Tableau de bord** affiche en temps réel :
- Compteurs globaux par statut (déployés / en attente / en cours / échoués / alertes smoke)
- Barres de répartition par organisation
- Alertes automatiques : machines bloquées en déploiement depuis plus de 30 minutes, échecs récents
- Liste des 15 derniers déploiements terminés

---

## Filtres avancés

La barre de recherche de l'onglet **Machines** combine plusieurs filtres simultanément :
- **Recherche texte** - hostname, client, MAC, modèle, utilisateur affecté, notes
- **OS** - filtre par Windows / Ubuntu / Debian
- **Smoke tests** - afficher uniquement les machines avec des alertes post-déploiement
- **Réinitialiser** - bouton visible dès qu'un filtre est actif

---

## Smoke tests post-déploiement

A la fin du premier démarrage, chaque machine exécute automatiquement une série de vérifications et envoie les résultats à OSIRIS :

**Vérifications effectuées**

| Test | Windows | Ubuntu |
|---|---|---|
| Ping passerelle | oui | oui |
| Résolution DNS | oui | oui |
| Jonction AD (si profil joint le domaine) | oui | oui |
| Service TeamViewer | oui | oui |
| Présence des applications installées | oui | oui |

**Dans l'interface**

- Badge vert "Tests OK" ou badge orange "N alerte(s)" sur chaque ligne machine
- Cliquer sur le badge développe le détail : chaque test avec un point vert/rouge et le message d'erreur si applicable
- Compteur "alertes smoke" dans la barre de stats rapides
- Bouton dans la barre de filtres pour isoler les machines en alerte

**Endpoint de réception**

```
POST /machines/{mac}/smoke-tests
Content-Type: application/json

{
  "tests": [
    {"name": "Ping passerelle", "ok": true, "detail": ""},
    {"name": "Résolution DNS", "ok": false, "detail": "getent hosts osiris.local a échoué"}
  ]
}
```

---

## BitLocker

Activé automatiquement au premier démarrage Windows si le profil l'autorise. Deux modes :

- **TPM seul** - démarrage automatique, clé de récupération 48 chiffres stockée dans OSIRIS
- **TPM+PIN** - PIN aléatoire à 6 chiffres généré à la volée, démarrage manuel requis. Les deux (PIN et clé 48 chiffres) sont stockés dans OSIRIS, chiffrés avec Fernet.

La clé et le PIN ne sont visibles dans l'interface que par les administrateurs, via le bouton "Afficher les clés" dans le panneau de chaque machine.

---

## LAPS - Mot de passe administrateur local

Au premier démarrage Windows, OSIRIS génère un mot de passe aléatoire de 16 caractères (lettres, chiffres, symboles), l'applique au compte `Administrator` local et le stocke chiffré (Fernet) dans OSIRIS. Chaque machine obtient un mot de passe unique.

Le mot de passe est visible uniquement par les administrateurs, via le bouton "Afficher le mot de passe" dans le panneau de la machine. La date de la dernière rotation est affichée en dessous.

### Rotation automatique

Dans chaque profil Windows, un champ **Rotation LAPS** permet de configurer le renouvellement automatique : désactivée, 30, 60, 90 ou 180 jours.

Quand la rotation est activée, OSIRIS dépose à la fin du premier démarrage :
- Un script `osiris-laps-renew.ps1` (chemin : `C:\Windows\System32\`)
- Une tâche planifiée Windows `OSIRIS-LAPS-Renewal` (SYSTEM, au démarrage, exécution cachée)

A chaque démarrage, le script interroge `GET /machines/{mac}/laps-due`. Si la période est écoulée, il génère un nouveau mot de passe, l'applique localement et le poste à OSIRIS via `POST /machines/{mac}/laps-password`.

---

## Inventaire matériel

Au premier démarrage, chaque machine collecte automatiquement :
- Fabricant et modèle (Windows : WMI Win32_ComputerSystem / Ubuntu : `/sys/class/dmi/id/`)
- Quantité de RAM en Go
- Numéro de série

Ces informations sont affichées dans le panneau de chaque machine et incluses dans l'export CSV.

---

## Domaines AD multi-clients

Les identifiants de jonction AD peuvent être configurés au niveau de chaque **organisation** plutôt que dans chaque profil. Cela évite de dupliquer les informations sensibles quand plusieurs profils utilisent le même domaine.

Dans **Administration > Domaines AD** : ajouter une configuration par client (nom, domaine, compte de jonction, OU par défaut). Dans le profil, sélectionner "Utiliser la config AD de l'organisation" ou continuer à saisir les informations directement dans le profil (compatibilité totale avec l'ancienne méthode).

La jonction AD Ubuntu/Debian utilise `realm join` (realmd + sssd) et configure automatiquement :
- Login sans suffixe `@domaine` (juste `utilisateur`)
- Création automatique du dossier home au premier login
- Groupe "Domain Admins" en sudo sans mot de passe

---

## Post-install : lecteurs, imprimantes, script

Dans chaque profil Windows, vous pouvez configurer des actions exécutées à la fin du premier démarrage :

- **Lecteurs réseau** - liste de paires lettre / chemin UNC (`Z:` -> `\\serveur\partage`). Utilise `New-PSDrive -Persist`, le mapping survit aux redémarrages.
- **Imprimantes réseau** - liste de chemins UNC (`\\serveur\imprimante`). Installées via `Add-Printer -ConnectionName`.
- **Script post-install** - bloc PowerShell (Windows) ou Bash (Ubuntu) exécuté en dernier. Les erreurs sont loguées mais ne bloquent pas le reste.

---

## Notification d'échec firstboot

Si le script de premier démarrage échoue de façon inattendue (erreur fatale non capturée), il envoie automatiquement un callback `status=failed` à OSIRIS avant de s'arrêter. La machine apparaît en rouge dans l'interface et une alerte s'affiche dans le tableau de bord.

---

## Déploiement en lot

Depuis l'onglet **Machines**, cochez les machines cibles, puis utilisez la barre d'actions :
- **Redéployer** - passe les machines en `pending` (elles redéploieront au prochain boot PXE)
- **WoL** - envoie un magic packet Wake-on-LAN
- **Redéployer maintenant** (bouton sur chaque ligne) - combine les deux en une seule action : remet en `pending` et envoie le WoL immédiatement

---

## Import / Export CSV

**Import** - bouton "Importer CSV" dans la barre du tableau machines. Format attendu (UTF-8 ou UTF-8-BOM pour Excel) :

```
mac,hostname,client,os,profile_name
aa:bb:cc:dd:ee:ff,PC-DUPONT,Acme Corp,windows,Windows -- par défaut
11:22:33:44:55:66,SRV-LINUX,Acme Corp,ubuntu,Ubuntu -- par défaut
aa:bb:cc:11:22:33,PC-MARTIN,Autre Client,debian,
```

Les machines déjà enregistrées (même MAC) sont ignorées silencieusement. `profile_name` est optionnel.

**Export** - bouton "Exporter CSV" dans la barre. Génère un fichier UTF-8-BOM incluant toutes les colonnes : MAC, hostname, client, OS, profil, statut, modèle, RAM, numéro de série, utilisateur affecté, notes.

---

## Sélecteur d'applications

Dans chaque **Profil**, sélectionnez les applications à installer automatiquement :
- **Windows** : installées via `winget` dans le firstboot (premier démarrage)
- **Ubuntu** : installées via `apt` dans le firstboot

24 applications disponibles : Chrome, Firefox, Signal, Audacity, VLC, LibreOffice, Nextcloud Client, Bitwarden, 7-Zip, Java OpenJDK 21, .NET Runtime 8, VS Code, MS Office 365, Adobe Acrobat Reader, TeamViewer, Slack, Zoom, Notepad++, WinRAR, Git, NetExplorer, Citrix Workspace, OpenVPN, WithSecure.

---

## Historique de déploiement

Chaque machine conserve un journal des transitions de statut. Cliquer sur le chevron d'une ligne affiche :
- Le journal du déploiement en cours, complété en direct via WebSocket
- L'historique des 20 derniers événements (date, statut, OS, profil utilisé)

### Journal de déploiement

Les lignes postées par WinPE et par le firstboot (`POST /machines/{mac}/log?msg=...`) sont
**stockées en base** (table `deploy_log_line`). Elles survivent donc au redémarrage du backend
comme au rechargement de la page — ce qui compte, puisque la fenêtre WinPE disparaît avec le
reboot de la machine et qu'on ne consulte le journal qu'après coup.

Relancer un déploiement **n'efface pas** le journal précédent : chaque passage en `pending`
ouvre un nouveau numéro de tentative (`Machine.deploy_log_run`). C'est justement après un échec
qu'on relance, et comparer deux tentatives est souvent ce qui met le doigt sur la cause.

| Route | Contenu |
|---|---|
| `GET /machines/{mac}/logs` | Déploiement **en cours** — c'est ce qu'affiche le terminal live |
| `GET /machines/{mac}/logs.txt` | **Toutes** les tentatives, en texte brut, servi en pièce jointe |

Le bouton **.txt** de la fiche machine télécharge le second.

Garde-fou : au-delà de `DEPLOY_LOG_MAX_LINES` (5000) lignes pour une même tentative, OSIRIS
cesse d'enregistrer et l'indique dans le journal — une machine coincée en boucle PXE ne peut
pas faire grossir la base indéfiniment.

---

## Notifications webhook

Dans **Administration > Organisations**, chaque organisation dispose d'un champ "Webhook URL". Quand un déploiement se termine (`deployed` ou `failed`), OSIRIS envoie un payload structuré :

```json
{
  "event": "deployed",
  "hostname": "PC-DUPONT",
  "mac": "aabbccddeeff",
  "client": "Acme Corp",
  "os": "windows",
  "hw_model": "HP EliteBook 840 G9",
  "hw_ram_gb": 16,
  "hw_serial": "5CD1234XYZ",
  "osiris_url": "https://osiris.local",
  "text": "PC-DUPONT déployé avec succès (WINDOWS - Acme Corp)"
}
```

Le champ `text` assure la compatibilité avec Teams (Incoming Webhook), Slack et Discord (`/slack` en fin d'URL).

---

## Intégrations API

### Swagger / documentation interactive

L'API complète est documentée et testable depuis le navigateur :

```
https://osiris.local/docs
```

### Vérification de santé

```bash
curl https://osiris.local/health
# {"status": "ok", "db": "ok", "version": "1.0.0"}
```

Utile pour les sondes de monitoring (Zabbix, Uptime Kuma, Grafana, healthcheck Docker).

### Enregistrement de machine depuis un outil externe

L'endpoint `POST /webhooks/new-machine` permet à un outil tiers (ticketing, CMDB) d'enregistrer automatiquement une machine dans OSIRIS. Il est idempotent : si la MAC est déjà connue, il renvoie les données existantes sans erreur.

```bash
curl -X POST https://osiris.local/webhooks/new-machine \
  -H "Authorization: Bearer osiris_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "mac": "aabbccddeeff",
    "hostname": "PC-DUPONT",
    "client": "Acme Corp",
    "os": "windows"
  }'
```

### Sécurité des comptes

#### 2FA TOTP

Chaque utilisateur peut activer la double authentification depuis l'icône paramètres (roue crantée en haut à droite). L'activation n'est pas obligatoire.

Flux d'activation :
1. OSIRIS génère un secret TOTP et affiche le QR code
2. L'utilisateur scanne avec Google Authenticator, Authy ou toute app compatible
3. Saisie d'un code de confirmation pour valider
4. A chaque connexion suivante : mot de passe + code à 6 chiffres

La désactivation requiert la saisie du mot de passe courant.

#### Clés API personnelles

Les clés API permettent à des outils externes d'interroger OSIRIS sans passer par le flux de connexion JWT :

```bash
# Lister les machines depuis un script ou un RMM
curl -H "Authorization: Bearer osiris_sk_..." https://osiris.local/machines

# Export CSV automatisé (cron, backup)
curl -H "Authorization: Bearer osiris_sk_..." https://osiris.local/machines/export > parc.csv

# Déclencher un redéploiement
curl -X POST https://osiris.local/machines/aabbccddeeff/redeploy \
  -H "Authorization: Bearer osiris_sk_..."
```

```powershell
# Depuis un script PowerShell ou ConnectWise Automate
$headers = @{ Authorization = "Bearer osiris_sk_..." }
$machines = Invoke-RestMethod "https://osiris.local/machines" -Headers $headers
```

```python
# Intégration Python (Zabbix, Make, script interne)
import requests
r = requests.get("https://osiris.local/machines",
    headers={"Authorization": "Bearer osiris_sk_..."})
```

Gestion depuis **Paramètres > Clés API** :
- Nommer chaque clé (ConnectWise, Grafana, Script backup...)
- La clé complète est affichée une seule fois à la création, stockée en SHA-256
- Date de dernière utilisation visible pour auditer les accès
- Révocation instantanée sans affecter les autres clés ni le compte

**L'onglet Intégrations** (Paramètres > Intégrations) génère automatiquement des snippets de code prêts à l'emploi pour : curl, PowerShell, Python, Grafana, Make/Zapier et la réception de webhooks inbound.

---

## Golden image (capture WIM)

Depuis l'onglet **Capture** :
1. Préparer le poste de référence (installer les logiciels, configurer Windows)
2. Dans OSIRIS, sélectionner la machine et nommer le fichier WIM
3. Cliquer "Lancer la capture" - la machine redémarre en PXE en mode capture
4. WinPE capture le disque via `wimlib-imagex` et dépose le WIM sur le partage Samba
5. Un toast confirme la fin de la capture

Le WIM est ensuite sélectionnable dans n'importe quel profil Windows via le navigateur WIM (bouton "Parcourir" dans le formulaire de profil).

Dépendance système : `sudo apt install wimtools`

---

## TeamViewer

Le mot de passe d'accès sans surveillance est généré automatiquement :
```
TV_PASSWORD = NOMHOTE_EN_MAJUSCULES + tv_suffix_du_profil
```
Exemple : profil avec `tv_suffix = @Osiris2026!`, machine `PC-COMPTA-01` -> mot de passe `PC-COMPTA-01@OSIRIS2026!`.

Le suffixe est stocké chiffré (Fernet) et jamais renvoyé en clair via l'API.

---

## Hyperviseurs

OSIRIS pilote plusieurs hyperviseurs en parallèle, de types différents. Le type
est porté par la fiche hyperviseur et détermine l'implémentation utilisée —
c'est le seul endroit où le choix se fait (`_PROVIDERS` dans `main.py`).

| Type | État | Authentification |
|---|---|---|
| `proxmox` | Complet : inventaire, création de VM (PXE, cloud-init, clone de template), Linux **et** Windows | Jeton d'API (`osiris@pve!osiris-token`) |
| `vsphere` | Inventaire + création de VM **Linux en cloud-init** — ni PXE, ni Windows (voir plus bas) | Compte de service + mot de passe, chiffré Fernet |

Le vocabulaire de l'interface est celui de Proxmox. Côté vSphere : un **nœud**
est un cluster de calcul, un **stockage** un datastore, un **réseau** un port group.

### Ajouter un second Proxmox

Rien à développer : créer la fiche dans Administration › Infrastructure. Il faut
que le pare-feu laisse passer OSIRIS vers le port **8006** du cluster, et un jeton
d'API dont le rôle porte :

| Privilège | Ce qu'OSIRIS en fait |
|---|---|
| `VM.Allocate` | créer et détruire les VM |
| `VM.Clone` | cloner un template (modes `template` et `cloudinit`) |
| `VM.Config.*` | matériel, réseau, ordre de démarrage, redimensionnement de disque |
| `VM.PowerMgmt` | démarrer, arrêter, cycler l'alimentation |
| `VM.Snapshot` + `VM.Snapshot.Rollback` | snapshots depuis la fiche d'une machine |
| `VM.Monitor`, `VM.Audit` | lire l'état et la configuration des VM |
| `Datastore.AllocateSpace`, `Datastore.Audit` | disques des VM créées |
| `Datastore.AllocateTemplate` | déposer l'ISO WinPE (déploiement Windows sur VM) |
| `Datastore.Allocate` | **remplacer** une ISO WinPE périmée — `download-url` refuse d'écraser, il faut donc supprimer l'ancienne |
| `Sys.Audit` | version et inventaire des nœuds |
| `Sys.AccessNetwork` | fait télécharger l'ISO WinPE par le nœud (`download-url`) |

⚠️ **Aucun rôle intégré ne porte `Sys.AccessNetwork` hors `Administrator`** : il
faut créer un rôle sur mesure.

#### Borner le périmètre : le pool

`Sys.AccessNetwork` et `Sys.Audit` doivent être attribués **sur `/`**, ce qui pousse
naturellement à y mettre *tout* le rôle. Mais `VM.Allocate` sur `/` donne droit de
vie et de mort sur **chaque VM du cluster**, celles qu'OSIRIS n'a pas créées
comprises. Le rayon d'action d'une erreur devient alors l'infrastructure entière.

En pratique, avec les rôles intégrés, cela donne quatre attributions pour
`osiris@pve` — et **c'est le chemin de la première qui compte** :

| Chemin | Rôle | Pourquoi |
|---|---|---|
| `/pool/osiris` | `PVEVMAdmin` | tout ce qui écrit sur une VM, **borné au pool** |
| `/pool/osiris` | `PVEPoolAdmin` | `Pool.Audit` pour lire le pool, `Pool.Allocate` pour y ranger une VM à la création |
| `/` | `PVEAuditor` | lecture de l'inventaire : nœuds, VM, configurations |
| `/storage` | `PVEDatastoreUser` | `Datastore.AllocateSpace` pour les disques des VM créées |
| `/storage/<iso>` | `PVEDatastoreAdmin` | déposer **et remplacer** l'ISO WinPE |
| `/` | rôle sur mesure à `Sys.AccessNetwork` | fait télécharger l'ISO par le nœud |

⚠️ **`PVEPoolAdmin` n'est pas optionnel, et la raison est contre-intuitive** : dans
Proxmox, une ACL sur un chemin **plus spécifique REMPLACE** celle héritée du parent,
elle ne s'y ajoute pas. Poser `PVEVMAdmin` sur `/pool/osiris` **retire** donc le
`Pool.Audit` que `PVEAuditor` accordait sur `/`, et OSIRIS ne peut plus lire son
propre pool — `Permission check failed (/pool/osiris, Pool.Audit)`, alors que le
privilège *paraît* accordé plus haut. Constaté sur les deux clusters le 2026-08-10.
Deux rôles sur le même chemin, eux, se cumulent bien.

`PVEVMAdmin` sur **`/vms`** — la configuration spontanée — donne ces droits sur
**chaque VM du cluster**. Sur `/pool/osiris`, l'hyperviseur refuse lui-même toute
écriture hors du pool : c'est la même garantie que le contrôle d'identité côté code
(ci-dessous), mais rendue par la plateforme, donc valable même en cas de bug
d'OSIRIS. La lecture, elle, reste cluster-wide via `PVEAuditor` — le contrôle
d'identité en a besoin pour comparer l'UUID d'une VM avant d'y toucher.

Quatre pièges à la bascule :

- **les templates clonés doivent être dans le pool** : le clone exige `VM.Clone` sur
  la VM **source**, et un template hors pool fait échouer tout déploiement. Cela vaut
  pour **chaque template créé plus tard** : un cluster dont le pool est vide
  aujourd'hui parce qu'il n'a pas encore de template reste piégé le jour où on lui en
  fabrique un. Le symptôme est un « Permission check failed » sur le clone, qui ne
  nomme ni le pool ni le template ;
- **les VM déjà créées par OSIRIS aussi**, sans quoi il perd la main sur son parc ;
- **la VM d'OSIRIS elle-même, surtout pas** — elle n'a aucune raison de pouvoir
  s'éteindre ou se détruire ;
- **le bouton « Tester » de l'interface ne prouve rien** de cette bascule : il ne fait
  qu'un `GET /version`, couvert par `PVEAuditor`. Il reste vert même si tout le reste
  est cassé.

Pour valider la bascule sans rien casser, le test symétrique : réécrire la
**description** d'une VM avec **sa valeur actuelle**. L'opération est idempotente — état
final identique à l'état initial — mais Proxmox contrôle `VM.Config.Options` *avant*
d'écrire. Refusée, rien n'a été tenté ; acceptée, rien n'a changé. À jouer dans les deux
sens : une VM **du pool** doit l'accepter, une VM **hors pool** doit la refuser. Ne
tester qu'un seul côté ne prouve que la moitié.

⚠️ `GET /access/permissions?path=/vms/<vmid>` ne convient que pour le côté « hors
pool » : cette route ne calcule que les droits liés au chemin et **ignore
l'appartenance à un pool**, que Proxmox résout au moment du contrôle. Elle annonce donc
« aucun droit » sur une VM du pool parfaitement accessible. Pour l'appartenance, lire
`GET /pools/<pool>`.

#### Le contrôle d'identité des VM

Un identifiant de VM Proxmox **n'est pas une identité** : `cluster/nextid` rend le
plus petit numéro libre, donc les numéros sont recyclés. Une VM supprimée à la main
sans retirer sa fiche OSIRIS laisse un numéro qui repart au tourniquet, et la fiche
se met à désigner la VM de quelqu'un d'autre.

OSIRIS ancre donc chaque fiche sur l'**UUID SMBIOS** de sa VM (`machine.vm_uuid`) et
le compare avant toute écriture. Si le numéro désigne une autre VM, l'action est
refusée avec une erreur **409**, inscrite à l'audit sous `vm_identite_refusee`, et
**rien n'est touché**. Il faut alors vérifier la VM dans l'interface Proxmox, puis
corriger ou supprimer la fiche.

Les fiches antérieures à ce mécanisme n'ont pas d'UUID : elles sont identifiées par
le **nom** de la VM, et l'UUID relu est gravé au premier contrôle réussi. Renommer
une VM à la main dans Proxmox avant ce premier contrôle fait donc refuser l'action —
c'est volontaire, et il suffit de rétablir le nom ou de recréer la fiche.

#### Le certificat TLS

La vérification est **activée par défaut**. Le jeton peut détruire des VM : sur une
session non vérifiée, il suffit de se placer sur le chemin OSIRIS↔hyperviseur pour
le récolter. La désactiver reste possible — Proxmox s'installe avec un certificat
auto-signé — mais chaque appel laisse alors un avertissement dans le journal, et la
fiche porte un badge « TLS non vérifié ».

### Déployer sur plusieurs réseaux : l'URL de rappel

Les scripts de premier démarrage gravent l'adresse d'OSIRIS. Une VM qui ne peut
pas la joindre télécharge son script puis **ne rappelle plus personne** : elle
reste « en attente » sans que rien n'explique pourquoi.

Chaque hyperviseur porte donc un champ **URL de rappel** (`callback_url`), qui
remplace `OSIRIS_BASE_URL` pour les VM créées dessus. Vide = adresse globale.
À renseigner dès qu'un site voit OSIRIS à une autre adresse (NAT, interconnexion,
seconde patte réseau).

Le VLAN, lui, se choisit VM par VM : le formulaire liste les bridges du nœud. Il
faut seulement que le réseau retenu sache router vers l'URL de rappel, et que le
pare-feu laisse passer le HTTP.

**En mode PXE**, il faut en plus que le VLAN soit sur le même domaine de diffusion
DHCP qu'OSIRIS, ou disposer d'un relais (`ip-helper`) qui pointe vers lui — le
DHCP et le TFTP ne se routent pas d'eux-mêmes. Le mode cloud-init n'a pas cette
contrainte : il ne demande que du HTTP, ce qui en fait la voie naturelle pour
déployer sur un site distant.

### vSphere : ce qui marche, et ce qui n'existe pas

Le clonage passe par **pyvmomi (SOAP)** : l'API REST n'expose le clone qu'à partir
de vSphere 8, et le vCenter cible est en 6.7. La configuration est injectée en
`guestinfo.userdata` — l'équivalent vSphere des snippets, sans le blocage d'upload
rencontré sur Proxmox.

**Ce qui est implémenté** : inventaire (clusters, datastores, port groups,
templates), création d'une VM Linux par clone de template en mode `cloud-init`,
disque de données, adressage fixe, destruction.

**Ce qui ne l'est pas :**

- **Le mode PXE**, et il n'a pas de sens ici : le réseau de déploiement d'OSIRIS
  n'est pas routable jusqu'au vCenter (DHCP et TFTP ne se routent pas).
- **Windows**, qui se déploie par une ISO WinPE — le dépôt d'ISO n'existe pas dans
  `vsphere.py`.
- **La MAC imposée** : vCenter l'attribue lui-même. OSIRIS clone d'abord, relit la
  MAC obtenue, puis écrit le `guestinfo` — dont le contenu dépend de cette MAC.

Prérequis :

- **Compte de service** avec, sur le datacenter cible : lecture de l'inventaire,
  `Virtual machine.Provisioning.Clone`, `Virtual machine.Configuration.*`,
  `Virtual machine.Interaction.Power On`, `Virtual machine.Inventory.Delete`,
  `Resource.Assign VM to resource pool`, `Datastore.Allocate space`.
- **Port 443** ouvert depuis OSIRIS vers le vCenter.
- **Cible de déploiement** : noms du datacenter, du cluster, du datastore et du
  port group.
- **Un template Linux cloud-init** (l'équivalent du 9000 côté Proxmox).

Comme sur Proxmox, restreindre le compte au **dossier et au pool de ressources**
d'accueil plutôt qu'au datacenter entier borne le rayon d'action d'une erreur.
vCenter ne recycle pas ses moID comme Proxmox recycle ses VMID, donc le risque de
viser une VM étrangère y est plus faible — mais la destruction vérifie tout de même
le nom de la VM avant d'agir (`destroy_vm`), un `Destroy_Task` ne se rattrapant pas.

---

## Gabarit matériel des serveurs

Un profil porte les caractéristiques des VM créées avec lui : vCPU, RAM, disque
système, et disque de données. Choisir le profil dans le formulaire de création
reprend ces valeurs, qui restent modifiables — le profil sait ce que demande ce
type de serveur, l'opérateur garde la main.

Le **disque de données** est un second disque, laissé vierge par l'hyperviseur et
formaté au premier démarrage, monté sur `/data` **par UUID** (l'ordre des disques
n'est pas stable d'un démarrage à l'autre). Le script ne touche qu'un disque
**sans table de partition ni système de fichiers** : jamais le disque système,
jamais un disque déjà formaté — un redéploiement n'écrase pas les données.

### Adressage IP des VM

À la création d'une VM, les champs **IP / passerelle / DNS** sont facultatifs :
laissés vides, la machine reste en DHCP. Renseignés, cloud-init applique
l'adresse au premier démarrage — `ipconfig0` sur Proxmox, configuration réseau
`guestinfo` sur vSphere. Même réglage, deux véhicules.

C'est indispensable sur un **VLAN serveur**, qui n'a généralement pas de DHCP.
Sans adresse, la VM démarre, tourne, et ne rappelle jamais OSIRIS : elle reste
« en attente » sans qu'aucun message n'explique pourquoi. Avec une adresse
imposée, soit elle répond, soit la configuration est fausse et ça se voit.

L'adresse est conservée sur la fiche machine : l'inventaire OSIRIS sait donc
où joignent les serveurs qu'il a déployés.

### Mot de passe root de secours

Option de profil `set_root_password`. Au premier démarrage, la machine tire un
mot de passe aléatoire, l'envoie à OSIRIS, et **ne le pose que si OSIRIS confirme
l'avoir enregistré** — dans l'autre ordre, un rappel qui échoue laisserait un root
dont plus personne n'a le mot de passe.

C'est un accès **console** : root reste interdit en SSH sur les profils serveur.
Le mot de passe est stocké chiffré et s'affiche dans la fiche machine, au même
endroit que LAPS sous Windows.

---

## VM Linux : template d'amorçage générique

Une VM clonée depuis un template n'a pas d'installeur pour recevoir sa configuration :
il faut un mécanisme qui, au premier démarrage, aille la demander à OSIRIS. Ce mécanisme
est **cuit une fois dans le template** et **ne contient aucun identifiant** — il sait
seulement lire sa propre MAC et appeler OSIRIS.

Sur la VM qui servira de template, en root :

```bash
# Installe /usr/local/sbin/osiris-bootstrap.sh + osiris-firstboot.service
curl -sf http://osiris.local:8000/bootstrap/linux | bash

# Puis, juste avant de convertir la VM en template :
curl -sf http://osiris.local:8000/bootstrap/linux | bash -s -- --seal
```

`--seal` remet à zéro `machine-id`, les clés d'hôte SSH et l'état cloud-init. **Sans ça,
tous les clones partagent le même `machine-id`, donc le même DUID DHCP, et se volent
leurs baux.**

Au démarrage de chaque clone, l'unité `osiris-firstboot.service` :

1. énumère les MAC des cartes **physiques** (`/sys/class/net/*/device`) ;
2. appelle `GET /firstboot-linux/<mac>` pour chacune, jusqu'à obtenir un 200 ;
3. poste `status=deploying`, exécute le script reçu, qui pose le nom d'hôte, installe
   les applications du profil, joint le domaine, configure la supervision, lance les
   smoke tests puis poste `status=deployed` ;
4. le script désactive l'unité — **et lui seul**. Une VM démarrée avant que sa fiche
   existe côté OSIRIS retente donc au démarrage suivant au lieu de rester orpheline.

Ce script d'amorçage ne contient **aucune logique métier** : tout vient d'OSIRIS au
démarrage. Un changement de profil, d'application ou de script de premier démarrage
**ne nécessite pas de refabriquer le template**.

---

## Supervision Zabbix

Deux réglages, l'un par organisation, l'autre par machine :

| Où | Champ | Effet |
|---|---|---|
| Administration › Organisations | `zabbix_server` | Adresse du serveur ou proxy qui collecte cette organisation. Vide = aucune supervision. |
| Fiche machine | `supervised` | Coché par défaut. Décocher exclut la machine sans toucher à l'organisation. |

L'agent n'est installé que si **les deux** conditions sont réunies : un agent sans
collecteur à qui parler serait muet.

Le premier démarrage installe `zabbix-agent2` (ou `zabbix-agent` à défaut) depuis les
dépôts de la distribution, puis écrit un fichier à part —
`/etc/zabbix/zabbix_agent2.d/osiris.conf` — qu'une mise à jour du paquet n'écrase pas :

```
Server=<zabbix_server>
ServerActive=<zabbix_server>
Hostname=<nom d'hôte de la machine>
HostMetadata=osiris linux <slug de l'organisation>
```

**Mode actif** : c'est l'agent qui sort vers le collecteur en **TCP 10051**. Le collecteur
ne joint jamais la machine, ce qui convient à un VLAN isolé — un seul flux sortant à
autoriser, pour tout le sous-réseau.

`HostMetadata` est là pour l'**auto-enregistrement** côté Zabbix : une action qui filtre
sur `osiris linux` crée l'hôte et lui applique le bon modèle sans intervention.

Deux smoke tests remontent dans la fiche machine : l'agent tourne, et le collecteur est
joignable en 10051. Le second teste la **règle de pare-feu**, ce qui distingue un agent
mal configuré d'un flux bloqué.

---

## Post-installation des paquets Linux

`Application.linux_post_install` est un script bash exécuté en root **juste après**
l'`apt-get install` du paquet, pendant le premier démarrage. Pendant Linux de
`installer_config_file`, qui est exclusivement Windows.

Il s'édite dans Administration › Applications (bouton 🐧 sur les applications qui ont un
paquet apt). Sans lui, OSIRIS savait poser un paquet mais pas le configurer.

```bash
# Exemple sur nginx
rm -f /etc/nginx/sites-enabled/default
systemctl reload nginx
```

Une erreur dans ce script n'interrompt pas le déploiement : elle est journalisée dans
`/var/log/osiris-firstboot.log` et la suite continue.

---

## Modèle de données

```
Organization          User                    Profile
------------          ----                    -------
id / name / slug      id / email              id / name / os
webhook_url           hashed_password         locale / keyboard / timezone
zabbix_server
                      role (admin|tech)       default_user / extra_packages
                      totp_secret (Fernet)    join_domain / domain
                                              domain_join_user/password (Fernet)
                      ApiKey[]                domain_config_id -> DomainConfig
                                              win_image / win_index
                                              enable_bitlocker / bitlocker_pin
                                              network_drives (JSON)
                                              printers (JSON)
                                              post_script
                                              tv_suffix (Fernet)
                                              app_ids -> Application[]
                                              laps_rotation_days

Machine               DomainConfig            Application
-------               ------------            -----------
id / mac / hostname   id / name               id / name
client / os / ou      organization_id         winget_id (Windows)
status / deployed_at  domain                  apt_package (Ubuntu)
organization_id       join_user               category / icon
profile_id            join_password (Fernet)
hw_serial / hw_model  default_ou              linux_post_install
hw_ram_gb
bitlocker_key (Fernet)
bitlocker_pin (Fernet)
laps_password (Fernet)
laps_rotated_at
user_name / user_email
supervised
notes
smoke_status / smoke_results
```

---

## Rôles

| Rôle | Peut faire |
|---|---|
| `admin` | Tout : organisations, utilisateurs, profils, machines, drivers, captures, clés API |
| `technician` | Enregistrer et consulter des machines, pas supprimer ni accéder à l'admin |

---

## Fichiers à fournir manuellement

Les binaires et images ISO ne sont pas inclus dans le dépôt. A placer dans `backend/static/` :

| Fichier | Source |
|---|---|
| `wimboot` | github.com/ipxe/wimboot/releases |
| `curl.exe` (Windows 8.x) | curl.se/windows |
| `installers/DellBIOSProvider.zip` | PowerShell Gallery — voir ci-dessous |
| `installers/zabbix-agent2.deb` | zabbix.com — voir ci-dessous |

### Module DellBIOSProvider (mot de passe BIOS Dell)

Nécessaire seulement si une organisation a un mot de passe BIOS renseigné. Le module
est **servi par OSIRIS** plutôt qu'installé depuis PSGallery sur chaque poste : le
PowerShellGet livré en boîte avec Windows 11 est en 1.0.0.1, qui ne connaît pas
`-AcceptLicense` et n'amorce pas le fournisseur NuGet en session non interactive.

```bash
curl -sSL -o /tmp/dbp.nupkg https://www.powershellgallery.com/api/v2/package/DellBIOSProvider
mkdir -p /tmp/dbp && cd /tmp/dbp && unzip -q /tmp/dbp.nupkg
rm -rf _rels package '[Content_Types].xml' *.nuspec     # metadonnees NuGet inutiles
zip -qr backend/static/installers/DellBIOSProvider.zip .
```

Le firstboot le télécharge, le décompacte dans `%ProgramFiles%\WindowsPowerShell\Modules\`
et l'importe — sans accès Internet depuis le poste du client.

### Agent Zabbix (supervision des VM Linux)

Nécessaire seulement si une organisation a un collecteur Zabbix renseigné.

**Ubuntu 24.04 « noble » ne fournit plus d'agent Zabbix** — le paquet a été retiré des
dépôts (vérifié le 2026-08-05 ; seul `pcp-export-zabbix-agent`, qui est autre chose,
subsiste). Le firstboot essaie donc d'abord les dépôts de la distribution — Debian les
fournit encore — puis retombe sur le paquet **servi par OSIRIS**, comme le MSI WithSecure
et le module DellBIOSProvider côté Windows.

Aucun dépôt tiers n'est ajouté aux machines : elles n'ont pas à joindre `repo.zabbix.com`
depuis le réseau du client, souvent filtré. Seules les dépendances viennent des dépôts de
la distribution.

Récupérer le paquet correspondant à la distribution déployée sur
[zabbix.com/download](https://www.zabbix.com/download) (section *Agent*, paquet
`zabbix-agent2` pour Ubuntu 24.04), puis :

```bash
cp zabbix-agent2_*_amd64.deb backend/static/installers/zabbix-agent2.deb
```

Le nom de fichier est **fixe** : le firstboot ne connaît pas le numéro de version. Pour
mettre à jour l'agent, il suffit de remplacer ce fichier — aucun template de VM n'est à
refabriquer.

### Images Ubuntu

Les machines Ubuntu bootent via NFS (pas de téléchargement ISO en RAM) :

```bash
sudo apt install nfs-kernel-server xorriso
sudo mkdir -p /srv/nfs/ubuntu-24.04
sudo xorriso -osirrox on -indev ubuntu-24.04.iso -extract / /srv/nfs/ubuntu-24.04

# Extraire kernel + initrd pour iPXE
sudo xorriso -osirrox on -indev ubuntu-24.04.iso \
  -extract /casper/vmlinuz backend/static/vmlinuz \
  -extract /casper/initrd  backend/static/initrd

echo "/srv/nfs/ubuntu-24.04 *(ro,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -ra
```

### Images Windows

Les fichiers Windows sont servis via Samba (requis : protocole NT1 pour WinPE) :

```ini
# smb.conf (serveur de fichiers OSIRIS, pas le DC Samba)
[windows]
   path = /srv/data/windows
   read only = yes
   guest ok = yes
   min protocol = NT1
   ntlm auth = yes
```

### Pilotes réseau pour WinPE

WinPE ne dispose que des pilotes *inbox* de l'ISO Windows. Sur une machine dont la
carte réseau n'est pas reconnue (ThinkPad T15, Realtek récentes…), WinPE démarre
**sans réseau** et le déploiement se bloque — sans pouvoir aller chercher le pilote
sur le partage, puisqu'il faut justement le réseau pour ça.

Pour ajouter un pilote, déposer ses fichiers (INF + SYS + CAT) dans :

```
/srv/data/windows/winpe-drivers/net/<nom-du-pilote>/
```

Rien d'autre à faire : OSIRIS les passe à wimboot au démarrage PXE, qui les dépose
dans `\Windows\System32\` de l'image démarrée, et `startnet.cmd` fait le `drvload`
avant `wpeinit`. **`boot.wim` n'est jamais modifié** — l'y avoir baké un dossier
`\drivers\` produisait un WIM que wimboot ne démarrait plus. Un pilote ajouté est
donc actif au boot suivant, sans régénérer la moindre image.

⚠️ `\Windows\System32` est un espace de noms plat : deux pilotes ne peuvent pas
avoir de fichiers de même nom. OSIRIS ignore le doublon et le signale dans les logs
de l'API.

### Choix du pack de pilotes par identifiant matériel

Le nom commercial ne désigne pas une machine sans ambiguïté : un **ThinkPad T15**
(Machine Type 20S6/20S7) et un **ThinkPad T15g** (20UR/20US) sont deux machines
différentes que sépare une seule lettre — et se tromper de pack, c'est un poste
livré sans pavé tactile ni WiFi.

Les trois constructeurs publient un identifiant matériel, que OSIRIS enregistre sur
chaque pack (colonne `hw_ids`, remplie à la synchro du catalogue) :

| constructeur | champ du catalogue | exemple |
|---|---|---|
| Dell   | `systemID`  | `092f` |
| HP     | `SystemId` (carte mère) | `81c3,8396` |
| Lenovo | `Types` (Machine Type)  | `20s6,20s7` |

Côté machine, WinPE remonte `Win32_ComputerSystemProduct.Name` au moment de
l'identification. **Cette valeur n'a pas la même nature selon le constructeur**, et
c'est tout l'enjeu :

- chez **Lenovo**, c'est le MTM (`20S6CTO1WW`), dont les 4 premiers caractères sont
  le Machine Type → il se compare directement à `hw_ids` ;
- chez **Dell et HP**, c'est le **nom commercial** (`Dell Pro 14 Plus PB14250`), qui
  ne ressemble en rien au code stocké dans `hw_ids` (`0cf9`) → aucune correspondance
  possible par identifiant.

OSIRIS résout donc le pack dans cet ordre, et s'arrête au premier qui répond :

1. le pack **choisi à la main** sur la fiche machine — toujours prioritaire ;
2. l'**identifiant matériel** (`hw_ids`), qui seul sépare un T15 d'un T15g ;
3. le **nom commercial**, rapproché de `model_key` — c'est ce qui couvre Dell et HP ;
4. à défaut, le dossier `drivers/` complet (~36 Go) : lent, mais il ne manque jamais
   un pilote.

Le rapprochement par nom (étape 3) est volontairement **strict** : égalité, ou l'un
préfixe de l'autre. `/drivers/suggest` se permet d'être plus souple parce qu'un humain
valide sa proposition ; ici l'injection est silencieuse. DISM n'installant que les
`.inf` dont l'identifiant matériel correspond, un pack « presque bon » ne casse rien —
il installe des pilotes **incomplets**, et le périphérique muet ne se découvre qu'à la
livraison. Dans le doute, mieux vaut donc l'étape 4.

---

## Caddyfile - routes requises

Routes à configurer dans le bloc HTTPS de votre Caddyfile :

```
handle /auth/*          { reverse_proxy localhost:8000 }
handle /machines*       { reverse_proxy localhost:8000 }
handle /organizations*  { reverse_proxy localhost:8000 }
handle /users*          { reverse_proxy localhost:8000 }
handle /profiles*       { reverse_proxy localhost:8000 }
handle /images*         { reverse_proxy localhost:8000 }
handle /audit-logs*     { reverse_proxy localhost:8000 }
handle /dashboard*      { reverse_proxy localhost:8000 }
handle /domain-configs* { reverse_proxy localhost:8000 }
handle /apps*           { reverse_proxy localhost:8000 }
handle /capture*        { reverse_proxy localhost:8000 }
handle /drivers*        { reverse_proxy localhost:8000 }
handle /wims*           { reverse_proxy localhost:8000 }
handle /webhooks*       { reverse_proxy localhost:8000 }
handle /health*         { reverse_proxy localhost:8000 }
handle /docs*           { reverse_proxy localhost:8000 }
handle /openapi.json    { reverse_proxy localhost:8000 }
handle /ws/*            { reverse_proxy localhost:8000 }
```

Le bloc HTTP (celui que les machines en déploiement appellent, sans TLS) doit en plus
laisser passer `/bootstrap/*` et `/firstboot-linux/*`, à côté des routes PXE existantes —
sans quoi une VM clonée ne peut ni s'amorcer ni récupérer son script de premier démarrage.

En Docker Compose, le `Caddyfile.docker` inclus utilise `backend:8000` comme upstream et ajoute `tls internal` (certificat auto-signé géré par Caddy).

---

## Sécurité

| Mesure | Détail |
|---|---|
| Auth JWT | Toutes les routes API exigent un Bearer token signé (HS256) |
| Clés API | Format `osiris_sk_...` - stockées en SHA-256, jamais récupérables en clair |
| 2FA TOTP | Secret chiffré Fernet en base, token temporaire 5 min entre mot de passe et code |
| Secrets chiffrés | Mots de passe AD, BitLocker, LAPS, PIN, suffixe TV : Fernet (AES-128-CBC) |
| Validation MAC | Regex stricte `^[0-9a-f]{12}$` - injection iPXE impossible |
| Echappement XML | `xml.sax.saxutils.escape` sur tous les champs injectés dans unattend.xml |
| Hachage mots de passe | bcrypt pour les users - sha512_crypt 100k rounds pour les machines |
| CORS restreint | Origines explicitement listées dans `.env` |
| Rate limiting | `/auth/login` : 5/min - `/boot` : 30/min - endpoints publics : 10/min |

**Risques résiduels documentés :**
- **Spoofing MAC** - iPXE identifie les machines uniquement par MAC. Mitigation : VLAN PXE dédié.
- **Scripts en HTTP clair** - les scripts de boot transitent sans chiffrement sur le réseau PXE. Acceptable sur réseau interne isolé.
- **Endpoints firstboot sans auth** - `/machines/{mac}/status`, `/hardware`, `/laps-password`, `/laps-due`, `/bitlocker-key`, `/smoke-tests` sont appelés par la machine elle-même. La MAC est le seul identifiant. Acceptable sur réseau PXE interne isolé.

---

## Architecture multi-tenant

OSIRIS utilise une **base partagée, schéma partagé** (row-level) : toutes les machines sont dans la même table, chaque ligne porte un `organization_id`. C'est adapté à un MSP où l'équipe technique voit tous les clients.

**Pour une isolation par client (portail self-service)**, il faudrait ajouter `organization_id` sur `User`, l'inclure dans le JWT, et appliquer `WHERE organization_id = current_user.org_id` sur toutes les requêtes machines. PostgreSQL Row Level Security est disponible pour une isolation inviolable au niveau base de données.

---

*Projet fair-source - voir [LICENSE](LICENSE). Usage interne et MSP libre, revente ou hébergement SaaS du logiciel interdits sans accord.*
