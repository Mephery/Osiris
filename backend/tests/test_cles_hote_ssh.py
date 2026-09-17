# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un clone nu se déployait sans clés d'hôte SSH, donc injoignable.

Le scellement supprime les clés d'hôte — exprès : sans ça, tous les clones
partageraient la même identité SSH et un vrai intercepteur passerait inaperçu.
Encore faut-il que quelqu'un les regénère.

Sur un clone en cloud-init, c'est cloud-init qui s'en charge. Sur un clone NU il
n'y a aucune source de données, le module ne tourne pas, aucune clé n'est
générée — et sshd refuse de démarrer. La machine se déploie, OSIRIS la déclare
réussie, et personne ne peut s'y connecter.

Constaté le 17/09, juste après avoir (correctement) coupé l'héritage des
métadonnées du gabarit : c'est cet héritage qui, par accident, faisait tourner
le module cloud-init qui regénérait les clés.
"""
import re

import pytest
from jinja2 import Environment, FileSystemLoader


@pytest.fixture(scope="module")
def firstboot() -> str:
    return open("templates/firstboot-ubuntu.sh.j2", encoding="utf-8").read()


def _code(script: str) -> str:
    return "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))


def test_les_cles_d_hote_sont_regenerees(firstboot):
    assert "ssh-keygen -A" in _code(firstboot)


def test_la_regeneration_precede_le_redemarrage(firstboot):
    """Dans l'autre ordre, sshd redémarre sans clés et échoue quand même."""
    code = _code(firstboot)
    assert code.index("ssh-keygen -A") < code.index("systemctl restart ssh"), \
        "les clés doivent exister AVANT que sshd ne tente de démarrer"


def test_un_sshd_qui_ne_demarre_pas_est_DIT(firstboot):
    """Le message d'origine annonçait « auth désactivée, root interdit » même
    quand sshd était mort : un compte rendu qui décrit une configuration au lieu
    de constater un état."""
    assert "sshd ne demarre pas" in firstboot


def test_l_etat_est_VERIFIE_et_pas_suppose(firstboot):
    assert re.search(r"systemctl is-active --quiet ssh", _code(firstboot))
