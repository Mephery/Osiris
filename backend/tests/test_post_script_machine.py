# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un script de post-installation propre à UNE machine, pas à tout un profil.

Le profil en portait déjà un, mais il vaut pour toutes les machines qui l'utilisent.
Personnaliser une seule VM obligeait donc à dupliquer un profil entier pour trois
lignes — puis à maintenir deux profils qui divergent lentement.

Les deux se cumulent, dans cet ordre : le profil pose le socle commun à un type de
machine, le script de la machine ajoute ce qui ne vaut que pour elle. C'est l'ordre
qui donne son sens au mécanisme : l'inverse ferait écraser la spécificité par le
socle.
"""
import main

_PROFIL = {
    "os": "ubuntu", "default_user": "humains", "join_domain": False,
    "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0,
    "post_script": "echo SOCLE-DU-PROFIL",
}


def _script(post_script="", profil=None):
    return main._firstboot_linux_content(
        hostname="srv-odoo", mac="aabbccddeeff", ou="",
        profile_ctx=dict(profil if profil is not None else _PROFIL),
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test",
        post_script=post_script,
    )


def test_le_script_de_la_machine_est_injecte():
    contenu = _script("echo PROPRE-A-CETTE-VM")
    assert "echo PROPRE-A-CETTE-VM" in contenu


def test_il_sexecute_APRES_celui_du_profil():
    """L'ordre porte tout le sens : socle commun d'abord, spécificité ensuite."""
    contenu = _script("echo PROPRE-A-CETTE-VM")
    assert contenu.index("echo SOCLE-DU-PROFIL") < contenu.index("echo PROPRE-A-CETTE-VM")


def test_les_deux_se_cumulent_au_lieu_de_sexclure():
    """Renseigner l'un ne doit pas faire disparaître l'autre — sans quoi il faudrait
    recopier le socle dans chaque VM."""
    contenu = _script("echo PROPRE-A-CETTE-VM")
    assert "echo SOCLE-DU-PROFIL" in contenu
    assert "echo PROPRE-A-CETTE-VM" in contenu


def test_un_echec_ninterrompt_pas_le_deploiement():
    """Une personnalisation ratée ne doit pas emporter un déploiement par ailleurs
    réussi — mais elle doit se voir : le journal est le seul témoin sur une machine
    distante."""
    contenu = _script("false")
    bloc = contenu.split("post-install de la machine")[1]
    assert "AVERTISSEMENT" in bloc


def test_le_script_tourne_dans_un_sous_shell():
    """Isolé du reste du premier démarrage : un `cd`, un `set -e` ou une variable
    laissée derrière ne doivent pas perturber les étapes suivantes — les smoke
    tests, notamment, s'exécutent après."""
    contenu = _script("cd /tmp")
    bloc = contenu.split('_log "Execution du script post-install de la machine..."')[1]
    assert bloc.lstrip().startswith("(")


def test_rien_nest_ajoute_quand_la_machine_na_pas_de_script():
    """Le cas de loin le plus fréquent : la fonctionnalité ne doit rien peser."""
    assert "post-install de la machine" not in _script("")


def test_le_profil_seul_continue_de_fonctionner():
    """Non-régression : le mécanisme existant ne doit pas dépendre du nouveau."""
    contenu = _script("")
    assert "echo SOCLE-DU-PROFIL" in contenu


def test_le_script_de_la_machine_seul_fonctionne_sans_profil():
    """Un profil sans script ne doit pas empêcher la VM d'avoir le sien."""
    profil = dict(_PROFIL, post_script="")
    contenu = _script("echo SEULEMENT-LA-VM", profil=profil)
    assert "echo SEULEMENT-LA-VM" in contenu
    assert "post-install du profil" not in contenu


def test_il_est_conserve_sur_la_fiche_machine():
    """Le script doit survivre à la requête de création : un redéploiement ou une
    relance de /firstboot-* le rejoue, longtemps après."""
    from models import Machine

    assert "post_script" in Machine.model_fields


def test_la_requete_de_creation_de_vm_porte_le_champ():
    assert "post_script" in main.VmCreateBody.model_fields
