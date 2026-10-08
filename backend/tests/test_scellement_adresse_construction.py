# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le scellement retire l'adresse de CONSTRUCTION d'un gabarit installé par preseed.

Un gabarit tiré d'une image cloud n'a pas d'adresse écrite en dur. Un gabarit
installé par l'installeur Debian, si : sur un VLAN sans DHCP, il a fallu lui
donner une IP fixe pour qu'il s'installe, et l'installeur l'a gravée dans
/etc/network/interfaces (et dans /etc/hosts). ifupdown additionne les
déclarations d'une même carte : chaque clone aurait porté SA propre adresse ET
celle du gabarit. Vu le 01/10 sur le premier gabarit Debian LVM, avant scellement.

La fonction est EXÉCUTÉE, sous le même `set -euo pipefail` que le vrai script :
une commande qui échoue en silence ailleurs y interromprait le scellement.
"""
import subprocess

import pytest
from jinja2 import Environment, FileSystemLoader

# Ce qu'écrit l'installeur Debian 12 avec netcfg en IP fixe
INTERFACES_INSTALLEUR = """\
# This file describes the network interfaces available on your system
# and how to activate them. For more information, see interfaces(5).

source /etc/network/interfaces.d/*

# The loopback network interface
auto lo
iface lo inet loopback

# The primary network interface
allow-hotplug ens192
iface ens192 inet static
	address 192.0.2.201/24
	gateway 192.0.2.1
	# dns-* options are implemented by the resolvconf package, if installed
	dns-nameservers 192.0.2.53
	dns-search local
"""

HOSTS_INSTALLEUR = """\
127.0.0.1	localhost
192.0.2.201	debian-gabarit.local	debian-gabarit

# The following lines are desirable for IPv6 capable hosts
::1     localhost ip6-localhost ip6-loopback
"""


@pytest.fixture(scope="module")
def script() -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    return env.get_template("bootstrap-linux.sh.j2").render(osiris_url="http://osiris.test")


@pytest.fixture(scope="module")
def fonction(script) -> str:
    debut = script.index("neutraliser_adresse_installeur() {")
    return script[debut:script.index("\n}\n", debut) + 3]


def _lancer(fonction, tmp_path, interfaces: str | None, hosts: str | None):
    f, h = tmp_path / "interfaces", tmp_path / "hosts"
    if interfaces is not None:
        f.write_text(interfaces)
    if hosts is not None:
        h.write_text(hosts)
    r = subprocess.run(
        ["bash", "-c", f"set -euo pipefail\n"
                       f"export OSIRIS_INTERFACES={f} OSIRIS_HOSTS={h}\n"
                       f"{fonction}\nneutraliser_adresse_installeur\necho FIN"],
        text=True, capture_output=True)
    return r, f, h


def test_l_adresse_de_construction_ne_part_pas_avec_le_gabarit(fonction, tmp_path):
    r, f, h = _lancer(fonction, tmp_path, INTERFACES_INSTALLEUR, HOSTS_INSTALLEUR)
    assert "FIN" in r.stdout, r.stderr      # set -e n'a pas interrompu le script
    apres = f.read_text()
    assert "192.0.2.201" not in apres
    assert "inet static" not in apres
    assert "gateway" not in apres
    # Ce que l'agent du clone attend : interfaces.d inclus, boucle locale gardée
    assert "source /etc/network/interfaces.d/*" in apres
    assert "iface lo inet loopback" in apres


def test_l_adresse_de_construction_quitte_aussi_etc_hosts(fonction, tmp_path):
    r, f, h = _lancer(fonction, tmp_path, INTERFACES_INSTALLEUR, HOSTS_INSTALLEUR)
    hosts = h.read_text()
    assert "192.0.2.201" not in hosts
    assert "127.0.0.1\tlocalhost" in hosts       # le reste est intact
    # Le nom reste résolu en local : le firstboot réécrit ensuite cette ligne
    assert "\n127.0.1.1\t" in hosts


def test_une_ligne_127_0_1_1_existante_n_est_pas_doublee(fonction, tmp_path):
    hosts = "127.0.0.1\tlocalhost\n127.0.1.1\tdebian-gabarit\n192.0.2.201\tdebian-gabarit\n"
    r, f, h = _lancer(fonction, tmp_path, INTERFACES_INSTALLEUR, hosts)
    assert h.read_text().count("127.0.1.1") == 1


def test_une_image_cloud_sans_adresse_fixe_n_est_pas_touchee(fonction, tmp_path):
    """Le cas courant (gabarits tirés d'images cloud) doit rester intact."""
    cloud = "source /etc/network/interfaces.d/*\nauto lo\niface lo inet loopback\n" \
            "auto eth0\niface eth0 inet dhcp\n"
    r, f, h = _lancer(fonction, tmp_path, cloud, HOSTS_INSTALLEUR)
    assert "FIN" in r.stdout, r.stderr
    assert f.read_text() == cloud
    assert h.read_text() == HOSTS_INSTALLEUR


def test_sans_fichier_interfaces_rien_ne_casse(fonction, tmp_path):
    """netplan pur, systemd-networkd : pas d'ifupdown du tout."""
    r, f, h = _lancer(fonction, tmp_path, None, HOSTS_INSTALLEUR)
    assert "FIN" in r.stdout, r.stderr
    assert not f.exists()


def test_rien_a_retirer_est_dit(fonction, tmp_path):
    """Une ligne absente du journal de scellement laissait se demander si
    l'étape avait seulement tourné (07/10, gabarits tirés d'images cloud)."""
    cloud = "auto lo\niface lo inet loopback\nauto eth0\niface eth0 inet dhcp\n"
    r, _, _ = _lancer(fonction, tmp_path, cloud, HOSTS_INSTALLEUR)
    assert "rien a retirer" in r.stdout


def test_sans_fichier_interfaces_rien_a_retirer_est_dit_aussi(fonction, tmp_path):
    r, _, _ = _lancer(fonction, tmp_path, None, None)
    assert "rien a retirer" in r.stdout and "FIN" in r.stdout, r.stderr


def _annonce(script, tmp_path, url, ip):
    """Exécute curl_annonce contre un faux curl qui recopie ses arguments."""
    debut = script.index("curl_annonce() {")
    fn = script[debut:script.index("\n}\n", debut) + 3]
    faux = tmp_path / "curl"
    faux.write_text('#!/bin/bash\necho "$@"\n')
    faux.chmod(0o755)
    r = subprocess.run(
        ["bash", "-c", f"set -euo pipefail\nexport PATH={tmp_path}:$PATH\n"
                       f"OSIRIS_URL={url}\nOSIRIS_IP={ip}\n{fn}\n"
                       f"curl_annonce -sf $OSIRIS_URL/bootstrap/sealed"],
        text=True, capture_output=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_l_annonce_du_scellement_epingle_le_nom_https(script, tmp_path):
    """Un `curl` nu dépendait du DNS de la VM de construction : sur un VLAN qui
    ne résout pas le nom public, le gabarit n'était pas enregistré (07/10)."""
    sortie = _annonce(script, tmp_path, "https://osiris.example.com", "192.0.2.11")
    assert "--resolve osiris.example.com:443:192.0.2.11" in sortie


def test_l_annonce_en_http_reste_simple(script, tmp_path):
    sortie = _annonce(script, tmp_path, "http://192.0.2.11", "")
    assert "--resolve" not in sortie


def test_le_scellement_annonce_par_l_appel_epingle(script):
    sceller = script[script.index('if [ "$SEAL" -eq 1 ]; then'):]
    assert "curl_annonce -sf -X POST" in sceller
    assert "&& curl -sf" not in sceller


def test_le_scellement_appelle_la_fonction(script):
    sceller = script[script.index('if [ "$SEAL" -eq 1 ]; then'):]
    assert "neutraliser_adresse_installeur" in sceller
