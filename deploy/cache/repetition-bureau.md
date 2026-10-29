# Répétition générale d'un site distant, au bureau

Avant de poser un cache sur un vrai site, on rejoue tout au bureau, sur du vrai
matériel : un PC « cache » et un PC à installer. Le banc de test
(`deploy/banc-test`) a prouvé la mécanique en VM ; il ne peut pas prouver ce qui
suit, et c'est l'objet de cette journée :

- un **vrai PC** (Dell de préférence) : touche F12, pilotes réseau réels ;
- le **premier démarrage de Windows** (firstboot) derrière le cache ;
- la **jonction au domaine** à travers le NAT du cache ;
- **Secure Boot** actif, avec la chaîne signée d'iPXE ;
- le comportement quand **le lien vers OSIRIS tombe** en pleine installation ;
- le **script d'installation** du cache sur une vraie machine.

Pour chaque essai, la fiche dit ce qu'on fait, ce qu'on attend, et ce que
**l'opérateur voit**. Cette dernière colonne est la plus importante : elle
nourrit l'aide intégrée à l'interface. Remplir « Constaté » au fil de la journée,
même quand tout se passe comme prévu.

Durée : une journée.

## Matériel

- **PC cache** : n'importe quelle machine, Debian 12 fraîchement installé, deux
  cartes réseau (un adaptateur USB-Ethernet suffit pour la seconde), 250 Go de
  disque ou plus.
- **PC à installer** : idéalement un Dell récent, avec Secure Boot réglable.

Un **portable** fait un bon cache de répétition (sa batterie sert d'onduleur), à
deux conditions : brancher le lien en filaire (pas de Wi-Fi, on mesurerait le
Wi-Fi) et l'empêcher de se mettre en veille capot fermé, sinon le cache
disparaît en pleine installation :

```bash
echo 'HandleLidSwitch=ignore' | sudo tee -a /etc/systemd/logind.conf
sudo systemctl restart systemd-logind
```

Le disque doit tenir tout ce que copie le cache : quelques dizaines de Go
aujourd'hui, et une image qui change occupe un temps deux fois sa place.
- Un **câble** entre la carte site du cache et le PC (ou un petit switch relié à
  rien d'autre).

```
  OSIRIS (manager) ── réseau du bureau ── carte LIEN │ PC cache │ carte SITE ── câble ── PC à installer
                                                     │ (Debian) │  (isolée : le cache y est
                                                                 DHCP, passerelle et « OSIRIS »)
```

🔴 **La carte site ne se branche JAMAIS sur le switch du bureau.** Le cache y
prendrait l'adresse d'OSIRIS et distribuerait des adresses. Le script refuse s'il
détecte un DHCP ou l'adresse d'OSIRIS en face (prouvé sur le banc), mais on ne
compte pas sur un garde-fou pour ce qu'un câble bien branché évite.

## Préparation (avant le jour J)

1. Dans OSIRIS : créer le site « Répétition » (Infrastructure › Sites distants),
   noter le jeton.
2. Sur OSIRIS : relever l'empreinte SSH :
   `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.
3. Déclarer le PC à installer dans OSIRIS (numéro de série), avec un profil qui
   **rejoint le domaine dans une OU de test**, pour que la jonction soit éprouvée
   sans toucher aux vraies OU.
4. Vérifier qu'un pack de pilotes existe pour ce modèle (onglet Pilotes).

## Essais

### 1. Installer le cache

| Ce qu'on fait | Attendu |
|---|---|
| `installer-cache.sh installer --manager <OSIRIS> --osiris-ip <OSIRIS_IP> --carte-site <carte> --dns <DNS du domaine> --empreinte <SHA256:…>` | garde-fou passé (« réseau isolé »), installation sans erreur, ligne `autoriser-cache.sh '…'` affichée |
| `verifier` **avant** d'autoriser la clé sur OSIRIS | « OSIRIS refuse la copie (SSH) » en premier, puis les fichiers manquants |
| `autoriser-cache.sh '…'` sur OSIRIS, puis `osiris-cache-sync.sh --maintenant` | copie complète ; durée et volume à noter |
| `verifier` | « Tout est en ordre » ; onglet Sites : « À jour » |

Constaté :

### 2. Simuler le lien inter-sites

Sur le cache, ajouter du délai sur la carte lien, comme un MPLS :

```bash
sudo tc qdisc add dev <carte lien> root netem delay 20ms     # retirer : tc qdisc del dev <carte lien> root
```

Le débit de la copie de nuit, lui, se règle avec `--debit-max` (relancer
l'installation avec `--debit-max 2500` pour environ 20 Mbit/s). Brider la carte
avec `tc` ne limiterait que ce que le cache **envoie**, pas ce qu'il reçoit.

Constaté :

### 3. Installation nominale

| Ce qu'on fait | Attendu | Ce que voit l'opérateur |
|---|---|---|
| PC branché sur la carte site, allumé, **F12**, démarrage réseau | adresse donnée par le cache, WinPE, partitionnement, DISM, redémarrage | à l'écran : iPXE puis WinPE puis Windows ; dans OSIRIS : le journal en direct de la machine |
| Laisser finir | firstboot : jonction au domaine (OU de test), applications, statut `deployed` | fiche machine au vert |
| Vérifier dans l'AD | l'ordinateur est dans l'OU de test | — |

Mesurer : durée totale, et ce que le lien a porté pendant l'installation
(`ip -s link show <carte lien>` avant/après) : quelques Mo au plus attendus.

Constaté :

### 4. Secure Boot

| Ce qu'on fait | Attendu | Ce que voit l'opérateur |
|---|---|---|
| Activer Secure Boot dans le BIOS du PC, vérifier « Enable Microsoft UEFI CA » | — | — |
| Démarrer en réseau avec l'`ipxe.efi` actuel | **refus** du firmware | message du BIOS Dell (à noter mot pour mot) |
| Sur le cache : déposer `ipxe-shim.efi` et `ipxe.efi` du dossier `x86_64-sb` de l'archive iPXE v2.0.0 dans `/srv/osiris-cache/tftp/`, et mettre `ipxe-shim.efi` comme fichier d'amorce dans `/etc/dnsmasq.d/osiris-cache.conf`, puis `systemctl restart dnsmasq` | iPXE signé, puis WinPE, puis installation complète | comme l'essai 3 |
| Désactiver Secure Boot, redémarrer en réseau avec la chaîne signée | marche aussi : une seule configuration pour tous les PC | — |

Ce que le banc a déjà montré : refus de l'iPXE non signé, chaîne signée acceptée
jusqu'au noyau de WinPE. Cet essai doit montrer la suite.

Constaté :

### 5. Le lien tombe en pleine installation

| Ce qu'on fait | Attendu | Ce que voit l'opérateur |
|---|---|---|
| Pendant DISM, débrancher la carte lien du cache 5 minutes, puis la rebrancher | DISM continue : l'image est sur le cache | **dans OSIRIS, la fiche reste figée sur « DISM en cours »** : les lignes de journal envoyées pendant la coupure sont perdues |
| Laisser finir | statut final reçu après le rebranchement ? | à noter : la fiche se remet-elle à jour seule ? |

C'est l'essai qui dira ce que la fiche machine doit montrer quand une machine se
tait (cf. chantier « fiche honnête »).

Constaté :

### 6. Le lien est coupé AVANT le démarrage

| Ce qu'on fait | Attendu | Ce que voit l'opérateur |
|---|---|---|
| Carte lien débranchée, PC démarré en réseau | le cache donne une adresse, mais ne peut pas relayer le script de démarrage | **sur le PC** : message d'erreur d'iPXE (à noter mot pour mot) ; **dans OSIRIS** : rien du tout |

Constaté :

### 7. Le cache est éteint

| Ce qu'on fait | Attendu | Ce que voit l'opérateur |
|---|---|---|
| Cache éteint, PC démarré en réseau | aucune adresse | sur le PC : message du firmware (« No offer » ou équivalent) ; dans OSIRIS : rien ; onglet Sites : « en retard » après 36 h sans copie |

Constaté :

### 8. Copie de nuit

| Ce qu'on fait | Attendu | Ce que voit l'opérateur |
|---|---|---|
| Modifier une image sur OSIRIS en journée | onglet Sites : « arrivera avec la copie de cette nuit » (pas une alerte) | pas d'alerte rouge |
| Fenêtre très courte (`--fenetre` sur 5 minutes) avec un gros fichier à copier | arrêt à l'heure, état « Copie inachevée » (orange), reprise au passage suivant | message clair dans l'onglet Sites |
| Renouveler le jeton du site dans OSIRIS sans mettre à jour le cache | compte rendu refusé | onglet Sites figé sur la dernière copie, puis « en retard » ; `verifier` sur le cache : « OSIRIS refuse le jeton du site » |

Constaté :

## Démontage

1. Sur le cache : `tc qdisc del dev <carte lien> root`.
2. Sur OSIRIS : `autoriser-cache.sh --retirer osiris-cache-<nom>`.
3. Dans OSIRIS : retirer le site « Répétition », retirer le PC de test de l'OU de
   test (et de l'AD).
4. Si le cache est une machine prêtée ou personnelle : la réinstaller. Elle
   contient les images Windows du parc.

## Après la journée

Reporter chaque « Constaté » qui diffère de l'« Attendu », et chaque message
d'erreur relevé mot pour mot. Ils deviennent : des correctifs, des lignes de la
base de pannes connues, et des explications dans l'interface.
