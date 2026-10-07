# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le preseed du gabarit Debian sert les deux familles d'hyperviseurs.

Sur Proxmox, un clone ne reçoit son adresse QUE par cloud-init (lecteur NoCloud) :
sans cloud-init dans le gabarit, un clone sur un VLAN sans DHCP n'a aucun réseau —
le scellement a retiré la configuration de construction. Sur vSphere, cloud-init
ne doit pas sonder d'autres sources au démarrage : il est limité à NoCloud, absent
là-bas, et s'y désactive.
"""
import re


def _preseed(client) -> str:
    r = client.get("/preseed/gabarit/debian")
    assert r.status_code == 200
    return r.text


def test_cloud_init_est_installe_avec_les_agents(client):
    paquets = re.search(r"^d-i pkgsel/include string (.+)$", _preseed(client), re.M).group(1).split()
    for p in ("cloud-init", "qemu-guest-agent", "open-vm-tools", "lvm2", "cloud-guest-utils"):
        assert p in paquets


def test_cloud_init_est_limite_a_nocloud(client):
    p = _preseed(client)
    assert "printf 'datasource_list: [ NoCloud ]\\n' > /target/etc/cloud/cloud.cfg.d/99-osiris-datasource.cfg" in p
    # Écrit AVANT les enable tolérants : un échec plus loin ne le saute pas
    assert p.index("99-osiris-datasource.cfg") < p.index("systemctl enable open-vm-tools")


def test_le_mot_de_passe_de_construction_change_a_chaque_lecture(client):
    h1 = re.search(r"user-password-crypted password (\S+)", _preseed(client)).group(1)
    h2 = re.search(r"user-password-crypted password (\S+)", _preseed(client)).group(1)
    assert h1 != h2
