# Supervision du serveur OSIRIS

OSIRIS pose un agent Zabbix sur les machines qu'il déploie, mais le serveur
lui-même n'était supervisé par rien. Ce dossier rend l'installation
reproductible : sans lui, tout ce qui suit ne vit que dans `/etc` et
`/usr/local/bin`, et disparaît avec la machine.

Deux consommateurs, indépendants l'un de l'autre : **Zabbix** pour la
disponibilité, un **scanner de CVE** pour la surface logicielle.

## 1. Agent Zabbix

```bash
sudo apt install -y zabbix-agent2
sudo install -o root -g root -m 644 \
  deploy/supervision/zabbix-agent2-osiris.conf.example \
  /etc/zabbix/zabbix_agent2.d/osiris.conf
sudoedit /etc/zabbix/zabbix_agent2.d/osiris.conf   # renseigner les <valeurs>
sudo systemctl restart zabbix-agent2
```

Le paquet vient des dépôts de la distribution. **Pas** celui de
`backend/static/installers/`, qui est bâti pour Ubuntu 24.04 et dépend d'une
version d'OpenSSL absente de Debian 12.

Le fichier est déposé à part, dans `zabbix_agent2.d/`, et non dans
`zabbix_agent2.conf` : une mise à jour du paquet réécrit le second, jamais le
premier. Il est lu après lui, donc ses valeurs gagnent.

**Mode actif.** Si le serveur vit dans un VLAN d'où seul le 10051 sortant est
ouvert, le collecteur ne peut joindre ni le port 10050 ni l'API, et un item
passif resterait indéfiniment `unsupported`. C'est aussi pourquoi `/health` est
interrogé par l'agent en local : l'API n'écoute que sur la loopback.

`HostMetadata=osiris-server …` est délibérément différent du `osiris linux` des
machines déployées : le serveur n'est pas du bétail, il ne doit hériter ni du
groupe ni du modèle des postes clients. Une action d'auto-enregistrement
filtrant sur `osiris-server` crée l'hôte toute seule.

Tant que cette action n'existe pas, l'agent journalise toutes les deux minutes
`host [...] not found`. Ce n'est pas une panne : c'est la preuve que le flux
sortant passe et que le collecteur répond.

## 2. Modèle Zabbix

`zabbix-template-osiris-server.yaml` — export **6.0**, à importer via
*Data collection > Templates > Import*. Il n'ajoute que ce qui est propre à
OSIRIS ; le socle (CPU, RAM, disques, réseau) reste à
`Linux by Zabbix agent active`, à attacher en plus.

Neuf items : `/health` et ses trois champs dérivés, plus l'état des unités
`osiris-api`, `osiris-worker`, `caddy`, `postgresql@15-main` et `dnsmasq`.
Ce dernier mérite son déclencheur : son arrêt ne se voit nulle part dans
l'interface web, il se voit au poste qui ne démarre plus en PXE.

## 3. Inventaire logiciel (scanner de CVE)

```bash
sudo install -o root -g root -m 755 \
  deploy/supervision/osiris-inventory /usr/local/bin/osiris-inventory
```

Un scan qui ne lit que `dpkg` rate plusieurs centaines de paquets : ceux du venv
Python du backend et ceux de `node_modules`. C'est précisément là que vivent
FastAPI, uvicorn et Vite.

Chaque paquet hors distribution porte donc son écosystème au sens
[OSV](https://ossf.github.io/osv-schema/) (`PyPI`, `npm`). Ceux de la
distribution n'en portent pas : le leur se déduit de l'hôte, et les omettre
garde le format compatible avec les collectes existantes. Sans ce champ, un
scanner qui détermine l'écosystème par hôte cherche « fastapi » dans le
catalogue de la distribution, ne trouve rien, et conclut à l'absence de
vulnérabilité — une sous-déclaration muette, qui a l'apparence d'un succès.

La clé `ecosystems` en tête de rapport récapitule ce qui est présent, pour
qu'un consommateur puisse *refuser* un écosystème qu'il ne sait pas traiter
plutôt que de l'écraser silencieusement.

## 4. Compte de service du scanner

```bash
sudo useradd --system --create-home --home-dir /var/lib/cve-scan \
             --shell /bin/bash --comment "Scanner de CVE (lecture seule)" cve-scan
sudo passwd -l cve-scan
sudo install -d -o cve-scan -g cve-scan -m 700 /var/lib/cve-scan/.ssh
sudo install -o cve-scan -g cve-scan -m 600 /dev/null \
     /var/lib/cve-scan/.ssh/authorized_keys
# puis y coller la clé publique du scanner
```

**Aucun sudo, pas même une ligne étroite.** Lire des paquets ne demande pas
root : `dpkg-query`, `pip list` et `package-lock.json` sont accessibles au
compte nu. Un scanner à qui l'on donne root devient un chemin de latéralisation
qui traverse tout le parc.

Corollaire : ce compte lit tout ce qui est lisible par tous. `backend/.env`
contient la clé Fernet, le secret JWT et les mots de passe — il doit être en
**640**, l'API et le worker tournant sous le même compte :

```bash
chmod 640 backend/.env
```
