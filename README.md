# OSIRIS - Serveur de déploiement réseau

OSIRIS est un serveur de déploiement PXE pensé pour les équipes d'infogérance.
Il remplace les outils comme MDT/WDS avec une interface web moderne, une API REST et une automatisation complète du cycle de vie des postes.

> **Statut :** Production-ready en environnement lab : Windows 11 et Ubuntu 24.04 LTS validés bout-en-bout.

**Philosophie :** brancher un câble RJ45 suffit. La machine PXE-boot, OSIRIS la déploie, configure TeamViewer, installe les apps, joint le domaine, active BitLocker, tout depuis l'interface.

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
| Inventaire matériel automatique | oui | oui | - |
| Mapping lecteurs réseau au démarrage | oui | - | - |
| Imprimantes réseau au démarrage | oui | - | - |
| Script post-install personnalisé | PowerShell | Bash | - |
| Notification échec firstboot | oui | oui | - |
| Wake-on-LAN | oui | oui | oui |
| Redéployer maintenant (WoL + pending) | oui | oui | oui |
| Déploiement en lot | oui | oui | oui |
| Historique de déploiement par machine | oui | oui | oui |
| Notifications webhook (Teams / Slack) | oui | oui | oui |
| Capture golden image | oui (WIM) | - | - |
| Navigateur WIM | oui | - | - |
| Import / export CSV machines | oui | oui | oui |
| Notes libres sur les machines | oui | oui | oui |
| Utilisateur affecté à une machine | oui | oui | oui |
| Tableau de bord par organisation | oui | oui | oui |
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
     |            TeamViewer, winget, lecteurs, imprimantes, script perso)
     |  Ubuntu  : firstboot-ubuntu.sh  (inventaire, TeamViewer, apt,
     |            jonction AD, script perso)
     v
 Statut mis à jour en temps réel via WebSocket dans l'interface
 Webhook envoyé si une URL est configurée sur l'organisation
 Si le script échoue, callback automatique status=failed
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
- 24 applications courantes dans le catalogue

**Changez le mot de passe admin immédiatement** (icône paramètres en haut à droite).

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
id / name / slug      id / email              id / name / os
webhook_url           hashed_password         locale / keyboard / timezone
                      role (admin|tech)       default_user / extra_packages
                      totp_secret (Fernet)    join_domain / domain
                                              domain_join_user/password (Fernet)
                                              domain_config_id -> DomainConfig
                      ApiKey[]                win_image / win_index
                                              enable_bitlocker / bitlocker_pin
                                              network_drives (JSON)
                                              printers (JSON)
                                              post_script
                                              tv_suffix (Fernet)
                                              app_ids -> Application[]

Machine               DomainConfig            Application
-------               ------------            -----------
id / mac / hostname   id / name               id / name
client / os / ou      organization_id         winget_id (Windows)
status / deployed_at  domain                  apt_package (Ubuntu)
organization_id       join_user               category / icon
profile_id            join_password (Fernet)
hw_serial / hw_model  default_ou
hw_ram_gb
bitlocker_key (Fernet)
bitlocker_pin (Fernet)
laps_password (Fernet)
user_name / user_email
notes
```

---

## Rôles

| Rôle | Peut faire |
|---|---|
| `admin` | Tout : organisations, utilisateurs, profils, machines, drivers, captures, clés API |
| `technician` | Enregistrer et consulter des machines, pas supprimer ni accéder à l'admin |

---

## Tableau de bord

L'onglet **Tableau de bord** affiche en temps réel :
- Compteurs globaux par statut (déployés / en attente / en cours / échoués)
- Barres de répartition par organisation
- Alertes automatiques : machines bloquées en déploiement depuis plus de 30 minutes, échecs récents
- Liste des 15 derniers déploiements terminés

---

## BitLocker

Activé automatiquement au premier démarrage Windows si le profil l'autorise. Deux modes :

- **TPM seul** - démarrage automatique, clé de récupération 48 chiffres stockée dans OSIRIS
- **TPM+PIN** - PIN aléatoire à 6 chiffres généré à la volée, démarrage manuel requis. Les deux (PIN et clé 48 chiffres) sont stockés dans OSIRIS, chiffrés avec Fernet.

La clé et le PIN ne sont visibles dans l'interface que par les administrateurs, via le bouton "Afficher les clés" dans le panneau de chaque machine.

---

## LAPS - Mot de passe administrateur local

Au premier démarrage Windows, OSIRIS génère un mot de passe aléatoire de 16 caractères (lettres, chiffres, symboles), l'applique au compte `Administrator` local et le stocke chiffré (Fernet) dans OSIRIS. Chaque machine obtient un mot de passe unique.

Le mot de passe est visible uniquement par les administrateurs, via le bouton "Afficher le mot de passe" dans le panneau de la machine.

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
- Les logs temps réel de la session en cours (via WebSocket)
- L'historique des 20 derniers événements (date, statut, OS, profil utilisé)

---

## Notifications webhook

Dans **Administration > Organisations**, chaque organisation dispose d'un champ "Webhook URL". Quand un déploiement se termine (`deployed` ou `failed`), OSIRIS envoie :

```json
{"text": "PC-DUPONT déployé avec succès (WINDOWS - Acme Corp)"}
```

Compatible avec Teams (Incoming Webhook), Slack (Incoming Webhook) et Discord (Webhook + `/slack` en fin d'URL).

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

## Sécurité des comptes

### 2FA TOTP

Chaque utilisateur peut activer la double authentification depuis l'icône paramètres (roue crantée en haut à droite). L'activation n'est pas obligatoire.

Flux d'activation :
1. OSIRIS génère un secret TOTP et affiche le QR code
2. L'utilisateur scanne avec Google Authenticator, Authy ou toute app compatible
3. Saisie d'un code de confirmation pour valider
4. À chaque connexion suivante : mot de passe + code à 6 chiffres

La désactivation requiert la saisie du mot de passe courant.

### Clés API personnelles

Les clés API permettent à des outils externes d'interroger OSIRIS sans passer par le flux de connexion JWT. Elles s'utilisent exactement comme un token Bearer :

```bash
# Lister les machines depuis un script ou un RMM
curl -H "Authorization: Bearer osiris_sk_..." https://osiris.local/machines

# Export CSV automatisé (cron, backup)
curl -H "Authorization: Bearer osiris_sk_..." https://osiris.local/machines/export > parc.csv
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

Cas d'usage typiques pour un MSP :
- **RMM** (N-central, ConnectWise Automate, Datto) - déclencher un redéploiement depuis une tâche RMM
- **Ticketing** (Freshdesk, Halo PSA) - pré-enregistrer une machine quand un ticket "nouveau poste" est créé
- **CMDB / gestion de parc** (Snipe-IT, Lansweeper) - synchroniser l'inventaire hardware déployé
- **Monitoring** (Grafana, Zabbix) - afficher l'état des déploiements sur un dashboard externe
- **Automatisation** (Make, Zapier) - déclencher des actions à chaque déploiement terminé

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

```
handle /auth*          { reverse_proxy localhost:8000 }
handle /machines*      { reverse_proxy localhost:8000 }
handle /profiles*      { reverse_proxy localhost:8000 }
handle /organizations* { reverse_proxy localhost:8000 }
handle /domain-configs* { reverse_proxy localhost:8000 }
handle /users*         { reverse_proxy localhost:8000 }
handle /apps*          { reverse_proxy localhost:8000 }
handle /images*        { reverse_proxy localhost:8000 }
handle /capture*       { reverse_proxy localhost:8000 }
handle /wims*          { reverse_proxy localhost:8000 }
handle /drivers*       { reverse_proxy localhost:8000 }
handle /dashboard*     { reverse_proxy localhost:8000 }
handle /ws*            { reverse_proxy localhost:8000 }
```

---

## Sécurité

| Mesure | Détail |
|---|---|
| Auth JWT | Toutes les routes API exigent un Bearer token signé (HS256) |
| Clés API | Format `osiris_sk_...` - stockées en SHA-256, jamais récupérables en clair |
| 2FA TOTP | Secret chiffré Fernet en base, token temporaire 5 min entre mot de passe et code |
| Secrets chiffrés | Mots de passe AD, BitLocker, LAPS, PIN, suffixe TV : Fernet (AES-128-CBC) |
| Validation MAC | Regex stricte `^[0-9a-f]{12}$` - injection iPXE impossible |
| Échappement XML | `xml.sax.saxutils.escape` sur tous les champs injectés dans unattend.xml |
| Hachage mots de passe | bcrypt pour les users - sha512_crypt 100k rounds pour les machines |
| CORS restreint | Origines explicitement listées dans `.env` |
| Rate limiting | `/auth/login` : 5/min - `/boot` : 30/min - endpoints publics : 10/min |

**Risques résiduels documentés :**
- **Spoofing MAC** - iPXE identifie les machines uniquement par MAC. Mitigation : VLAN PXE dédié.
- **Scripts en HTTP clair** - les scripts de boot transitent sans chiffrement sur le réseau PXE. Acceptable sur réseau interne isolé.
- **Endpoints firstboot sans auth** - `/machines/{mac}/status`, `/hardware`, `/laps-password`, `/bitlocker-key` sont appelés par la machine elle-même. La MAC est le seul identifiant. Acceptable sur réseau PXE interne isolé.

---

## Migrations de schéma

`init_db()` crée les tables manquantes et applique des migrations légères (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) à chaque démarrage. Il n'y a pas encore Alembic - les migrations complexes se font manuellement.

---

## Architecture multi-tenant

OSIRIS utilise une **base partagée, schéma partagé** (row-level) : toutes les machines sont dans la même table, chaque ligne porte un `organization_id`. C'est adapté à un MSP où l'équipe technique voit tous les clients.

**Pour une isolation par client (portail self-service)**, il faudrait ajouter `organization_id` sur `User`, l'inclure dans le JWT, et appliquer `WHERE organization_id = current_user.org_id` sur toutes les requêtes machines. PostgreSQL Row Level Security est disponible pour une isolation inviolable au niveau base de données.

---

*Projet open source - licence à définir*
