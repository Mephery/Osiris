# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les avertissements du premier démarrage n'atteignaient pas OSIRIS.

`_log` fait deux choses : écrire le fichier local ET envoyer la ligne à OSIRIS.
Un `echo` nu ne fait que la première. Les quatre avertissements du script de
premier démarrage — application ratée, agent de supervision qui ne démarre pas,
script du profil en erreur, script de la machine en erreur — utilisaient `echo`.

Ils n'ont donc jamais quitté la machine. Un script de post-installation raté
rendait un journal STRICTEMENT identique à un script réussi : « Script
post-install terminé », et rien d'autre. Le commentaire du code affirmait
pourtant « il se voit dans le journal, qui est le seul témoin sur une machine
distante ».

Constaté le 17/09 en vérifiant l'installation d'une vingtaine de paquets par
`post_script` : impossible de dire, depuis OSIRIS, si elle avait abouti.
"""
import re

import pytest
from jinja2 import Environment, FileSystemLoader


@pytest.fixture(scope="module")
def firstboot() -> str:
    """Le script rendu, avec de quoi déclencher chaque branche d'avertissement."""
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters.setdefault("bash_squote", lambda v: "'" + str(v).replace("'", "'\\''") + "'")
    return env.get_template("firstboot-ubuntu.sh.j2").source if hasattr(
        env.get_template("firstboot-ubuntu.sh.j2"), "source") else open(
        "templates/firstboot-ubuntu.sh.j2", encoding="utf-8").read()


def test_aucun_avertissement_ne_reste_LOCAL(firstboot):
    """Chaque avertissement doit partir vers OSIRIS, pas seulement vers un
    fichier sur une machine que personne n'ira consulter."""
    locaux = re.findall(r'\|\|\s*echo\s+"\[\$\(ts\)\]\s*AVERTISSEMENT[^"]*"', firstboot)
    assert not locaux, f"avertissements qui n'atteignent jamais OSIRIS : {locaux}"


def test_les_quatre_avertissements_passent_par_log(firstboot):
    """Les quatre branches connues : application, supervision, script du profil,
    script de la machine. Si l'une disparaît du script, ce test le dira."""
    envoyes = re.findall(r'\|\|\s*_log\s+"AVERTISSEMENT[^"]*"', firstboot)
    assert len(envoyes) == 4, f"attendu 4, trouvé {len(envoyes)} : {envoyes}"


def _code(script: str) -> str:
    """Le script sans ses commentaires — sinon une phrase qui EXPLIQUE pourquoi
    on n'utilise pas un réglage se lit comme si on l'utilisait."""
    return "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))


def test_log_ecrit_ET_envoie(firstboot):
    """L'invariant dont tout le reste dépend : si `_log` cessait d'appeler
    `_osiris_log`, les quatre corrections ci-dessus redeviendraient muettes
    sans qu'aucun autre test ne s'en aperçoive.

    Ancré en début de ligne : `_log() {` est un SUFFIXE de `_osiris_log() {`,
    et une recherche naïve tombe sur la mauvaise fonction.
    """
    m = re.search(r"^_log\(\) \{(.*?)^\}", firstboot, re.M | re.S)
    assert m, "fonction _log introuvable"
    corps = m.group(1)
    assert "echo" in corps, "l'écriture locale a disparu"
    assert "_osiris_log" in corps, "_log n'envoie plus rien à OSIRIS"


def test_un_script_rate_n_emporte_PAS_le_deploiement(firstboot):
    """L'autre moitié de la décision : on journalise l'échec, mais un script de
    personnalisation raté ne doit pas faire échouer un déploiement par ailleurs
    réussi. C'est le `|| _log` qui porte les deux à la fois."""
    assert "set -e" not in _code(firstboot), \
        "un `set -e` ferait sortir au premier échec, avant la journalisation"
