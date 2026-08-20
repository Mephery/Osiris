# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Temps et dépôts : deux réglages que l'image cloud pose pour le monde ouvert.

Une image Ubuntu arrive avec les pools NTP publics et le miroir apt d'origine.
Sur un réseau qui n'autorise que certaines destinations — le cas de tous les VLAN
de Namek — les deux sont injoignables, et le silence coûte cher.

Pour l'heure, ce n'est pas du confort : Kerberos refuse toute authentification
au-delà de cinq minutes d'écart. Une machine qui dérive perd sa jonction au
domaine, et pas un message ne parle d'horloge.

Ces réglages passent par les directives NATIVES de cloud-init, pas par le script
de premier démarrage : ils s'appliquent donc même quand la machine ne joint jamais
OSIRIS, et le miroir est en place AVANT la première installation de paquet.
"""
import re

import yaml

import main

_BASE = {
    "os": "ubuntu", "default_user": "humains", "join_domain": False,
    "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0,
    "ssh_authorized_keys": "", "ntp_servers": [], "apt_mirror": "", "apt_proxy": "",
}


def _rendu(**surcharges) -> dict:
    """Le cloud-init tel qu'il partirait vers la VM, relu en YAML."""
    profil = dict(_BASE)
    profil.update(surcharges)
    contenu = main.jinja_env.get_template("cloud-init-user-data.j2").render(
        machine={"hostname": "srv-test", "password_hash": "", "mac": "aabbccddeeff"},
        profile=profil, linux_apps=[], mac="aabbccddeeff",
        osiris_url="http://osiris.test", firstboot_b64="IyEvYmluL2Jhc2gK",
    )
    return yaml.safe_load(contenu)


def test_un_profil_sans_reglage_ne_change_rien():
    """Tous les profils existants ont ces champs vides : le cloud-init doit rester
    identique à ce qu'il était, sans directive ajoutée."""
    doc = _rendu()
    assert "ntp" not in doc
    assert "apt" not in doc


def test_les_serveurs_de_temps_sont_poses_par_cloud_init():
    doc = _rendu(ntp_servers=["10.0.0.1", "10.0.0.2"])
    assert doc["ntp"]["enabled"] is True
    assert doc["ntp"]["servers"] == ["10.0.0.1", "10.0.0.2"]


def test_le_miroir_apt_couvre_aussi_les_mises_a_jour_de_securite():
    """Ne remplacer que `primary` laisserait `security` pointer vers le miroir
    d'origine : les correctifs de sécurité — précisément ceux qu'on ne veut pas
    rater — continueraient de viser une destination injoignable."""
    doc = _rendu(apt_mirror="http://miroir.test/ubuntu/")
    assert doc["apt"]["primary"][0]["uri"] == "http://miroir.test/ubuntu/"
    assert doc["apt"]["security"][0]["uri"] == "http://miroir.test/ubuntu/"


def test_le_proxy_apt_seul_ne_touche_pas_aux_miroirs():
    """Un cache apt s'ajoute devant les dépôts d'origine ; il ne les remplace pas."""
    doc = _rendu(apt_proxy="http://cache.test:3142")
    assert doc["apt"]["proxy"] == "http://cache.test:3142"
    assert "primary" not in doc["apt"]


def test_les_depots_sont_configures_avant_installation_des_paquets():
    """Ordre indispensable : `apt:` doit précéder `packages:`, sinon la première
    installation viserait encore le miroir de l'image."""
    profil = dict(_BASE, apt_mirror="http://miroir.test/ubuntu/")

    class _App:
        name, apt_package, linux_post_install = "VLC", "vlc", ""

    contenu = main.jinja_env.get_template("cloud-init-user-data.j2").render(
        machine={"hostname": "srv", "password_hash": "", "mac": "aabbccddeeff"},
        profile=profil, linux_apps=[_App()], mac="aabbccddeeff",
        osiris_url="http://osiris.test", firstboot_b64="IyEvYmluL2Jhc2gK",
    )
    # Sur les clés YAML en début de ligne, pas sur la première occurrence du texte :
    # les commentaires du gabarit citent ces mots et fausseraient la comparaison.
    position = {cle: re.search(rf"^{cle}:", contenu, re.MULTILINE).start()
                for cle in ("apt", "packages")}
    assert position["apt"] < position["packages"]


def test_le_cloud_init_reste_valide_avec_tous_les_reglages():
    """Trois blocs YAML générés côte à côte : une erreur d'indentation casserait le
    cloud-init entier, et la VM ne dirait jamais pourquoi."""
    doc = _rendu(ntp_servers=["10.0.0.1"],
                 apt_mirror="http://miroir.test/ubuntu/",
                 apt_proxy="http://cache.test:3142")
    assert isinstance(doc, dict)
    assert doc["ntp"]["servers"] == ["10.0.0.1"]
    assert doc["apt"]["proxy"] == "http://cache.test:3142"
    # Les directives d'origine survivent
    assert doc["hostname"] == "srv-test"
    assert "write_files" in doc


def test_les_serveurs_sont_nettoyes_des_espaces_a_la_lecture_du_profil():
    """Le champ est saisi à la main, séparé par des virgules : « a, b » ne doit pas
    produire un serveur nommé « espace-b »."""
    from models import Profile

    ctx = main._profile_for_template(
        Profile(name="p", os="ubuntu", ntp_servers=" 10.0.0.1 ,10.0.0.2 ")
    )
    assert ctx["ntp_servers"] == ["10.0.0.1", "10.0.0.2"]


def _firstboot(ntp):
    return main._firstboot_linux_content(
        hostname="srv", mac="aabbccddeeff", ou="",
        profile_ctx=dict(_BASE, ntp_servers=ntp),
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test",
    )


def test_la_source_de_temps_est_verifiee_apres_deploiement():
    """Une horloge qui dérive est une panne AD en préparation, et rien d'autre ne
    la signale : Kerberos refuse au-delà de cinq minutes, sans jamais parler
    d'heure."""
    script = _firstboot(["10.0.0.1"])
    assert '_add_test "Serveur de temps"' in script
    assert "timedatectl show-timesync" in script


def test_le_verdict_porte_sur_la_source_pas_sur_la_synchronisation():
    """La synchronisation peut demander plus que les secondes écoulées depuis le
    démarrage. Un test qui échouerait une fois sur deux sur une machine saine
    cesserait vite d'être lu — le verdict porte donc sur la présence d'une source
    active, et l'état de synchro voyage dans le détail."""
    script = _firstboot(["10.0.0.1"])
    verdict = script.split('if [ -n "$_ntp_src" ]')[1].split("fi")[0]
    assert '"Serveur de temps" true' in verdict
    assert "synchronise" in verdict, "l'état de synchro doit rester visible, en détail"


def test_aucun_controle_de_temps_si_le_profil_nen_demande_pas():
    """Un profil qui laisse le NTP par défaut ne doit pas produire de contrôle."""
    assert '_add_test "Serveur de temps"' not in _firstboot([])
