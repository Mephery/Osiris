# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les serveurs de temps du profil, sur un clone NU.

cloud-init les posait sur le chemin « clone + cloud-init » ; le clone nu n'a que
le premier démarrage, qui se contentait de TESTER la source active — et répondait
OK sur le pool Debian, injoignable et jamais synchronisé (vu le 07/10). Le réglage
du profil était donc décoratif sur tout un hyperviseur.

Le bloc est EXÉCUTÉ, timesyncd et chrony simulés dans un répertoire racine jetable.
"""
import stat
import subprocess

from jinja2 import Environment, FileSystemLoader

import main
from models import Profile

NTP = ["192.0.2.10", "192.0.2.11"]


def _rendu(ntp=NTP) -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters.setdefault("bash_squote", lambda v: "'" + str(v).replace("'", "'\\''") + "'")
    return env.get_template("firstboot-ubuntu.sh.j2").render(
        machine={"hostname": "srv-01", "mac": "aabbccddeeff", "ou": "", "post_script": ""},
        profile={"machine_type": "server", "ntp_servers": ntp},
        linux_apps=[], zabbix=None, disques=[], osiris_url="http://osiris.test",
        ip_attendue="", partition_vg="osiris", root_gb=None, swap_gb=2)


def _bloc(script: str, debut: str, fin: str) -> str:
    i = script.index(debut)
    return script[i:script.index(fin, i)]


def _executer(tmp_path, bloc: str, *, chrony: bool, source: str = "") -> dict:
    racine = tmp_path / "racine"
    (racine / "etc/chrony").mkdir(parents=True)
    (racine / "etc/chrony/chrony.conf").write_text(
        "pool 2.debian.pool.ntp.org iburst\nsourcedir /etc/chrony/sources.d\nmakestep 1 3\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    faux = {
        "systemctl": ('[ "$1" = list-unit-files ] && { %s; exit 0; }\n'
                      'echo "systemctl $*" >> "%s/appels"; exit 0'
                      % ("echo chrony.service enabled" if chrony else "true", tmp_path)),
        "timedatectl": ('[ "$1" = show-timesync ] && { echo "%s"; exit 0; }\n'
                        '[ "$1" = show ] && { echo yes; exit 0; }\nexit 0' % source),
        "chronyc": 'exit 1',
    }
    for nom, corps in faux.items():
        f = bin_ / nom
        f.write_text("#!/bin/bash\n" + corps + "\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    bloc = bloc.replace("/etc/", f"{racine}/etc/")
    script = f'''
ECHEC=0
trap 'ECHEC=1' ERR
_log() {{ echo "LOG $1"; }}
_add_test() {{ echo "TEST $1|$2|$3"; }}
{bloc}
echo "ECHEC=$ECHEC"
'''
    r = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin"})
    return {"sortie": r.stdout + r.stderr, "racine": racine,
            "appels": (tmp_path / "appels").read_text() if (tmp_path / "appels").exists() else ""}


def _pose() -> str:
    return _bloc(_rendu(), "_ntp_profil=", "# ── Inventaire materiel")


def _test() -> str:
    """Le verdict, de la lecture de la source jusqu'au `fi` qui le clôt."""
    script = _rendu()
    debut = script.index("_ntp_src=$(timedatectl")
    fin = script.index("\nfi\n", script.index('"aucune source de temps active"')) + 4
    return script[debut:fin]


def test_le_script_rendu_reste_du_bash_valide():
    r = subprocess.run(["bash", "-n"], input=_rendu(), text=True, capture_output=True)
    assert r.returncode == 0, r.stderr


def test_timesyncd_recoit_les_serveurs_du_profil_sans_pool_de_secours(tmp_path):
    r = _executer(tmp_path, _pose(), chrony=False)
    conf = (r["racine"] / "etc/systemd/timesyncd.conf.d/osiris.conf").read_text()
    assert conf == "[Time]\nNTP=192.0.2.10 192.0.2.11\nFallbackNTP=\n"
    assert "systemctl restart systemd-timesyncd" in r["appels"]
    assert "ECHEC=0" in r["sortie"]


def test_chrony_recoit_les_serveurs_et_oublie_les_pools_de_l_image(tmp_path):
    r = _executer(tmp_path, _pose(), chrony=True)
    sources = (r["racine"] / "etc/chrony/sources.d/osiris.sources").read_text()
    assert sources == "server 192.0.2.10 iburst\nserver 192.0.2.11 iburst\n"
    conf = (r["racine"] / "etc/chrony/chrony.conf").read_text()
    assert "\n# osiris: pool 2.debian.pool.ntp.org" in "\n" + conf
    assert conf.count("sourcedir /etc/chrony/sources.d") == 1
    assert "systemctl restart chrony" in r["appels"]


def test_une_source_hors_profil_fait_echouer_le_test(tmp_path):
    """Le cas du 07/10 : pool Debian actif, test « OK »."""
    r = _executer(tmp_path, _test(), chrony=False, source="1.debian.pool.ntp.org")
    assert "TEST Serveur de temps|false|1.debian.pool.ntp.org n'est pas un serveur du profil" in r["sortie"]


def test_une_source_du_profil_reussit(tmp_path):
    r = _executer(tmp_path, _test(), chrony=False, source="192.0.2.11")
    assert "TEST Serveur de temps|true|192.0.2.11" in r["sortie"]


def test_sans_serveur_au_profil_on_ne_touche_a_rien():
    assert "timesyncd.conf.d" not in _rendu(ntp=[])


def test_seul_un_nom_ou_une_adresse_passe_du_profil():
    """Les noms finissent dans des fichiers de configuration écrits en root."""
    p = Profile(name="p", os="debian",
                ntp_servers="10.0.0.1, ntp.exemple.test,x\nmakestep 9 9,$(reboot),fe80::1")
    assert main._profile_for_template(p)["ntp_servers"] == ["10.0.0.1", "ntp.exemple.test", "fe80::1"]
