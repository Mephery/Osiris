# Certificat TLS d'OSIRIS

L'interface est servie sur un **nom public** avec un certificat **Let's Encrypt**,
reconnu par tout le monde sans rien installer nulle part.

## Pourquoi pas l'autorité interne

Une autorité d'entreprise ne serait reconnue que des machines du domaine. Or les
machines qu'OSIRIS déploie — VM cloud-init fraîches, WinPE — n'en font pas encore
partie au moment où elles rappellent le serveur. Un certificat public est reconnu
d'elles **d'origine**, ce qui est la condition pour basculer un jour les rappels
en HTTPS sans injecter d'autorité dans les gabarits.

## Pourquoi la validation DNS-01

OSIRIS est sur une adresse privée, injoignable depuis internet : la validation
HTTP-01, qui suppose que Let's Encrypt vienne frapper sur le port 80, est donc
impossible. DNS-01 ne demande qu'un enregistrement TXT temporaire — aucun port
ouvert, aucune exposition.

## Installation

```bash
sudo install -m 700 deploy/tls/certbot-gandi.sh /usr/local/sbin/
sudo install -m 700 deploy/tls/osiris-cert-check.sh /usr/local/sbin/
sudo install -m 700 -D deploy/tls/osiris-caddy-deploy-hook.sh \
     /etc/letsencrypt/renewal-hooks/deploy/osiris-caddy.sh
sudo install -m 644 deploy/tls/osiris-cert-check.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now osiris-cert-check.timer
```

Puis le jeton : copier `gandi.ini.example` vers `/etc/letsencrypt/gandi.ini`,
le remplir, `chmod 600`.

**Vérifier le jeton AVANT de lancer certbot** — c'est cinq secondes, et ça évite
un échec obscur au milieu de la commande :

```bash
curl -H "Authorization: Bearer <jeton>" \
     https://api.gandi.net/v5/livedns/domains/<zone>      # doit rendre 200
```

Enfin :

```bash
sudo certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
  --manual --preferred-challenges dns \
  --manual-auth-hook "/usr/local/sbin/certbot-gandi.sh auth" \
  --manual-cleanup-hook "/usr/local/sbin/certbot-gandi.sh cleanup" \
  -d <nom> --cert-name osiris
```

## Trois pièges, tous rencontrés en vrai

**Le jeton doit venir de la bonne organisation.** Un compte Gandi peut en avoir
plusieurs, portant des noms très proches. Un jeton parfaitement valide mais créé
dans la mauvaise ne voit pas la zone et répond **403** — sans que rien ne le dise
avant le renouvellement.

**Les serveurs de noms ne convergent pas instantanément.** Observé : les trois
serveurs faisant autorité servant *trois valeurs différentes* du même TXT, dont
une vieille de vingt minutes. Le crochet `auth` interroge donc chacun d'eux
jusqu'à les voir tous d'accord, plutôt que d'attendre une durée fixe — trop
courte, la validation échoue ; trop longue, chaque renouvellement traîne.

**Let's Encrypt valide depuis plusieurs points d'observation en production**, pas
en staging. Un TXT périmé encore servi par un seul serveur suffit à faire échouer
la demande avec « During secondary validation: Incorrect TXT record ». Laisser
expirer le TTL entre deux tentatives.

## Le crochet de déploiement n'est pas optionnel

Caddy tourne sous son propre utilisateur et ne peut pas lire `/etc/letsencrypt`,
en `700 root`. Sans le crochet qui recopie le certificat et recharge Caddy, le
renouvellement **réussirait** et Caddy continuerait de servir l'ancien certificat
jusqu'à son expiration : une panne différée de trois mois, invisible le jour où
elle se prépare.

## Supervision

`osiris-cert-check.timer` écrit chaque jour un état sans secret, que l'agent
Zabbix relit. Il surveille deux échéances qui se taisent en cas de panne :

| Clé | Sens |
|---|---|
| `osiris.cert.jours` | jours avant expiration du certificat |
| `osiris.gandi.ok` | le jeton ouvre-t-il encore la zone (1/0) |
| `osiris.gandi.jours` | jours avant expiration déclarée du jeton |

Le second est le plus important : un jeton mort ne casse rien tout de suite, il
casse le *renouvellement* — et ne se manifeste que 90 jours plus tard.
