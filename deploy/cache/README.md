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

**Matériel** : une machine Debian 12 ou Ubuntu (serveur) avec **deux cartes réseau**
(un adaptateur USB-Ethernet convient pour la seconde) et un disque assez grand pour
toutes les images et tous les pilotes (compter 250 Go et plus).

- la **carte lien** va vers le réseau du site, d'où l'on joint OSIRIS ;
- la **carte site** va vers la **prise d'installation**, et **seulement** elle (ou
  en direct sur le PC à installer). Sur cette carte, le cache prend l'adresse
  d'OSIRIS et distribue des adresses.

1. **Dans OSIRIS** (Infrastructure › Sites distants) : créer le site et recopier son
   jeton, affiché une seule fois.
2. **Sur OSIRIS** : relever son empreinte SSH, que le cache vérifiera.
   ```bash
   ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   ```
3. **Sur le cache** (root), avec le dossier `deploy/cache` copié dessus :
   ```bash
   ./installer-cache.sh installer --manager <adresse d'OSIRIS> --osiris-ip <OSIRIS_IP> \
       --carte-site <interface> --dns <DNS du domaine> --empreinte <SHA256:…>
   ```
   Le jeton est demandé sans être affiché. Options : `--carte-lien`, `--fenetre
   01:00-05:00`, `--debit-max <Ko/s>`. Le script peut être relancé.
4. **Sur OSIRIS** : coller la ligne `autoriser-cache.sh '…'` que le script affiche
   à la fin. Elle ajoute la clé du cache avec sa bride, et refuse toute autre forme.
5. **Sur le cache** : première copie, puis contrôle complet.
   ```bash
   /opt/osiris-cache/osiris-cache-sync.sh --maintenant
   /opt/osiris-cache/installer-cache.sh verifier
   ```

**Le garde-fou de l'installation.** Avant de toucher à la carte site, le script
regarde si un serveur DHCP y répond, ou si une machine y porte déjà l'adresse
d'OSIRIS. Dans les deux cas, la carte est branchée sur un réseau en service : le
cache y créerait un doublon de l'adresse d'OSIRIS et un second DHCP, et les postes
de ce réseau perdraient leurs adresses. Le script refuse et dit pourquoi. La
solution n'est jamais de forcer : il faut rebrancher la carte sur la prise dédiée.

**`verifier`** contrôle, dans cet ordre : les services, la prise, la liaison avec
OSIRIS, puis les fichiers. L'ordre compte : sans liaison, les fichiers ne peuvent
pas arriver, et c'est la cause qu'il faut corriger d'abord.

Pour retirer un cache : `autoriser-cache.sh --retirer osiris-cache-<nom>` sur OSIRIS,
puis « Retirer le site » dans l'interface.

## La première copie

Elle transfère tout : plusieurs dizaines de gigaoctets. À 20 Mbit/s, cela prend
plusieurs nuits. **Mieux vaut préparer le cache à côté d'OSIRIS**, sur le réseau
local, et ne l'envoyer sur son site qu'ensuite. Le lien inter-sites ne portera
alors que les différences.

## Dépannage

| Constat | Où regarder |
|---|---|
| L'onglet Sites dit `jamais` | Le cache n'a jamais joint OSIRIS : `systemctl status osiris-cache-sync`, puis `journalctl -u osiris-cache-sync` |
| `inachevee` (Copie inachevée) | Normal pour une première copie ou une grosse image ; la nuit suivante reprend. Au-delà de 3 jours, élargir la fenêtre ou le débit |
| `echec`, « rsync … code 255 » | SSH refusé : clé non autorisée sur OSIRIS, ou empreinte d'OSIRIS changée. Sur le cache : `installer-cache.sh verifier` |
| Un PC du site ne démarre pas en réseau | Sur le cache : `installer-cache.sh verifier`, puis `journalctl -u dnsmasq` (le PC a-t-il demandé une adresse ?) |
| `en_retard` | Le cache est éteint, ou sa minuterie n'est pas active : `systemctl list-timers osiris-cache-sync.timer` |
| `images_differentes` | La copie a réussi mais une image manque : vérifier qu'elle n'est pas exclue (`*.bak*`, `*.ko-*`) |
