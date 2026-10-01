# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Désactivation de la couche IPv6 au premier démarrage (ticket sécurité 26421).

Demande : couper IPv6 sur toutes les VM, nous et clients. Le firstboot le pose à
CHAQUE déploiement — c'est le filet qui couvre toute VM livrée, même clonée d'un
master pas encore rescellé (le gabarit la portera aussi).
"""


def _lire(nom: str) -> str:
    return open(f"templates/{nom}", encoding="utf-8").read()


def test_ipv6_coupe_sur_linux():
    s = _lire("firstboot-ubuntu.sh.j2")
    assert "/etc/sysctl.d/99-osiris-disable-ipv6.conf" in s
    for cle in ("net.ipv6.conf.all.disable_ipv6 = 1",
                "net.ipv6.conf.default.disable_ipv6 = 1",
                "net.ipv6.conf.lo.disable_ipv6 = 1"):
        assert cle in s


def test_ipv6_coupe_sur_windows():
    s = _lire("firstboot-windows.ps1.j2")
    assert r"Tcpip6\Parameters" in s
    assert "DisabledComponents" in s
    assert "0xFF" in s
