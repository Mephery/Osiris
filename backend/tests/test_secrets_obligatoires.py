# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les secrets qui protègent l'installation doivent manquer bruyamment.

Une valeur de repli dans un dépôt ouvert n'est pas un défaut : c'est une valeur
*publique*. Un JWT_SECRET absent signerait les jetons avec une chaîne que tout le
monde peut lire, et un ADMIN_PASSWORD absent créerait un compte administrateur
dont le mot de passe est écrit dans le code. Ces tests vérifient que ces deux
situations arrêtent OSIRIS au lieu de le laisser démarrer en apparence sain.
"""
import os
import subprocess
import sys
import tempfile

import pytest
from sqlmodel import Session, select

from models import User, engine

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _importer_auth(valeur_jwt):
    """Importe `auth` dans un interpréteur neuf, avec le JWT_SECRET donné.

    En sous-processus et non par `importlib.reload` : le module est déjà chargé
    par la suite de tests, et le recharger avec un secret invalide laisserait
    les autres tests avec une clé de signature différente.
    """
    env = {**os.environ, "PYTHONPATH": RACINE}
    if valeur_jwt is None:
        env.pop("JWT_SECRET", None)
    else:
        env["JWT_SECRET"] = valeur_jwt
    # Le processus part d'un répertoire vide, et pas de la racine du backend :
    # `models` appelle load_dotenv(), qui relirait le .env réel de la machine et
    # rendrait le retrait de la variable sans effet. Le test ne mesurerait alors
    # que la présence d'un fichier de configuration.
    with tempfile.TemporaryDirectory() as ailleurs:
        return subprocess.run(
            [sys.executable, "-c", "import auth"],
            capture_output=True, text=True, env=env, cwd=ailleurs,
        )


def test_jwt_secret_absent_empeche_le_demarrage():
    r = _importer_auth(None)
    assert r.returncode != 0
    assert "JWT_SECRET" in r.stderr


def test_jwt_secret_vide_empeche_le_demarrage():
    # Une variable présente mais vide est le cas réel : un .env recopié et
    # jamais rempli. Elle ne doit pas être plus permissive qu'une absence.
    r = _importer_auth("   ")
    assert r.returncode != 0
    assert "JWT_SECRET" in r.stderr


def test_jwt_secret_laisse_a_la_valeur_d_exemple_est_refuse():
    # Cette chaîne a été la valeur de repli du code : elle est dans l'historique
    # public du dépôt, donc connue de quiconque le lit.
    r = _importer_auth("changeme-generate-a-real-secret")
    assert r.returncode != 0
    assert "JWT_SECRET" in r.stderr


def test_jwt_secret_propre_est_accepte():
    assert _importer_auth("un-secret-bien-a-cette-installation").returncode == 0


def test_admin_par_defaut_refuse_le_mot_de_passe_d_exemple(monkeypatch):
    """Le refus doit tomber au moment de créer le compte, pas au chargement."""
    import main

    # Base sans aucun utilisateur : c'est la seule situation où _seed_admin agit.
    with Session(engine) as session:
        for u in session.exec(select(User)).all():
            session.delete(u)
        session.commit()

    monkeypatch.setattr(main, "ADMIN_PASSWORD", "changeme")
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        main._seed_admin()

    with Session(engine) as session:
        assert session.exec(select(User)).first() is None, \
            "aucun compte ne doit avoir ete cree"


def test_admin_par_defaut_cree_le_compte_avec_un_vrai_mot_de_passe(monkeypatch):
    import main

    with Session(engine) as session:
        for u in session.exec(select(User)).all():
            session.delete(u)
        session.commit()

    monkeypatch.setattr(main, "ADMIN_PASSWORD", "un-mot-de-passe-choisi")
    main._seed_admin()

    with Session(engine) as session:
        assert session.exec(select(User)).first() is not None
