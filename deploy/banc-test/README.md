# Banc de test VM locale

Valide **toute la chaîne PXE → iPXE → wimboot → WinPE → déploiement** sur la
machine OSIRIS elle-même : sans matériel, sans hyperviseur joignable, et sans
toucher au VLAN de production. Il a déjà rattrapé deux régressions qui n'auraient
été visibles qu'en déploiement réel.

Ce dossier existe parce que la recette vivait dans un répertoire temporaire —
c'est-à-dire nulle part.

## Ce qui est persistant, ce qui ne l'est pas

| Élément | Survit à un redémarrage ? |
|---|---|
| Paquets `qemu-system-x86`, `ovmf` | ✅ |
| Utilisateur dans le groupe `kvm` | ✅ |
| `/etc/dnsmasq.d/banc-test.conf` | ✅ |
| Pont `br-test` + interface `tap-test` | ❌ — `banc-test.sh reseau` les recrée |
| Disque `disk.qcow2`, variables OVMF | ❌ — recréés à la demande |

## Mise en route

```bash
sudo install -m 644 deploy/banc-test/dnsmasq-banc-test.conf.example \
     /etc/dnsmasq.d/banc-test.conf     # puis renseigner les <valeurs>
sudo systemctl restart dnsmasq

deploy/banc-test/banc-test.sh reseau      # pont + tap (à refaire après reboot)
deploy/banc-test/banc-test.sh demarrer    # crée le disque au besoin, lance la VM
deploy/banc-test/banc-test.sh etat
deploy/banc-test/banc-test.sh arreter
```

## Deux contraintes qui ne se devinent pas

**SATA et e1000 sont obligatoires.** WinPE n'embarque pas les pilotes virtio : avec
`virtio-blk` ou `virtio-net`, il ne voit ni le disque ni la carte réseau, et l'échec
ressemble à un problème de déploiement alors qu'il est matériel.

**L'option DHCP 121 écrase l'option 3** (RFC 3442) : dès qu'une route statique
globale est servie — pour les tunnels VPN clients par exemple — le client **ignore**
la passerelle par défaut de l'option 3. Le réseau du banc doit donc porter sa propre
route par défaut dans son option 121, sinon la VM obtient une adresse mais ne sort
pas.

## Observer sans écran

Pas besoin de VNC : le socket moniteur QEMU accepte `screendump`, et `mon.py`
convertit le PPM en PNG.

```bash
deploy/banc-test/mon.py shot ecran.png   # capture d'écran
deploy/banc-test/mon.py info status      # n'importe quelle commande du moniteur
```

C'est ainsi que se lisent les écrans WinPE, qui n'ont aucune autre sortie.

## Deux pièges appris à nos dépens

**Arrêter le banc quand on a fini.** Un banc laissé tourner a consommé deux cœurs
pendant quatorze jours et son `disk.qcow2` a gonflé jusqu'à plusieurs dizaines de
gigaoctets — un tiers du disque de la machine. `banc-test.sh arreter` existe pour
ça, et `etat` dit en une ligne si quelque chose tourne encore.

**Pour un simple test d'amorçage**, préférer `DISQUE_JETABLE=1` : QEMU écrit alors
dans un fichier temporaire détruit à l'arrêt, et le disque ne grossit jamais.

## Ce que le banc ne prouve pas

La carte réseau d'une VM est *inbox* dans WinPE. Le banc démontre donc que les
pilotes sont bien livrés, injectés et balayés par `drvload` — **mais pas qu'un pilote
non-inbox se lie effectivement** au matériel. Seule une vraie machine le dira.

## Cache de site

`cache-banc.sh` simule le cache qu'on pose dans un site distant pour que l'image
Windows ne traverse pas le lien inter-sites. Le principe : sur la prise dédiée, le
cache porte **la même adresse qu'OSIRIS**. Le PC croit parler à OSIRIS ; le cache
sert lui-même ce qui pèse (`/static`, partage `windows` en lecture seule) et relaie
le reste (scripts, journaux, statut) au vrai OSIRIS. Ni `boot.wim` ni les scripts
n'ont à connaître le cache.

```bash
deploy/banc-test/cache-banc.sh monter      # espace réseau isolé + dnsmasq, Caddy, Samba
PONT=br-site TAP=tap-site PXE=1 DISQUE_JETABLE=1 deploy/banc-test/banc-test.sh demarrer
deploy/banc-test/cache-banc.sh etat        # services, baux, requêtes servies / relayées
PONT=br-site TAP=tap-site deploy/banc-test/banc-test.sh arreter
deploy/banc-test/cache-banc.sh demonter
```

Le cache tourne dans un *network namespace* : sa propre pile réseau, sans VM. Il
n'a besoin d'aucun fichier dans `/etc/dnsmasq.d/`. Le pont du site n'a **aucune
adresse côté hôte**, et la liaison montante est en lien-local (`169.254.0.0/16`).
L'hôte n'apprend donc aucune route nouvelle, alors qu'un réseau de banc en /24
peut masquer un vrai réseau du même nom.

`PXE=1` est indispensable : avec l'ISO, WinPE serait lu sur le CD et ne passerait
jamais par le cache.

Ce que le banc a montré : DHCP, TFTP, WinPE, pilotes WinPE et image servis par le
cache ; reconnaissance par numéro de série, journaux et statut final relayés. Le
lien montant n'a porté que quelques dizaines de kilo-octets pour tout un
déploiement. Il ne dit rien de la jonction au domaine à travers le cache, ni du
firstboot.

## Fiche machine associée

Le banc suppose une machine enregistrée dans OSIRIS avec la MAC et le numéro de
série utilisés par `banc-test.sh` (`52:54:00:51:21:15` / `VMTESTWINPE01` par
défaut). Lui donner un profil **sans jonction au domaine** : le banc ne doit rien
créer dans l'annuaire. La supprimer si l'on abandonne le banc.
