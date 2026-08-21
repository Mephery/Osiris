# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un clone Windows restait nommé WIN-DUAJQ4V5LOA après un déploiement réussi.

Découvert le 21/08 sur le premier clone Windows du vCenter : statut `deployed`,
inventaire matériel remonté, LAPS posé, smoke tests au vert… et une machine
portant toujours le nom aléatoire tiré par sysprep.

La cause est structurelle, pas accidentelle. Sur la voie PXE, le nom vient du
`<ComputerName>` d'un fichier de réponses écrit POUR CETTE MACHINE par WinPE.
Sur la voie clone, c'est impossible : le fichier de réponses d'un gabarit sert à
tous ses clones et ne peut donc contenir aucun nom. Personne ne prenait le
relais — alors que côté Linux le firstboot fait `hostnamectl set-hostname`.

Le cas le plus grave n'est pas le nom en lui-même : `Add-Computer` joignait le
domaine SANS `-NewName`, donc l'objet créé dans l'AD portait le nom aléatoire.
"""
import pytest
from jinja2 import Environment, FileSystemLoader

PROFIL = {
    "locale": "fr-FR", "keyboard": "fr", "timezone": "Europe/Paris",
    "join_domain": False, "domain": "", "domain_join_user": "", "domain_join_password": "",
    "enable_bitlocker": False, "bitlocker_pin": False, "laps_rotation_days": 0,
    "network_drives": "", "printers": "", "post_script": "",
    "wifi_ssid": "", "wifi_password": "", "default_user": "osiris",
}
AVEC_DOMAINE = dict(PROFIL, join_domain=True, domain="exemple.local",
                    domain_join_user="svc_join", domain_join_password="secret")


def _rendu(hostname="nk-win-test01", profil=None):
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    return env.get_template("firstboot-windows.ps1.j2").render(
        machine=type("M", (), {"hostname": hostname, "mac": "aabbccddeeff", "ou": ""})(),
        profile=dict(profil or PROFIL),
        tv_password="", win_apps=[], osiris_url="http://osiris", osiris_ip="10.0.0.1",
        bios_password="", forced_mac="",
    )


def _code(script: str) -> str:
    """Le script SANS ses commentaires.

    Indispensable ici : les commentaires de ce template citent `Rename-Computer`,
    `NetBIOS` et jusqu'au nom `WIN-DUAJQ4V5LOA` pour expliquer le pourquoi. Une
    assertion sur le texte brut passerait donc au vert même si tout le code
    disparaissait — c'est exactement le genre de test qui ne sert à rien.
    """
    return "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))


# ── Le nom est-il posé ? ──────────────────────────────────────────────────────

def test_le_nom_voulu_arrive_dans_le_script():
    assert "nk-win-test01" in _code(_rendu())


def test_hors_domaine_un_renommage_autonome_a_lieu():
    assert "Rename-Computer" in _code(_rendu())


def test_le_renommage_ne_se_declenche_pas_si_le_nom_est_deja_bon():
    """La voie PXE nomme déjà la machine : la rejouer coûterait un redémarrage
    de plus à chaque déploiement de PC physique, pour rien."""
    assert "-ieq $nomVoulu" in _code(_rendu())


# ── Le cas qui touchait l'AD ──────────────────────────────────────────────────

def test_avec_domaine_le_nom_est_pose_PAR_la_jonction():
    """Renommer puis joindre créerait l'objet AD sous l'ancien nom : le renommage
    n'est effectif qu'au redémarrage, la jonction est immédiate."""
    code = _code(_rendu(profil=AVEC_DOMAINE))
    assert "$djArgs['NewName'] = $nomVoulu" in code


def test_une_jonction_reussie_consomme_le_renommage():
    """Sans cela, `Rename-Computer` repasserait derrière la jonction sur une
    machine désormais dans le domaine — et échouerait faute d'identifiants."""
    code = _code(_rendu(profil=AVEC_DOMAINE))
    apres_jonction = code.split("Add-Computer @djArgs")[1]
    assert "$renommageAFaire = $false" in apres_jonction.split("Rename-Computer")[0]


# ── Garde-fous ────────────────────────────────────────────────────────────────

def test_un_nom_trop_long_est_refuse_et_dit():
    """NetBIOS plafonne à 15 caractères. Sans ce garde-fou, `Rename-Computer`
    lève une exception et le déploiement s'arrête sur une machine par ailleurs
    parfaitement fonctionnelle."""
    assert "-gt 15" in _code(_rendu())


def test_un_renommage_rate_n_emporte_pas_le_deploiement():
    bloc = _code(_rendu()).split("Rename-Computer")[1]
    assert "AVERTISSEMENT" in bloc


def test_sans_nom_on_ne_touche_a_rien():
    """Une fiche machine sans hostname ne doit pas produire un renommage vide."""
    assert "if (-not $nomVoulu)" in _code(_rendu(hostname=""))


# ── Non-régression ────────────────────────────────────────────────────────────

def test_la_jonction_au_domaine_reste_entiere():
    code = _code(_rendu(profil=AVEC_DOMAINE))
    assert "Add-Computer @djArgs" in code
    assert "$djMaxEssais" in code
