# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Sort de l'hôte Zabbix quand une machine quitte OSIRIS.

Chaque VM supprimée laissait un hôte orphelin, qui alertait « agent injoignable »
jusqu'à ce que quelqu'un le retire à la main (huit d'un coup le 07/10). Le choix
revient à l'opérateur : ne rien changer, désactiver (garde l'historique),
supprimer (VM de test). OSIRIS n'agit QUE sur un hôte de son groupe.

L'API Zabbix est simulée (`_call`).
"""
import pytest

import zabbix

GROUPE = "OSIRIS-deployes"


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    monkeypatch.setattr(zabbix, "ZABBIX_API_URL", "http://zbx/api_jsonrpc.php")
    monkeypatch.setattr(zabbix, "ZABBIX_API_TOKEN", "tok")
    monkeypatch.setattr(zabbix, "ZABBIX_DEPLOYED_GROUP", GROUPE)


def _zabbix(monkeypatch, *, groupes=(GROUPE,), existe=True, actif=True,
            refus=None, ancien=False):
    """Faux Zabbix. `ancien` = avant 6.2 (selectGroups) ; `refus` = méthode que
    le rôle du jeton n'autorise pas."""
    appels = []

    def faux(method, params, auth=True):
        appels.append((method, params))
        if method == refus:
            raise RuntimeError(f'Zabbix {method} : No permissions to call "{method}".')
        if method == "host.get":
            if ancien and "selectHostGroups" in params:
                raise RuntimeError("Zabbix host.get : Invalid parameter")
            if not existe:
                return []
            champ = "groups" if ancien else "hostgroups"
            return [{"hostid": "42", "host": "vm-t01", "status": "0" if actif else "1",
                     champ: [{"name": g} for g in groupes]}]
        return {"hostids": ["42"]}

    monkeypatch.setattr(zabbix, "_call", faux)
    return appels


def _methodes(appels):
    return [m for m, _ in appels]


# ── Ce que montre la fenêtre ──────────────────────────────────────────────────

def test_etat_d_un_hote_osiris(monkeypatch):
    _zabbix(monkeypatch)
    e = zabbix.etat_hote("vm-t01")
    assert e == {"configure": True, "existe": True, "actif": True, "gere": True,
                 "groupes": [GROUPE]}


def test_un_sous_groupe_d_organisation_est_gere(monkeypatch):
    _zabbix(monkeypatch, groupes=(f"{GROUPE}/Acme",))
    assert zabbix.etat_hote("vm-t01")["gere"] is True


def test_un_groupe_au_nom_voisin_n_est_pas_gere(monkeypatch):
    """« OSIRIS-deployes-old » commence pareil, mais n'est pas notre groupe."""
    _zabbix(monkeypatch, groupes=(f"{GROUPE}-old",))
    assert zabbix.etat_hote("vm-t01")["gere"] is False


def test_hote_absent(monkeypatch):
    _zabbix(monkeypatch, existe=False)
    assert zabbix.etat_hote("vm-t01") == {"configure": True, "existe": False}


def test_zabbix_injoignable_n_empeche_pas_d_ouvrir_la_fenetre(monkeypatch):
    def boom(*a, **k):
        raise OSError("timeout")
    monkeypatch.setattr(zabbix, "_call", boom)
    assert "erreur" in zabbix.etat_hote("vm-t01")


def test_non_configure(monkeypatch):
    monkeypatch.setattr(zabbix, "ZABBIX_API_URL", "")
    assert zabbix.etat_hote("vm-t01") == {"configure": False}


def test_zabbix_avant_6_2_lit_les_groupes_a_l_ancienne(monkeypatch):
    _zabbix(monkeypatch, ancien=True)
    assert zabbix.etat_hote("vm-t01")["gere"] is True


# ── Le retrait ────────────────────────────────────────────────────────────────

def test_desactiver(monkeypatch):
    appels = _zabbix(monkeypatch)
    assert zabbix.retirer_hote("vm-t01", "desactiver") == "desactive"
    assert ("host.update", {"hostid": "42", "status": 1}) in appels
    assert "host.delete" not in _methodes(appels)


def test_supprimer(monkeypatch):
    appels = _zabbix(monkeypatch)
    assert zabbix.retirer_hote("vm-t01", "supprimer") == "supprime"
    assert ("host.delete", ["42"]) in appels


def test_rien_ne_parle_meme_pas_a_zabbix(monkeypatch):
    appels = _zabbix(monkeypatch)
    assert zabbix.retirer_hote("vm-t01", "rien") == "inchange"
    assert appels == []


@pytest.mark.parametrize("action", ["desactiver", "supprimer"])
def test_un_hote_hors_du_groupe_osiris_reste_intact(monkeypatch, action):
    """Un vrai serveur du même nom, ajouté à la main : un nom ne prouve rien."""
    appels = _zabbix(monkeypatch, groupes=("Serveurs/Production",))
    assert zabbix.retirer_hote("vm-t01", action) == "non-gere"
    assert _methodes(appels) == ["host.get"]


def test_hote_deja_absent(monkeypatch):
    _zabbix(monkeypatch, existe=False)
    assert zabbix.retirer_hote("vm-t01", "supprimer") == "absent"


def test_un_refus_du_role_est_explique(monkeypatch):
    """Le jeton n'avait pas `host.delete` à l'origine : l'opérateur doit savoir
    POURQUOI, et où agir — pas lire « No permissions » en anglais."""
    _zabbix(monkeypatch, refus="host.delete")
    with pytest.raises(RuntimeError, match="rôle Zabbix.*host.delete"):
        zabbix.retirer_hote("vm-t01", "supprimer")


def test_une_action_inconnue_est_refusee(monkeypatch):
    _zabbix(monkeypatch)
    with pytest.raises(ValueError):
        zabbix.retirer_hote("vm-t01", "detruire")
