# Sauvegarde d'OSIRIS

Tout ce qui fait une installation OSIRIS vit dans PostgreSQL : organisations,
profils, parc, journaux de déploiement — et, chiffrés par Fernet, les mots de
passe de jonction au domaine, les PIN BitLocker et les secrets TOTP. Perdre cette
base, c'est refaire toute la configuration à la main.

Deux niveaux, deux métiers différents. Le second n'est **pas** fourni ici : il
dépend de l'hyperviseur.

## Niveau 1 — l'archive quotidienne (ce dossier)

```bash
sudo install -o root -g root -m 700 deploy/backup/osiris-backup.sh /usr/local/sbin/
sudo install -o root -g root -m 644 deploy/backup/osiris-backup.{service,timer} /etc/systemd/system/
sudo systemctl enable --now osiris-backup.timer
```

Chaque nuit : dump PostgreSQL, `backend/.env`, la configuration hors dépôt
(`dnsmasq.d`, `Caddyfile`, unités systemd, agent Zabbix, sudoers), l'état git réel
de la machine, et un inventaire de `/srv/data`. Quelques centaines de kilooctets,
14 archives conservées.

**L'archive contient `.env` en clair** — donc la clé Fernet, le secret JWT et le
mot de passe de la base. Elle est en `600`, propriété de root, et vaut exactement
ce que valent ces secrets. C'est délibéré : un dump sans sa clé ne restaure que
des colonnes illisibles, et une clé rangée ailleurs finit par se perdre. Si
l'archive doit sortir de la machine, la chiffrer.

**Ce qui n'y est pas** : `/srv/data` (images Windows, ISO, pilotes — des dizaines
de Go). Le script en garde l'inventaire, pas le contenu : ces fichiers se
retéléchargent, sauf la **golden image**, qui vient d'une machine de référence et
ne se retrouve que dans une sauvegarde au niveau de la VM.

Le script se relit lui-même : après chaque exécution il ouvre l'archive et passe
le dump à `pg_restore --list`. Une sauvegarde jamais relue est une hypothèse.

```bash
sudo osiris-backup.sh --verifier      # contrôle la dernière archive sans en créer
```

Chaque archive contient son propre `RESTAURATION.md`. L'ordre y compte :
**`.env` avant la base**.

### Variables

| Variable | Défaut | Effet |
|---|---|---|
| `DESTINATION` | `/srv/backup` | où déposer les archives |
| `RETENTION` | `14` | nombre d'archives conservées |
| `BUNDLE_COMPLET` | `0` | `1` embarque toute l'histoire git (~130 Mo/nuit) et rend l'archive autonome ; `0` n'embarque que les commits absents du dépôt distant |

## Niveau 2 — la VM entière

L'archive ci-dessus protège d'une fausse manœuvre, pas de la perte de la machine :
elle est posée sur le disque qu'elle sauvegarde. Il faut donc **en plus** une
sauvegarde au niveau de l'hyperviseur.

⚠️ **Vérifier la place avant de planifier un `vzdump`.** Le stockage `local` d'un
nœud Proxmox est son disque système : une sauvegarde qui le remplit fait tomber
**toutes** les VM du nœud, pas seulement celle qu'on sauvegardait. Comparer
l'espace libre à l'occupation réelle de la VM, pas à son disque alloué.

Sans stockage de sauvegarde dimensionné, la mesure d'attente est un **instantané
avant travaux** : sur du stockage Ceph il est quasi instantané et ne coûte que les
blocs modifiés. Ce n'est pas une sauvegarde — il vit sur le même stockage que la
VM — mais il couvre le cas courant : « j'ai cassé quelque chose en développant ».

À faire depuis l'interface de l'hyperviseur : la VM d'OSIRIS ne doit **pas**
appartenir au pool que pilote son propre jeton, sous peine de pouvoir se
restaurer, se cloner ou s'éteindre elle-même.
