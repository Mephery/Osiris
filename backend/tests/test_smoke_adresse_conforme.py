# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Une machine peut être verte partout et tourner sur la mauvaise adresse.

Constaté le 17/09 : une VM déployée en cloud-init, tous les smoke tests au vert,
tournait sur une adresse DHCP alors que sa fiche en annonçait une fixe. L'image
Debian livrait `network: {config: disabled}` dans sa configuration cloud-init —
le nom d'hôte injecté a donc été appliqué, et le réseau ignoré.

C'est le pire cas de la famille : la machine MARCHE. Elle répond, elle se
supervise, elle passe « ping passerelle » — sur une adresse qui n'est pas la
sienne selon l'inventaire. La personne qui cherchera ce serveur à l'adresse
écrite dans OSIRIS ne trouvera personne, ou pire, trouvera quelqu'un d'autre.

Les tests exécutent le bloc réellement rendu, contre un faux `ip`, plutôt que de
relire son texte : c'est une comparaison de chaînes, exactement le genre de code
qui a l'air juste et se trompe d'un caractère.
"""
import subprocess
import textwrap

import pytest
from jinja2 import Environment, FileSystemLoader


def _rendu(ip_cidr: str) -> str:
    """Le bloc de conformité d'adresse, rendu pour une fiche donnée."""
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters["bash_squote"] = lambda v: "'" + str(v).replace("'", "'\\''") + "'"
    src = env.loader.get_source(env, "firstboot-ubuntu.sh.j2")[0]
    debut = src.index("# L'adresse REELLE correspond-elle")
    fin = src.index("# Ping passerelle par defaut.")
    return env.from_string(src[debut:fin]).render(
        ip_attendue=(ip_cidr or "").split("/")[0])


def _lancer(bloc: str, tmp_path, adresses: str) -> str:
    """Exécute le bloc avec un `ip` bidon qui rend les adresses données."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    faux = d / "ip"
    # Format de `ip -o` : « 2: eth0    inet 10.0.5.20/24 brd ... scope global eth0 »
    # C'est le CHAMP 4 que lit le script ; un faux qui décale les colonnes
    # testerait autre chose que la vraie commande.
    lignes = "\n".join(
        f'echo "{i+2}: eth{i}    inet {a} brd 10.0.5.255 scope global eth{i}"'
        for i, a in enumerate(adresses.split()))
    faux.write_text("#!/bin/bash\n" + (lignes or "true") + "\n")
    faux.chmod(0o755)
    script = tmp_path / "t.sh"
    script.write_text(
        f'export PATH="{d}:$PATH"\n'
        '_add_test() { echo "TEST|$1|$2|${3:-}"; }\n'
        f'{textwrap.dedent(bloc)}\n')
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=30)
    return r.stdout + r.stderr


def test_adresse_conforme(tmp_path):
    sortie = _lancer(_rendu("10.0.5.20/24"), tmp_path, "10.0.5.20/24")
    assert "TEST|Adresse conforme a la fiche|true|" in sortie


def test_adresse_DIFFERENTE_est_signalee(tmp_path):
    """Le cas réel : la fiche dit une chose, la machine en a une autre."""
    sortie = _lancer(_rendu("10.0.5.20/24"), tmp_path, "10.0.5.66/24")
    assert "TEST|Adresse conforme a la fiche|false|" in sortie
    assert "10.0.5.20" in sortie and "10.0.5.66" in sortie, \
        "le détail doit nommer LES DEUX adresses, sinon il n'aide pas à trancher"


def test_le_prefixe_ne_compte_PAS(tmp_path):
    """C'est l'adresse qui sert à joindre la machine. Un /24 écrit /25 par
    erreur ne justifie pas de crier au loup sur une machine joignable."""
    sortie = _lancer(_rendu("10.0.5.20/24"), tmp_path, "10.0.5.20/25")
    assert "TEST|Adresse conforme a la fiche|true|" in sortie


def test_plusieurs_cartes_la_bonne_suffit(tmp_path):
    """Un serveur multi-cartes est légitime : on cherche l'adresse attendue
    parmi celles qu'il porte, on n'exige pas qu'il n'en ait qu'une."""
    sortie = _lancer(_rendu("10.0.5.20/24"), tmp_path, "172.17.0.1/16 10.0.5.20/24")
    assert "TEST|Adresse conforme a la fiche|true|" in sortie


def test_une_adresse_qui_RESSEMBLE_ne_passe_pas(tmp_path):
    """`grep -qx` et non `grep -q` : sans l'ancrage, « 10.0.5.2 » attendu serait
    satisfait par « 10.0.5.20 » porté par la machine."""
    sortie = _lancer(_rendu("10.0.5.2/24"), tmp_path, "10.0.5.20/24")
    assert "TEST|Adresse conforme a la fiche|false|" in sortie


def test_aucune_adresse_du_tout_est_signalee(tmp_path):
    """Le cas APIPA : la machine a démarré sans rien obtenir."""
    sortie = _lancer(_rendu("10.0.5.20/24"), tmp_path, "")
    assert "TEST|Adresse conforme a la fiche|false|" in sortie


def test_sans_adresse_sur_la_fiche_aucun_test_n_est_emis(tmp_path):
    """Une machine en DHCP n'a rien promis : la juger sur une promesse absente
    produirait une alarme permanente, et une alarme permanente cesse d'être lue.

    On vérifie qu'aucun test n'est ÉMIS — les commentaires, eux, restent dans le
    script quoi qu'il arrive, et c'est très bien ainsi.
    """
    sortie = _lancer(_rendu(""), tmp_path, "10.0.5.66/24")
    assert "Adresse conforme" not in sortie
    assert "_add_test" not in _rendu("")


# ── Le câblage, et pas seulement le fragment ──────────────────────────────────

def test_le_bloc_est_REELLEMENT_rendu_par_le_code_de_production():
    """Le test qui manquait, et dont l'absence a coûté un déploiement.

    Les tests ci-dessus rendent le fragment avec un contexte qu'ils fabriquent
    eux-mêmes : ils prouvent que le shell est juste, jamais qu'il est atteint.
    La première version lisait `machine.ip_cidr`, or le vrai rendu passe un
    `machine` volontairement ÉTROIT — un dict de quatre clés, parce que la fiche
    peut ne pas exister en base à cet instant. Jinja rend `Undefined` pour une
    clé absente, `{% if %}` la juge fausse, et le bloc n'a jamais été rendu. Sans
    erreur, sans trace : exactement la famille de défauts que ce bloc traque.

    Celui-ci appelle la vraie fonction de rendu. C'est la seule façon d'attraper
    un décalage de contexte.
    """
    import main
    rendu = main._firstboot_linux_content(
        hostname="srv-test", mac="005056aa0042", ou="",
        profile_ctx={"default_user": "osiris", "vm_data_disk_gb": 0},
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test",
        ip_attendue="10.0.5.20/24",
    )
    assert "Adresse conforme a la fiche" in rendu, \
        "le bloc n'est pas rendu par le code de production"
    assert '_ip_attendue="10.0.5.20"' in rendu, "le préfixe doit être retiré"


def test_sans_adresse_le_code_de_production_n_emet_rien():
    import main
    rendu = main._firstboot_linux_content(
        hostname="srv-test", mac="005056aa0042", ou="",
        profile_ctx={"default_user": "osiris", "vm_data_disk_gb": 0},
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test",
        ip_attendue="",
    )
    assert "_add_test \"Adresse conforme" not in rendu
