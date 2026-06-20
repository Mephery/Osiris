# OSIRIS — Déploiement iPXE automatisé

Osiris est un serveur de déploiement réseau pensé pour les équipes d'infogérance.  
Il remplace les outils comme MDT mais pour **toutes les images** (Windows, distributions Linux, et à terme n'importe quel OS), avec une interface web moderne et une API REST.

> **Statut :** POC fonctionnel — Ubuntu autoinstall et Windows WinPE validés en lab.

---

## Fonctionnement général

```
Machine vierge
     │
     │  boot réseau (DHCP → iPXE)
     ▼
 GET /boot?mac=aa:bb:cc:...
     │
     │  Osiris reconnaît la MAC en base
     │  → génère un script iPXE à la volée
     ▼
 Ubuntu  → kernel casper via NFS + user-data dynamique (cloud-init)
 Windows → wimboot + unattend.xml dynamique
     │
     │  pendant l'install, la machine appelle :
     │  POST /machines/{mac}/status?status=deploying
     │  POST /machines/{mac}/status?status=deployed
     ▼
 Statut mis à jour en temps réel dans l'interface
```

---

## Pile technique

| Composant | Technologie |
|---|---|
| Backend | Python · FastAPI · SQLModel |
| Base de données | PostgreSQL |
| Frontend | React 19 · TypeScript · Tailwind CSS v4 |
| Auth | JWT (python-jose) · bcrypt (passlib) |
| Boot réseau | iPXE · DHCP (externe) |
| Autoinstall Ubuntu | cloud-init / subiquity |
| Autoinstall Windows | WinPE · wimboot · unattend.xml |
| NFS (images Ubuntu) | sur le serveur hôte (Proxmox ou VM dédiée) |

---

## Installation

### Prérequis

- Python 3.11+
- Node.js 22+
- PostgreSQL 14+
- Un serveur DHCP configuré pour pointer vers Osiris (next-server + filename)

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # ou pip install fastapi sqlmodel uvicorn python-jose[cryptography] passlib[bcrypt] python-dotenv python-multipart "bcrypt==4.0.1"

cp .env.example .env
# Éditer .env avec vos valeurs (voir section Variables d'environnement)

python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Au premier démarrage, Osiris crée automatiquement un compte admin depuis `ADMIN_EMAIL` et `ADMIN_PASSWORD` définis dans `.env`.  
**Changez ce mot de passe immédiatement** (voir section Changer son mot de passe).

### Frontend

```bash
cd frontend
cp .env.example .env
# Éditer VITE_API_URL avec l'IP/URL de votre backend

npm install
npm run dev -- --host      # dev
npm run build              # production
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

# JWT — générer avec : python3 -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=changeme

# Compte admin créé au premier démarrage (si aucun user en base)
ADMIN_EMAIL=admin@osiris.local
ADMIN_PASSWORD=changeme

# Réseau PXE — IP vue par les machines qui bootent (pas l'IP Tailscale !)
OSIRIS_BASE_URL=http://10.0.0.1:8000
OSIRIS_IP=10.0.0.1

# CORS — origines autorisées pour le frontend (séparées par des virgules)
ALLOWED_ORIGINS=http://192.168.1.x:5173

# Clé SSH publique déposée sur chaque Ubuntu déployé (optionnel)
OSIRIS_SSH_PUBKEY=
```

### `frontend/.env`

```env
VITE_API_URL=http://192.168.1.x:8000
```

> **Note réseau :** `OSIRIS_BASE_URL` doit être l'IP du réseau PXE (celle que voient les machines qui bootent). 

---

## Changer son mot de passe

Via curl (remplacer le token obtenu au login) :

```bash
# 1. Se connecter
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@osiris.local","password":"changeme"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Changer le mot de passe
curl -s -X PATCH http://localhost:8000/auth/me/password \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"current_password":"changeme","new_password":"VotreVraiMotDePasse!"}'
```

---

## Fichiers statiques à fournir manuellement

Les binaires et images ISO ne sont **pas** inclus dans le dépôt (trop lourds). À placer dans `backend/static/` :

| Fichier | Source |
|---|---|
| `ubuntu.iso` | [ubuntu.com/download/server](https://ubuntu.com/download/server) |
| `vmlinuz` | Extrait de `ubuntu.iso/casper/vmlinuz` |
| `initrd` | Extrait de `ubuntu.iso/casper/initrd` |
| `wimboot` | [ipxe.org/wimboot](https://github.com/ipxe/wimboot/releases) |

### Extraire vmlinuz et initrd depuis l'ISO

```bash
sudo apt install xorriso
xorriso -osirrox on -indev ubuntu.iso \
  -extract /casper/vmlinuz backend/static/vmlinuz \
  -extract /casper/initrd  backend/static/initrd
```

### Configurer le partage NFS (Ubuntu)

Les machines Ubuntu bootent via NFS (pas de téléchargement de l'ISO en RAM). Sur le serveur hôte :

```bash
sudo apt install nfs-kernel-server
sudo mkdir -p /srv/nfs/ubuntu
sudo xorriso -osirrox on -indev ubuntu.iso -extract / /srv/nfs/ubuntu

echo "/srv/nfs/ubuntu *(ro,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -ra
```

---

## Architecture multi-tenant

### Modèle de données

```
Organization          User                    Machine
─────────────         ──────────────          ──────────────────
id                    id                      id
name                  email                   mac
slug                  hashed_password         hostname / os / ou
created_at            role (admin|technician) client
                                              status / deployed_at
                                              organization_id → Organization
```

### Rôles

| Rôle | Peut faire |
|---|---|
| `admin` | Tout : créer/supprimer des organisations, des utilisateurs, des machines |
| `technician` | Enregistrer et consulter des machines — pas supprimer |

### Philosophie de cette implémentation

Osiris utilise une **base partagée, schéma partagé** (approche dite "row-level") : toutes les machines sont dans la même table, chaque ligne porte un `organization_id`.

Ce choix est volontaire et adapté à un contexte MSP où **toute l'équipe technique voit tous les clients**. Le filtre par organisation dans l'UI est un confort de navigation, pas une restriction de sécurité.

**Si vous adaptez Osiris pour un contexte où chaque client ne doit voir que ses propres machines**, il faudra :

1. Ajouter `organization_id` sur le modèle `User`
2. Inclure l'`org_id` dans le payload JWT
3. Extraire l'`org_id` du JWT dans la dépendance `get_current_user`
4. Appliquer `WHERE organization_id = current_user.org_id` sur toutes les requêtes machines

Pour une isolation garantie au niveau base de données (inviolable même si l'applicatif oublie de filtrer), PostgreSQL propose le **Row Level Security** natif :

```sql
ALTER TABLE machine ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON machine
  USING (organization_id = current_setting('app.current_tenant')::int);
```

---

## Sécurité — état actuel et risques résiduels

### Mesures en place

| Mesure | Détail |
|---|---|
| Auth JWT | Toutes les routes API exigent un Bearer token signé (HS256) |
| Validation MAC | Regex stricte `^[0-9a-f]{12}$` — injection iPXE impossible |
| Échappement XML | `xml.sax.saxutils.escape` sur tous les champs injectés dans unattend.xml |
| Hachage mots de passe | bcrypt pour les users · sha512_crypt 100k rounds pour les machines |
| CORS restreint | Origines explicitement listées dans `.env` |
| Logs SQL désactivés | `echo=False` — pas de données sensibles dans les logs |

### Risques résiduels restants pour l'heure documentés

**Spoofing MAC** — iPXE identifie les machines uniquement par adresse MAC. N'importe quelle machine sur le réseau peut usurper la MAC d'une machine enregistrée et recevoir son script de déploiement. C'est une contrainte du protocole, pas un bug. Mitigation : isoler le réseau PXE sur un VLAN dédié.

**Scripts iPXE en HTTP clair** — les scripts de boot et les user-data (qui contiennent des hashs de mots de passe) transitent sans chiffrement. Sur un réseau d'entreprise interne et isolé c'est acceptable. Pour une exposition WAN : iPXE supporte HTTPS mais nécessite une compilation avec `DOWNLOAD_PROTO_HTTPS=1`.

**Endpoint `/machines/{mac}/status` sans auth** — appelé par la machine elle-même pendant l'install via `curl`. Une machine n'a pas de token JWT, donc cet endpoint est volontairement ouvert. La MAC est le seul identifiant. Acceptable sur réseau interne.

**Rate limiting** — limites en place sur les endpoints publics (`/auth/login` : 5/min, `/boot` : 30/min, `/machines/{mac}/status` : 10/min). Un attaquant patient avec plusieurs IPs peut contourner une limite par IP ; ce n'est qu'une couche parmi d'autres.


---

## Contribuer

Quelques points d'attention si vous adaptez Osiris :

- Si vous ajoutez de la restriction par organisation, concevez le multi-tenant et le RBAC **ensemble** — les deux sont liés et refactorer l'un sans l'autre oblige à tout reprendre.
- Les migrations de schéma se font manuellement (`ALTER TABLE`) — il n'y a pas encore Alembic. `init_db()` crée les tables manquantes mais ne modifie pas les colonnes existantes.
- `OSIRIS_BASE_URL` est l'IP du réseau PXE, pas l'IP d'accès à l'UI. Ne pas les confondre.

---

*Projet open source — licence à définir*
