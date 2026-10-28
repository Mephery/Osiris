# Installer OSIRIS (le manager)

`installer-manager.sh` installe OSIRIS sur un **Debian 12 neuf**, en une commande,
puis le contrôle. Il a été écrit après une répétition sur une machine vierge
(28/10/2026) : en suivant le README à la lettre, l'installation n'aboutissait pas
(versions de dépendances non figées, modèles de configuration contradictoires,
binaires de démarrage réseau introuvables). Le script fige ce qui marche.

## Deux façons de l'installer

| Mode | Pour qui | Ce que fait ce serveur |
|---|---|---|
| `manager-seul` (défaut) | plusieurs sites, chacun avec un **cache** (`deploy/cache`) | interface, API, base, et les fichiers que les caches recopient la nuit. Pas de DHCP : ce sont les caches qui accueillent les PC. |
| `tout-en-un` | un seul site, PC sur le même réseau qu'OSIRIS | tout ce qui précède, plus le DHCP, le TFTP et le partage des images sur la carte d'installation |

État des essais (28/10/2026) : `manager-seul` installé sur une VM Debian 12
vierge, relancé, contrôlé, interface et connexion vérifiées. `tout-en-un` est
écrit sur le modèle du cache de site (même garde-fou DHCP) mais **n'a pas encore
été rejoué** sur une machine neuve.

## Installation

```bash
sudo apt install git
sudo install -d -o "$USER" /opt/osiris
git clone https://github.com/Mephery/Osiris.git /opt/osiris
sudo /opt/osiris/deploy/manager/installer-manager.sh installer \
    --adresse-pc <OSIRIS_IP> --adresse-admin <adresse ou nom de ce serveur>
```

- `--adresse-pc` : l'adresse à laquelle **les PC** joignent OSIRIS. En
  `manager-seul`, ce sont les caches de site qui la portent ; ce serveur la pose
  seulement sur sa boucle locale, pour contrôler ses propres routes.
- `--adresse-admin` : l'adresse de l'interface pour les administrateurs (HTTPS,
  certificat interne de Caddy tant qu'aucun n'est fourni).
- `--reseaux-admin 10.0.0.0/8,…` : réseaux autorisés sur l'interface. Par défaut,
  les plages privées. Ailleurs, l'interface répond 403 **en affichant l'adresse
  vue**, pour savoir quoi ajouter.
- `tout-en-un` : `--mode tout-en-un --carte-installation <if> --dns <DNS du domaine>`.
  La carte doit déjà porter l'adresse des PC. Le script refuse s'il trouve un
  autre serveur DHCP sur cette carte.

Le mot de passe du compte administrateur initial est dans
`/root/osiris-mot-de-passe-initial` : le changer à la première connexion, puis
supprimer ce fichier. Ensuite, téléverser une ISO Windows (onglet Images) : OSIRIS
en tire WinPE et l'image à déployer, sans l'ADK de Microsoft.

## Relancer, contrôler

Le script peut être relancé, pour changer une option ou réparer. Il **ne
régénère jamais** `backend/.env` : ce fichier porte la clé qui déchiffre les mots
de passe en base (jonction au domaine, BitLocker, TOTP). La perdre les rendrait
illisibles.

```bash
sudo /opt/osiris/deploy/manager/installer-manager.sh verifier
```

contrôle les services, la base, WinPE, et ce que voient les PC (script de
démarrage servi par Caddy, `ipxe.efi`, `wimboot`).

## D'où viennent iPXE et wimboot

Ni l'un ni l'autre n'est dans le dépôt. Le script les télécharge aux sources
officielles, en **version figée**, et refuse tout fichier dont l'empreinte SHA-256
diffère de celle inscrite dans le script :

| Fichier | Version | Source | Licence |
|---|---|---|---|
| `/srv/tftp/ipxe.efi` | iPXE v2.0.0 (`x86_64/ipxe.efi` de `ipxeboot.tar.gz`) | github.com/ipxe/ipxe | GPL-2.0 (ou ultérieure) |
| `backend/static/wimboot` | wimboot v2.9.0 | github.com/ipxe/wimboot | GPL-2.0 (ou ultérieure) |

Changer de version : mettre à jour l'URL **et** l'empreinte dans le script, après
un essai sur le banc (`deploy/banc-test`) jusqu'au chargement de WinPE.

⚠️ Ce `ipxe.efi` n'est pas signé pour **Secure Boot**. Un PC où Secure Boot est
actif refusera de le démarrer : le désactiver, ou passer aux variantes signées
publiées par iPXE (non éprouvées avec OSIRIS).
