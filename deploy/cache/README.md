# Cache de site

Un site distant ne peut pas tirer une image Windows de 15 Go par son lien
inter-sites à chaque PC. Son cache sert sur place ce qui pèse et relaie le reste
à OSIRIS. Ce dossier en contient la **copie de nuit**. Le principe du cache et sa
simulation sur le banc sont décrits dans `deploy/banc-test/README.md`.

## Ce qui se passe chaque nuit

1. À 01:00, la minuterie du cache lance `osiris-cache-sync.sh`.
2. Le cache se connecte en SSH à OSIRIS, au compte `osiris-cache`. La clé de ce
   compte ne peut lancer **que** rsync, en lecture seule, sur trois dossiers :
   `static` (WinPE, wimboot, installeurs), `windows` (images, pilotes) et `tftp`
   (iPXE). Il n'a pas de shell, ne peut rien écrire, et la liste des modules est
   masquée.
3. rsync n'envoie que ce qui a changé. Une nuit sans changement coûte quelques
   kilo-octets.
4. Le cache rend compte à OSIRIS (`POST /sites/rapport`, avec le jeton du site) en
   passant par sa propre adresse, que son Caddy relaie comme pour un PC.
5. OSIRIS compare les images du cache aux siennes. Le résultat est l'un de ces
   états : `jamais`, `echec`, `en_retard`, `images_differentes`, `a_jour`.

Ce qui ne bouge pas pendant la copie :

- un PC qui lit déjà une image garde l'ancienne jusqu'au bout (rsync remplace par
  renommage) ;
- un PC qui démarre voit l'ancien WinPE ou le nouveau, jamais un mélange des deux
  (`--delay-updates`).

**La fenêtre de nuit est une limite stricte.** À `FIN_FENETRE`, la copie s'arrête,
même au milieu d'une image. Ce qui a été reçu est gardé, et la nuit suivante
reprend là (vérifié sur le banc : 1,3 Go → 3,2 Go à la reprise). Il n'y a **pas
de rattrapage** au rallumage : un cache rallumé en journée ne lance pas de copie
sur le lien des utilisateurs.

## Côté OSIRIS (une fois)

```bash
sudo apt install rsync
sudo useradd --system --home-dir /var/lib/osiris-cache --create-home --shell /bin/sh osiris-cache
sudo install -d -m 755 /etc/osiris
sudo install -m 644 deploy/cache/rsyncd-cache.conf.example /etc/osiris/rsyncd-cache.conf
sudo install -d -m 700 -o osiris-cache -g osiris-cache /var/lib/osiris-cache/.ssh
```

Le Caddyfile doit laisser passer `/sites*` (interface) et `/sites/rapport` (caches),
voir `Caddyfile.example`.

## Pour chaque site

1. **Dans OSIRIS** : créer le site. Le jeton n'est affiché qu'une fois. En cas de
   perte ou de fuite, en générer un nouveau : l'ancien cesse aussitôt de valoir.
2. **Sur le cache** : générer sa clé.
   ```bash
   sudo install -d -m 700 /etc/osiris-cache
   sudo ssh-keygen -t ed25519 -N "" -C "cache-<site>" -f /etc/osiris-cache/id_ed25519
   ```
3. **Sur OSIRIS** : ajouter la clé publique, bridée, à
   `/var/lib/osiris-cache/.ssh/authorized_keys` (une ligne par cache) :
   ```
   command="rsync --server --daemon --config=/etc/osiris/rsyncd-cache.conf .",restrict ssh-ed25519 AAAA… cache-<site>
   ```
4. **Sur le cache** : relever l'empreinte d'OSIRIS et la **comparer** à celle
   qu'affiche `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` sur OSIRIS. Si elles
   diffèrent, ne pas continuer.
   ```bash
   ssh-keyscan -t ed25519 <manager> | sudo tee /etc/osiris-cache/known_hosts
   ssh-keygen -lf /etc/osiris-cache/known_hosts
   ```
5. **Sur le cache** : installer le script et sa configuration.
   ```bash
   sudo install -D -m 755 osiris-cache-sync.sh /opt/osiris-cache/osiris-cache-sync.sh
   sudo install -m 600 cache.conf.example /etc/osiris-cache/cache.conf   # puis la remplir
   sudo install -m 644 osiris-cache-sync.service osiris-cache-sync.timer /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now osiris-cache-sync.timer
   ```
6. **Première copie** : `sudo /opt/osiris-cache/osiris-cache-sync.sh --maintenant`.

## La première copie

Elle transfère tout : plusieurs dizaines de gigaoctets. À 20 Mbit/s, cela prend
plusieurs nuits. **Mieux vaut préparer le cache à côté d'OSIRIS**, sur le réseau
local, et ne l'envoyer sur son site qu'ensuite. Le lien inter-sites ne portera
alors que les différences.

## Dépannage

| Constat | Où regarder |
|---|---|
| L'onglet Sites dit `jamais` | Le cache n'a jamais joint OSIRIS : `systemctl status osiris-cache-sync`, puis `journalctl -u osiris-cache-sync` |
| `echec`, « fenêtre de nuit terminée » | Normal pour une première copie ou une grosse image ; la nuit suivante reprend |
| `echec`, « rsync … code 255 » | SSH refusé : clé absente d'`authorized_keys`, ou empreinte d'OSIRIS changée |
| `en_retard` | Le cache est éteint, ou sa minuterie n'est pas active : `systemctl list-timers osiris-cache-sync.timer` |
| `images_differentes` | La copie a réussi mais une image manque : vérifier qu'elle n'est pas exclue (`*.bak*`, `*.ko-*`) |
