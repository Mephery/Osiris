# OSIRIS - Serveur de déploiement réseau

OSIRIS est un serveur de déploiement PXE pensé pour les équipes d'infogérance.
Il remplace les outils comme MDT/WDS avec une interface web moderne, une API REST et une automatisation complète du cycle de vie des postes.

> **Statut :** Production-ready en environnement lab : Windows 11 et Ubuntu 24.04 LTS validés bout-en-bout.

**Philosophie :** brancher un câble RJ45 suffit. La machine PXE-boot, OSIRIS la déploie, configure TeamViewer, installe les apps, joint le domaine, tout depuis l'interface.

---

## Fonctionnalités

| Fonctionnalité | Windows | Ubuntu | Debian |
|---|---|---|---|
| Déploiement PXE automatique | WinPE + wimboot | cloud-init / subiquity | preseed |
| Partitionnement GPT automatique | oui | oui | oui |
| Jonction domaine AD automatique | oui (unattend specialize) | en cours (sssd prévu) | - |
| Sélecteur d'applications (winget / apt) | 20 apps | 20 apps | - |
| Configuration TeamViewer automatique | oui (firstboot.ps1) | oui (firstboot.sh) | - |
| Barre de progression DISM temps réel | oui | - | - |
| Drivers Dell (catalogue constructeur) | oui | - | - |
| Drivers HP / Lenovo | en cours | - | - |
| Wake-on-LAN | oui | oui | oui |
| Déploiement en lot | oui | oui | oui |
| Historique de déploiement par machine | oui | oui | oui |
| Notifications webhook (Teams / Slack) | oui | oui | oui |
| Capture golden image | oui (WIM) | en cours | - |
| Navigateur WIM | oui | - | - |
| Import CSV machines | oui | oui | oui |

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
 Premier démarrage
     |  Windows : firstboot-windows.ps1.j2 (winget, TeamViewer, callback)
     |  Ubuntu  : firstboot-ubuntu.sh.j2  (apt, TeamViewer, callback)
     v
 Statut mis à jour en temps réel via WebSocket dans l'interface
 Webhook envoyé si une URL est configurée sur l'organisation
```

---

## Pile technique

| Composant | Technologie |
|---|---|
| Backend | Python 3.11 - FastAPI - SQLModel |
| Base de données | PostgreSQL |
| File de tâches | ARQ - Redis |
| Proxy | Caddy (HTTPS auto via mkcert en local) |
| Frontend | React 19 - TypeScript - Tailwind CSS v4 - sonner |
| Auth | JWT (python-jose) - bcrypt (passlib) |
| Boot réseau | iPXE - dnsmasq (DHCP/TFTP) |
| Autoinstall Ubuntu | cloud-init / subiquity |
| Autoinstall Windows | WinPE - wimboot - unattend.xml |
| Partage fichiers Windows | Samba (NT1 pour WinPE) |
| Drivers constructeurs | Dell (catalogue XML) / HP / Lenovo |
| Apps Windows | winget (firstboot) |
| Apps Ubuntu | apt (cloud-init packages + firstboot) |

---

## Installation

### Prérequis

- Python 3.11+
- Node.js 22+
- PostgreSQL 14+
- Redis
- Un serveur DHCP configuré pour pointer vers OSIRIS (`next-server` + `filename`)

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Éditer .env avec vos valeurs (voir section Variables d'environnement)

python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Au premier démarrage, OSIRIS crée automatiquement :
- Un compte admin depuis `ADMIN_EMAIL` / `ADMIN_PASSWORD`
- Deux profils par défaut (Ubuntu + Windows)
- 20 applications courantes dans le catalogue (Chrome, Firefox, VLC, Office 365, Acrobat, VS Code...)

**Changez le mot de passe admin immédiatement** (via l'UI ou l'API).

### Frontend

```bash
cd frontend
cp .env.example .env
# Éditer VITE_API_URL avec l'IP/URL de votre backend

npm install
npm run build   # production -> dist/ servi par Caddy
```

---

## Variables d'environnement

### `backend/.env`

```env
# PostgreSQL
DB_USER=osiris_user
DB_PASSWORD=votre_mot_de_passe
DB_HOST=localhost
DB_NAME=osiris

# JWT - générer avec : python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=changeme

# Compte admin créé au premier démarrage (si aucun user en base)
ADMIN_EMAIL=admin@osiris.local
ADMIN_PASSWORD=changeme

# Réseau PXE - IP vue par les machines qui bootent (pas l'IP d'accès à l'UI !)
OSIRIS_BASE_URL=http://10.0.0.1:8000
OSIRIS_IP=10.0.0.1

# CORS - origines autorisées pour le frontend (séparées par des virgules)
ALLOWED_ORIGINS=https://osiris.local,http://192.168.1.x:5173

# Clé SSH publique déposée sur chaque Ubuntu déployé (optionnel)
OSIRIS_SSH_PUBKEY=

# Chemin local du partage Windows (pour le navigateur WIM)
WIN_SHARE_PATH=/srv/data/windows
```

### `frontend/.env`

```env
VITE_API_URL=https://osiris.local
```

> **Note réseau :** `OSIRIS_BASE_URL` doit être l'IP du réseau PXE (celle que voient les machines qui bootent). Ne pas confondre avec l'URL d'accès à l'UI.

---

## Modèle de données

```
Organization          User                    Profile
------------          ----                    -------
id                    id                      id / name / os
name / slug           email                   locale / keyboard / timezone
webhook_url           hashed_password         default_user / extra_packages
                      role (admin|tech)       join_domain / domain
                                              domain_join_user/password (Fernet)
                                              win_image / win_index
                                              tv_suffix (Fernet)
                                              app_ids -> Application[]

Machine               DeploymentEvent         Application
-------               ---------------         -----------
id / mac / hostname   id / mac                id / name
client / os / ou      hostname / status       winget_id (Windows)
status / deployed_at  os / profile_name       apt_package (Ubuntu)
organization_id       timestamp               category / icon
profile_id
```

---

## Rôles

| Rôle | Peut faire |
|---|---|
| `admin` | Tout : organisations, utilisateurs, profils, machines, drivers, captures |
| `technician` | Enregistrer et consulter des machines, pas supprimer ni accéder à l'admin |

---

## Déploiement en lot

Depuis l'onglet **Machines**, cochez les machines cibles (checkbox par ligne ou "tout sélectionner"), puis utilisez la barre d'actions :
- **Redéployer** - passe toutes les machines sélectionnées en `pending`. Elles redéploieront au prochain boot PXE.
- **WoL** - envoie un magic packet Wake-on-LAN à chacune pour les démarrer à distance.

Combinaison typique : cocher N machines -> WoL -> Redéployer -> surveiller la progression via les barres de statut en temps réel.

---

## Import CSV

Bouton "Importer CSV" dans la barre du tableau machines. Format attendu (encodage UTF-8 ou UTF-8-BOM pour les fichiers Excel) :

```
mac,hostname,client,os,profile_name
aa:bb:cc:dd:ee:ff,PC-DUPONT,Acme Corp,windows,Windows -- par défaut
11:22:33:44:55:66,SRV-LINUX,Acme Corp,ubuntu,Ubuntu -- par défaut
aa:bb:cc:11:22:33,PC-MARTIN,Autre Client,debian,
```

Les machines déjà enregistrées (même MAC) sont ignorées silencieusement. `profile_name` est optionnel.

---

## Sélecteur d'applications

Dans chaque **Profil**, vous pouvez sélectionner les applications à installer automatiquement :
- **Windows** : installées via `winget` dans `osiris-firstboot.ps1` (premier démarrage)
- **Ubuntu** : installées via `apt` dans `osiris-firstboot.sh` (premier boot via systemd oneshot)

20 applications disponibles dans le catalogue : Chrome, Firefox, Signal, Audacity, VLC, LibreOffice, Nextcloud Client, Bitwarden, 7-Zip, Java OpenJDK 21, .NET Runtime 8, VS Code, MS Office 365, Adobe Acrobat Reader, TeamViewer, Slack, Zoom, Notepad++, WinRAR, Git.

---

## Historique de déploiement

Chaque machine conserve un journal des transitions de statut (pending, deploying, deployed, failed). Cliquer sur le chevron d'une ligne dans le tableau machines affiche :
- Les logs temps réel de la session en cours (via WebSocket)
- L'historique des 20 derniers événements (date, statut, OS, profil utilisé)

---

## Notifications webhook

Dans Admin -> Organisations, chaque organisation dispose d'un champ "Webhook URL". Quand un déploiement se termine (statut `deployed` ou `failed`), OSIRIS envoie automatiquement un message HTTP POST au format :

```json
{"text": "PC-DUPONT déployé avec succès (WINDOWS - Acme Corp)"}
```

Ce format est directement compatible avec :
- Teams (Incoming Webhook)
- Slack (Incoming Webhook)
- Discord (Webhook, ajouter `/slack` à la fin de l'URL Discord)

Les échecs d'envoi sont silencieux et ne bloquent pas le déploiement.

---

## Golden image (capture WIM)

Depuis l'onglet **Images**, section "Capturer une golden image" :
1. Préparer le poste de référence (installer les logiciels, configurer Windows)
2. Dans OSIRIS, sélectionner la machine de référence et nommer le fichier WIM
3. Cliquer "Lancer la capture" - la machine redécolle en PXE en mode capture
4. WinPE capture le disque via `wimlib-imagex` et dépose le WIM sur le partage Samba
5. Un toast de notification confirme la fin de la capture

Le WIM généré est ensuite sélectionnable dans n'importe quel profil Windows via le navigateur de fichiers WIM (bouton "Parcourir" dans le formulaire de profil).

Dépendance système : `sudo apt install wimtools`

---

## TeamViewer

Le mot de passe d'accès sans surveillance est généré automatiquement :
```
TV_PASSWORD = NOMHOTE_EN_MAJUSCULES + tv_suffix_du_profil
```
Exemple : profil avec `tv_suffix = @Osiris2026!`, machine `PC-COMPTA-01` -> mot de passe `PC-COMPTA-01@OSIRIS2026!`.

Le suffixe est stocké chiffré en base (Fernet) et jamais renvoyé en clair via l'API.

---

## Fichiers à fournir manuellement

Les binaires et images ISO ne sont pas inclus dans le dépôt. À placer dans `backend/static/` :

| Fichier | Source |
|---|---|
| `wimboot` | github.com/ipxe/wimboot/releases |
| `curl.exe` (Windows 8.x) | curl.se/windows |

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

---

## Caddyfile - routes nécessaires

Chaque route API utilisée par le frontend doit avoir un bloc explicite dans la section HTTPS de Caddyfile :

```
handle /auth*          { reverse_proxy localhost:8000 }
handle /machines*      { reverse_proxy localhost:8000 }
handle /profiles*      { reverse_proxy localhost:8000 }
handle /organizations* { reverse_proxy localhost:8000 }
handle /users*         { reverse_proxy localhost:8000 }
handle /apps*          { reverse_proxy localhost:8000 }
handle /images*        { reverse_proxy localhost:8000 }
handle /capture*       { reverse_proxy localhost:8000 }
handle /wims*          { reverse_proxy localhost:8000 }
handle /drivers*       { reverse_proxy localhost:8000 }
handle /ws*            { reverse_proxy localhost:8000 }
```

---

## Sécurité

| Mesure | Détail |
|---|---|
| Auth JWT | Toutes les routes API exigent un Bearer token signé (HS256) |
| Secrets chiffrés | Mots de passe AD et suffixe TV stockés avec Fernet (AES-128-CBC) |
| Validation MAC | Regex stricte `^[0-9a-f]{12}$` - injection iPXE impossible |
| Échappement XML | `xml.sax.saxutils.escape` sur tous les champs injectés dans unattend.xml |
| Hachage mots de passe | bcrypt pour les users - sha512_crypt 100k rounds pour les machines |
| CORS restreint | Origines explicitement listées dans `.env` |
| Rate limiting | `/auth/login` : 5/min - `/boot` : 30/min - endpoints publics machines : 10/min |

**Risques résiduels documentés :**
- **Spoofing MAC** - iPXE identifie les machines uniquement par MAC. Mitigation : VLAN PXE dédié.
- **Scripts en HTTP clair** - les scripts de boot transitent sans chiffrement sur le réseau PXE. Acceptable sur réseau interne isolé.
- **`/machines/{mac}/status` sans auth** - appelé par la machine elle-même pendant l'install. La MAC est le seul identifiant. Acceptable sur réseau interne.

---

## Migrations de schéma

`init_db()` crée les tables manquantes et applique des migrations légères (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) pour les colonnes ajoutées en cours de projet. Il n'y a pas encore Alembic - les migrations complexes se font manuellement.

---

## Architecture multi-tenant

OSIRIS utilise une **base partagée, schéma partagé** (row-level) : toutes les machines sont dans la même table, chaque ligne porte un `organization_id`. C'est adapté à un MSP où l'équipe technique voit tous les clients.

**Pour une isolation par client (portail self-service)**, il faudrait ajouter `organization_id` sur `User`, l'inclure dans le JWT, et appliquer `WHERE organization_id = current_user.org_id` sur toutes les requêtes machines. PostgreSQL Row Level Security est disponible pour une isolation inviolable au niveau DB.

---

*Projet open source - licence à définir*
