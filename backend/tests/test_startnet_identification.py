# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Tests de l'appel d'identification émis par startnet.cmd (worker.py).

Régression attrapée le 2026-07-28 sur banc de test : l'identifiant matériel avait
été collé directement dans l'URL. Il contient des espaces dès qu'on sort du monde
Lenovo (« Latitude 5420 », « Standard PC (Q35 + ICH9, 2009) »…), l'URL devenait
malformée, curl sortait en erreur 3 et AUCUNE machine Dell ou HP n'aurait plus
été reconnue — bascule silencieuse sur le script générique.
"""
import re

from worker import _make_startnet_cmd


def _startnet() -> str:
    return _make_startnet_cmd().decode("utf-8", errors="replace")


def _code_lines() -> str:
    """startnet.cmd sans ses commentaires (REM), pour ne tester que l'exécuté."""
    return "\n".join(
        l for l in _startnet().splitlines()
        if not l.strip().upper().startswith("REM")
    )


def test_les_valeurs_ne_sont_jamais_collees_dans_l_url():
    """Le cœur de la régression : aucune query string construite à la main.
    Les valeurs doivent passer par --data-urlencode, jamais par « ?a=%VAR% »."""
    code = _code_lines()
    assert "winpe-auto?" not in code
    assert "&sysid=" not in code


def test_curl_encode_les_deux_identifiants():
    txt = _startnet()
    assert '--data-urlencode "serial=%OSSERIAL%"' in txt
    assert '--data-urlencode "sysid=%OSSYSID%"' in txt
    assert "--get" in txt


def test_l_identifiant_materiel_est_bien_collecte():
    txt = _startnet()
    assert "wmic csproduct get name" in txt
    assert "set OSSYSID=" in txt


def test_la_lecture_de_l_identifiant_ne_bloque_jamais():
    """Best-effort comme le numéro de série : une machine dont la lecture échoue
    doit continuer à se déployer, pas rester coincée en WinPE."""
    txt = _startnet()
    assert "2>nul" in txt
    # la boucle de nettoyage des espaces doit avoir une sortie inconditionnelle
    assert ":sidready" in txt
    assert "if not defined OSSYSID goto sidready" in txt


def test_pas_de_findstr_ni_de_powershell():
    """Ni l'un ni l'autre n'existe dans ce WinPE (vérifié sur l'image).
    On ne regarde que le code : les commentaires ont le droit de les nommer,
    c'est même là qu'on explique pourquoi on s'en passe."""
    code = _code_lines().lower()
    assert "findstr" not in code
    assert "powershell" not in code


def test_les_pilotes_sont_charges_depuis_system32_avant_wpeinit():
    """Les pilotes injectés par wimboot atterrissent dans \\Windows\\System32\\ ;
    ils doivent être chargés AVANT wpeinit, sinon la carte n'existe pas encore."""
    txt = _startnet()
    drvload = txt.index("X:\\Windows\\System32\\*.inf")
    wpeinit = txt.index("wpeinit")
    assert drvload < wpeinit


def test_la_boucle_de_nettoyage_du_serial_ne_boucle_pas_indefiniment():
    """Piège batch connu : « if cond cmd & goto » exécute le goto sans condition."""
    for label in (":trimsn", ":trimsid"):
        bloc = _startnet().split(label, 1)[1][:400]
        assert not re.search(r"if .*&\s*goto", bloc)
