# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""L'agent gravé dans les gabarits Linux : lire le jeton, parler en HTTPS épinglé.

Le jeton arrive par l'hyperviseur (guestinfo, numéro de série SMBIOS) : jamais
par le réseau. L'agent doit le distinguer d'un message d'erreur de vmtoolsd et
du vrai numéro de série d'une machine. Fonctions EXÉCUTÉES, commandes simulées.
"""
import subprocess

import pytest
from jinja2 import Environment, FileSystemLoader

JETON = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcd"


@pytest.fixture(scope="module")
def agent() -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    rendu = env.get_template("bootstrap-linux.sh.j2").render(
        osiris_url="https://osiris.example.com", osiris_ip="192.0.2.11",
        url_installation="http://192.0.2.11", empreinte="test")
    debut = rendu.index("<< 'OSIRIS_BOOTSTRAP_EOF'\n") + len("<< 'OSIRIS_BOOTSTRAP_EOF'\n")
    return rendu[debut:rendu.index("\nOSIRIS_BOOTSTRAP_EOF", debut)]


def _fonction(agent: str, nom: str) -> str:
    debut = agent.index(f"{nom}() {{")
    return agent[debut:agent.index("\n}\n", debut) + 3]


def _jeton(tmp_path, agent, *, guestinfo=None, serie="", fichier=None) -> str:
    racine = tmp_path / "racine"
    (racine / "dmi").mkdir(parents=True)
    (racine / "dmi" / "product_serial").write_text(serie)
    if fichier is not None:
        (racine / "osiris").mkdir()
        (racine / "osiris" / "jeton").write_text(fichier)
    vmtoolsd = ""
    if guestinfo is not None:
        vmtoolsd = tmp_path / "vmtoolsd"
        vmtoolsd.write_text(f"#!/bin/bash\necho '{guestinfo}'\n")
        vmtoolsd.chmod(0o755)
    corps = "\n".join([
        f'chemin_vmtoolsd() {{ echo "{vmtoolsd}"; }}',
        _fonction(agent, "info_get"),
        _fonction(agent, "jeton_machine")
        .replace("/sys/class/dmi/id/product_serial", str(racine / "dmi" / "product_serial"))
        .replace("/var/lib/osiris/jeton", str(racine / "osiris" / "jeton")),
        "jeton_machine",
    ])
    return subprocess.run(["bash", "-c", corps], text=True, capture_output=True).stdout


def test_vsphere_le_jeton_vient_de_guestinfo(tmp_path, agent):
    assert _jeton(tmp_path, agent, guestinfo=JETON, serie="VMware-42 2d 11") == JETON


def test_un_message_d_erreur_de_vmtoolsd_n_est_pas_un_jeton(tmp_path, agent):
    """Clé absente : vmtoolsd répond une phrase, qu'il ne faut pas envoyer à OSIRIS."""
    assert _jeton(tmp_path, agent, guestinfo="No value found") == ""


def test_proxmox_le_jeton_vient_du_numero_de_serie_prefixe(tmp_path, agent):
    assert _jeton(tmp_path, agent, serie=f"osiris-jeton:{JETON}") == JETON


def test_le_vrai_numero_de_serie_d_une_machine_n_est_pas_un_jeton(tmp_path, agent):
    assert _jeton(tmp_path, agent, serie="5CD1234XYZ") == ""


def test_a_defaut_le_jeton_garde_par_un_precedent_passage(tmp_path, agent):
    assert _jeton(tmp_path, agent, fichier=JETON) == JETON


def test_https_nom_epingle_et_jeton_envoye(tmp_path, agent):
    faux = tmp_path / "curl"
    faux.write_text('#!/bin/bash\necho "CURL $*"\n')
    faux.chmod(0o755)
    corps = "\n".join(['OSIRIS_URL="https://osiris.example.com"', 'OSIRIS_IP="192.0.2.11"',
                       f'JETON="{JETON}"', _fonction(agent, "curl_osiris"),
                       'curl_osiris -s "$OSIRIS_URL/firstboot-linux/aabbccddeeff"'])
    sortie = subprocess.run(["bash", "-c", corps], text=True, capture_output=True,
                            env={"PATH": f"{tmp_path}:/usr/bin:/bin"}).stdout
    assert f"-H X-Osiris-Jeton: {JETON}" in sortie
    assert "--resolve osiris.example.com:443:192.0.2.11" in sortie


def test_aucun_repli_vers_http(agent):
    """Bloquer le 443 ne doit pas suffire à faire voyager le script en clair."""
    assert "http://" not in _fonction(agent, "curl_osiris")


def test_le_scellement_efface_le_jeton_de_la_vm_de_construction():
    source = open("templates/bootstrap-linux.sh.j2", encoding="utf-8").read()
    scellement = source[source.index('if [ "$SEAL" -eq 1 ]; then'):]
    assert "rm -rf /var/lib/osiris" in scellement


def test_l_agent_n_annonce_plus_le_deploiement_lui_meme(agent):
    """Après un redéploiement, son jeton peut dater du précédent : c'est le script,
    porteur du jeton de CE déploiement, qui annonce « deploying »."""
    assert "status=deploying" not in agent


def test_le_jeton_du_dernier_deploiement_prime_sur_celui_de_la_creation(tmp_path, agent):
    """Après un redéploiement, le canal de l'hyperviseur garde le jeton d'origine ;
    le fichier, lui, porte le jeton courant."""
    courant = "courant" + JETON[7:]
    assert _jeton(tmp_path, agent, guestinfo=JETON, fichier=courant) == courant
