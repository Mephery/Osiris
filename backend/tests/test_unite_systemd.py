# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Ce que le service doit faire avant de se déclarer prêt.

Ces contrôles lisent le fichier d'unité livré par le dépôt. Ils ne disent rien de
la copie installée dans /etc — mais ils garantissent que ce qu'on distribue est
correct, et ils vivent à part de `test_migrations.py`, qui exige une base Postgres
jetable et se saute entièrement sans elle.
"""
from pathlib import Path


def test_lunite_systemd_applique_les_migrations_avant_de_servir():
    """Le service doit jouer Alembic AVANT uvicorn — et l'oubli ne se voit pas.

    Constaté le 2026-08-18 : `init_db()` ne fait qu'un `create_all`, qui crée les
    tables manquantes mais JAMAIS les colonnes manquantes. Un déploiement ajoutant
    une révision laissait donc la base en arrière, et l'unité démarrait quand même :
    `systemctl status` affichait « active (running) », `/health` répondait 200 — il
    ne touche aucune table métier — pendant que toute requête sur une machine
    tombait en `UndefinedColumn`. Une panne totale sous les apparences d'un
    démarrage réussi.

    Ce test lit le fichier d'unité livré par le dépôt. Il ne prouve rien sur la
    copie installée dans /etc, mais il garantit que ce qu'on distribue est correct.
    """
    unite = (Path(__file__).resolve().parents[2] / "osiris-api.service").read_text()

    assert "ExecStartPre=" in unite and "alembic upgrade head" in unite, \
        "l'unite doit appliquer les migrations avant de servir"
    assert unite.index("ExecStartPre=") < unite.index("ExecStart="), \
        "les migrations doivent precer le lancement de l'API"
    assert "WorkingDirectory=/opt/osiris/backend" in unite, \
        "alembic.ini et le .env y sont : Alembic echoue ailleurs"
