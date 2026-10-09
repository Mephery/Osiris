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


# ── Ubuntu : netplan réactivait IPv6 derrière le sysctl ──────────────────────
# 09/10 : HUMNKLPR03 (Ubuntu) gardait son fe80:: alors que HUMNVLPR01 (Debian)
# était conforme. netplan demande par défaut à systemd-networkd une adresse de
# lien local IPv6, et networkd remet disable_ipv6=0 sur la carte. Le bloc est
# EXÉCUTÉ contre un faux `netplan`, sous `set -euo pipefail`.
import subprocess

DEBUT = "# Le sysctl ne suffit PAS"
FIN = "{% if profile.ntp_servers %}"

NETPLAN_GET = """ens192:
  match:
    macaddress: "00:50:56:ad:17:f9"
  set-name: "ens192"
  dhcp4: true
eth1:
  addresses:
  - "192.0.2.10/24"
"""


def _bloc() -> str:
    s = _lire("firstboot-ubuntu.sh.j2")
    return s[s.index(DEBUT):s.index(FIN)]


def _lancer(tmp_path, netplan=None, apply_ok=True):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    trace = tmp_path / "trace"
    if netplan is not None:
        (tmp_path / "get.yaml").write_text(netplan)
        f = bin_ / "netplan"
        f.write_text(f'#!/bin/bash\necho "netplan $*" >> {trace}\n'
                     f'[ "$1" = get ] && cat {tmp_path}/get.yaml\n'
                     f'[ "$1" = apply ] && exit {0 if apply_ok else 1}\nexit 0\n')
        f.chmod(0o755)
    s = bin_ / "sysctl"
    s.write_text(f'#!/bin/bash\necho "sysctl $*" >> {trace}\n')
    s.chmod(0o755)
    r = subprocess.run(["bash", "-c", "set -euo pipefail\n_log() { echo \"LOG $1\"; }\n"
                        + _bloc() + "\necho FIN"],
                       env={"PATH": f"{bin_}:/usr/bin:/bin"}, capture_output=True, text=True)
    return r, (trace.read_text() if trace.exists() else "")


def test_ubuntu_chaque_carte_perd_son_lien_local_ipv6(tmp_path):
    r, trace = _lancer(tmp_path, NETPLAN_GET)
    assert "FIN" in r.stdout, r.stderr
    for carte in ("ens192", "eth1"):
        assert f"netplan set ethernets.{carte}.link-local=[]" in trace
        assert f"netplan set ethernets.{carte}.accept-ra=false" in trace
    # Les sous-clés (match, set-name, addresses) ne sont pas prises pour des cartes
    assert "ethernets.match" not in trace and "ethernets.set-name" not in trace
    # Appliqué, puis le sysctl repassé sur la carte reconfigurée
    assert trace.index("netplan apply") < trace.rindex("sysctl -p")
    assert "IPv6 coupe aussi dans netplan" in r.stdout


def test_debian_sans_netplan_n_est_pas_touchee(tmp_path):
    r, trace = _lancer(tmp_path, netplan=None)
    assert "FIN" in r.stdout, r.stderr
    assert "netplan" not in trace


def test_un_netplan_apply_rate_est_signale_sans_arreter_le_deploiement(tmp_path):
    r, trace = _lancer(tmp_path, NETPLAN_GET, apply_ok=False)
    assert "FIN" in r.stdout, r.stderr
    assert "AVERTISSEMENT : netplan apply a echoue" in r.stdout


def test_pas_de_coupure_au_noyau():
    """`ipv6.disable=1` retire la pile : un service qui écoute sur [::] (nginx
    par défaut) refuserait de démarrer."""
    s = _lire("firstboot-ubuntu.sh.j2")
    code = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#"))
    assert "ipv6.disable=1" not in code
