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
retéléchargent tous chez Microsoft ou les constructeurs.

**Sauf la golden image**, qui vient d'une machine de référence et ne se
retéléchargera jamais. Elle est donc copiée à part, dans `golden/`, mais
seulement quand sa taille ou sa date ont changé — c'est-à-dire après une vraie
capture, quelques fois par an. Les autres nuits, le script constate et passe.
La copie précédente est conservée : une capture ratée écrase la golden image
*en place*, et sans cela on répliquerait l'image cassée par-dessus la bonne.

## Un volume dédié, pas le disque système

Une archive posée sur le disque qu'elle sauvegarde disparaît avec lui. Le script
**refuse de s'exécuter** si `DESTINATION` n'est pas un point de montage — sans
ce contrôle, un volume absent ferait écrire les sauvegardes sur le disque
système sans que rien ne le signale, et on ne s'en apercevrait qu'au moment de
restaurer. `EXIGER_MONTAGE=0` pour une destination volontairement posée sur la
racine.

Monter le volume avec `nofail` : un disque de sauvegarde manquant ne doit jamais
empêcher la machine de démarrer.

## Relire, puis répéter

Le script se relit lui-même : après chaque exécution il ouvre l'archive et passe
le dump à `pg_restore --list`. Une sauvegarde jamais relue est une hypothèse.

Mais `--list` ne fait que lire la table des matières du dump : il prouve qu'il
n'est pas tronqué, **pas qu'il remonte**. Une archive peut passer ce contrôle
toutes les nuits pendant des mois et se révéler inutilisable le jour où on en a
besoin. D'où le second mode, qui restaure pour de vrai :

```bash
sudo osiris-backup.sh --verifier      # contrôle la dernière archive sans en créer
sudo osiris-backup.sh --repetition    # la restaure vraiment, dans une base jetable
```

La répétition crée une base neuve, y restaure le dump avec `--exit-on-error`,
contrôle ce qui en ressort, puis **détruit la base dans tous les cas**, y compris
quand un contrôle échoue. Elle refuse de démarrer si `REPETITION_BASE` porte le
nom de la base de production.

Quatre contrôles, du plus évident au moins visible :

1. **La restauration passe sans une seule erreur.** `--exit-on-error` est
   indispensable : par défaut `pg_restore` signale ses erreurs et sort quand même
   en `0`, donc une restauration à moitié faite passerait pour un succès.
2. **Le schéma a une version.** Un dump pris pendant une migration interrompue se
   restaure sans broncher, mais l'application le refuserait au démarrage.
3. **Les tables vitales ne sont pas vides.** Un dump peut être parfaitement
   valide *et* vide ; sans utilisateur ni organisation, l'OSIRIS restauré ne
   laisserait même pas ouvrir une session.
4. **La `FERNET_KEY` de l'archive déchiffre les secrets de la même archive.**
   C'est le contrôle qui manquait le plus : une archive dont la clé et le dump ne
   vont pas ensemble se restaure *parfaitement* et ne rend que des secrets
   illisibles — jonction AD, PIN BitLocker, jetons d'hyperviseur, tous à
   ressaisir à la main. Un seul déchiffrement suffit à prouver la paire ; le
   clair n'est ni affiché ni conservé.

Hebdomadaire plutôt que quotidien : ce contrôle restaure la base entière, là où
la vérification légère tourne déjà à chaque sauvegarde.

```bash
sudo install -o root -g root -m 644 deploy/backup/osiris-repetition.{service,timer} /etc/systemd/system/
sudo systemctl enable --now osiris-repetition.timer
```

Chaque archive contient son propre `RESTAURATION.md`. L'ordre y compte :
**`.env` avant la base**.

### Variables

| Variable | Défaut | Effet |
|---|---|---|
| `DESTINATION` | `/srv/backup` | où déposer les archives |
| `RETENTION` | `14` | nombre d'archives conservées |
| `BUNDLE_COMPLET` | `0` | `1` embarque toute l'histoire git (~130 Mo/nuit) et rend l'archive autonome ; `0` n'embarque que les commits absents du dépôt distant |
| `GOLDEN` | `/srv/data/windows/Golden_Image.wim` | image à recopier hors du disque principal |
| `EXIGER_MONTAGE` | `1` | refuse de s'exécuter si la destination n'est pas montée |
| `REPETITION_BASE` | `osiris_repetition` | base jetable de la répétition ; refuse de valoir `BASE` |
| `TABLES_VITALES` | `user organization hypervisor` | tables qui doivent contenir des lignes après restauration |
| `PYTHON` | `$DEPOT/backend/venv/bin/python` | interpréteur portant `cryptography`, pour le contrôle de la clé |

## Savoir qu'elle a échoué

Une sauvegarde qui échoue en silence est le mode de défaillance habituel des
sauvegardes. Le service sort en erreur, donc systemd retient le motif, et le
modèle Zabbix de `deploy/supervision/` le relève :

```
systemd.unit.info["osiris-backup.service","Result","Service"]
systemd.unit.info["osiris-repetition.service","Result","Service"]
```

⚠️ Le troisième paramètre est indispensable : `Result` appartient à l'interface
`Service`, pas à `Unit` — sans lui l'item reste en `ZBX_NOTSUPPORTED`.

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
