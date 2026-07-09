# Tunnels VPN clients — déploiement

Remplace le script PowerShell MDT (bascule d'un seul VPN à la fois côté
Windows) par des tunnels OpenVPN permanents sur la VM Debian OSIRIS, pilotés
depuis l'UI web. Chaque organisation peut avoir un tunnel ; toutes les
machines déployées sur le VLAN 10.0.0.0/24 peuvent joindre tous les
domaines AD clients simultanément, sans sélection manuelle.

Aucune nouvelle dépendance Python (tout est stdlib : `subprocess`,
`ipaddress`, `tempfile`).

## 1. Paquet OpenVPN

```bash
sudo apt install -y openvpn
```

Le paquet Debian fournit le service template `openvpn-client@.service` qui
lit `/etc/openvpn/client/<nom>.conf` — c'est ce qu'utilise `backend/vpn.py`.

## 2. Scripts root + sudoers

```bash
sudo install -o root -g root -m 700 deploy/osiris-vpn-apply.sh   /usr/local/sbin/osiris-vpn-apply.sh
sudo install -o root -g root -m 700 deploy/osiris-vpn-disable.sh /usr/local/sbin/osiris-vpn-disable.sh
sudo install -o root -g root -m 440 deploy/osiris-vpn.sudoers    /etc/sudoers.d/osiris-vpn
sudo visudo -c
```

`humans` (compte qui fait tourner osiris-api) n'obtient de sudo NOPASSWD que
sur ces deux scripts précis — pas de sudo générique. Les scripts vivent hors
de `/opt/osiris` (qui appartient à `humans`) pour que ce compte ne puisse pas
se donner root en modifiant le script qu'il a le droit d'exécuter en sudo.

## 3. NAT + routage

L'IP forwarding est déjà activé sur ce serveur (`/proc/sys/net/ipv4/ip_forward
= 1`). Pour qu'il survive à un reboot :

```bash
echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-osiris-vpn.conf
```

Règle NAT pour que le trafic du VLAN labo sorte via les tunnels clients
(chaque tunnel a sa propre route poussée dans son fichier .ovpn par
`backend/vpn.py`, donc une seule règle générique suffit) :

```bash
sudo iptables -t nat -A POSTROUTING -o tun+ -j MASQUERADE
sudo apt install -y iptables-persistent   # puis "oui" pour sauvegarder les règles IPv4
```

## 4. Base de données + backend

```bash
cd /opt/osiris/backend
source venv/bin/activate
alembic upgrade head
sudo systemctl restart osiris-api
```

## 5. dnsmasq (DNS split-horizon)

Le fichier `dnsmasq.conf` à la racine du repo a été mis à jour : dnsmasq
écoute maintenant aussi sur le port 53 (DNS) en plus du DHCP/TFTP, avec
`10.0.0.1` comme DNS poussé aux machines déployées. Les domaines AD
clients sont ajoutés dynamiquement dans un fichier séparé
(`/etc/dnsmasq.d/osiris-vpn-domains.conf`, généré par `backend/vpn.py` à
chaque "Appliquer" dans l'UI) — pas besoin d'y toucher à la main.

**Impact : ceci change le comportement DNS de TOUTES les machines qui
bootent sur le VLAN 10.0.0.0/24.** À appliquer hors période de
déploiement actif si possible.

```bash
sudo cp /opt/osiris/dnsmasq.conf /etc/dnsmasq.d/osiris.conf
sudo dnsmasq --test          # valide la syntaxe avant de recharger
sudo systemctl reload dnsmasq
```

## 6. Frontend

```bash
cd /opt/osiris/frontend
npm run build
```

(Caddy sert déjà `frontend/dist` — pas de redéploiement Caddy nécessaire.)

## 7. Ajouter un client

Dans l'UI OSIRIS → onglet Admin → "Tunnels VPN clients" :

1. Choisir l'organisation, lui donner un nom.
2. Coller le contenu du fichier `.ovpn` du client (certificats inclus).
3. Renseigner le DNS interne du client (ex: `192.0.2.53`) et son réseau
   (ex: `192.0.2.0/24`).
4. "Ajouter" puis "Appliquer" — le tunnel démarre, la route et l'entrée DNS
   sont poussées, et le statut systemd s'affiche dans la liste.

Penser aussi à créer la `DomainConfig` correspondante (section juste
au-dessus) avec le bon nom de domaine AD : c'est ce couple
(domaine × DNS du tunnel) qui alimente le `server=/domaine/ip` généré pour
dnsmasq.
