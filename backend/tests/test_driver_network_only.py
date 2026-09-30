# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Injection hors-ligne « réseau seul » (main.py + winpe-deploy.cmd.j2).

Le pack constructeur complet injecté hors-ligne dans une image Windows 11 récente
(24H2/25H2) fige la passe PnP de sysprep — « SYSPRP SPPNP … Total = 0 » en boucle
puis « l'ordinateur a redémarré de manière inattendue » (EliteBook 840 G9, 29/09).
Un pack marqué `network_only` ne fait injecter que ses pilotes réseau (Class=Net,
sans co-installeur) ; le reste vient ensuite en ligne (Windows Update / inbox).
"""
from types import SimpleNamespace

import pytest

import main

NET_GUID = "{4d36e972-e325-11ce-bfc1-08002be10318}"


def _inf(root, rel, body):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


@pytest.fixture
def pack(tmp_path, monkeypatch):
    """Un pack factice sous WIN_SHARE_PATH, prêt pour _network_driver_infs."""
    share = tmp_path
    monkeypatch.setattr(main, "WIN_SHARE_PATH", str(share))
    root = share / "drivers" / "hp" / "monpack"
    root.mkdir(parents=True)
    return SimpleNamespace(local_path=str(root)), root


# ── Sélection des pilotes réseau ───────────────────────────────────────────────

def test_garde_les_pilotes_class_net(pack):
    p, root = pack
    _inf(root, "Network/carte.inf", "[Version]\nClass=Net\nClassGuid=%s\n" % NET_GUID)
    out = main._network_driver_infs(p)
    assert out == ["drivers\\hp\\monpack\\Network\\carte.inf"]


def test_reconnait_net_par_le_classguid_seul(pack):
    """Certains .inf ne posent pas `Class=Net` en clair mais seulement le GUID."""
    p, root = pack
    _inf(root, "wifi.inf", "[Version]\nClassGUID = %s\n" % NET_GUID)
    assert main._network_driver_infs(p) == ["drivers\\hp\\monpack\\wifi.inf"]


def test_ecarte_les_pilotes_non_reseau(pack):
    p, root = pack
    _inf(root, "chipset.inf", "[Version]\nClass=System\n")
    _inf(root, "audio.inf", "[Version]\nClass=MEDIA\n")
    assert main._network_driver_infs(p) == []


def test_ecarte_un_pilote_reseau_a_co_installeur(pack):
    """Un co-installeur incompatible est justement ce qui fige sysprep : on
    l'écarte même quand le pilote est de classe réseau (cas du WWAN Fibocom)."""
    p, root = pack
    _inf(root, "wwan.inf",
         "[Version]\nClass=Net\n[Reg]\nHKR,,CoInstallers32,,\"foo.dll\"\n")
    assert main._network_driver_infs(p) == []


def test_lit_un_inf_en_utf16(pack):
    """Les .inf d'un pack constructeur mêlent ANSI et UTF-16 (BOM)."""
    p, root = pack
    (root / "utf16.inf").write_bytes(
        ("[Version]\nClass=Net\n").encode("utf-16"))
    assert main._network_driver_infs(p) == ["drivers\\hp\\monpack\\utf16.inf"]


def test_dossier_absent_rend_liste_vide(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "WIN_SHARE_PATH", str(tmp_path))
    p = SimpleNamespace(local_path=str(tmp_path / "nexiste_pas"))
    assert main._network_driver_infs(p) == []


# ── Rendu du template WinPE ────────────────────────────────────────────────────

def _render(driver_dir, net_driver_infs):
    return main.jinja_env.get_template("winpe-deploy.cmd.j2").render(
        machine=SimpleNamespace(hostname="TESTPC", client="Acme"),
        profile={"tv_suffix": "", "win_image": ""},
        mac="aabbccddeeff",
        osiris_url="http://osiris",
        osiris_ip="10.0.0.1",
        win_index=6,
        locale="fr-FR",
        driver_dir=driver_dir,
        net_driver_infs=net_driver_infs,
    )


def test_rendu_reseau_seul_injecte_inf_par_inf(pack):
    infs = ["drivers\\hp\\monpack\\Network\\a.inf",
            "drivers\\hp\\monpack\\Network\\b.inf"]
    out = _render("drivers\\hp\\monpack", infs)
    # une ligne DISM par .inf, pas de /Recurse
    assert '/Add-Driver /Driver:"Z:\\drivers\\hp\\monpack\\Network\\a.inf"' in out
    assert '/Add-Driver /Driver:"Z:\\drivers\\hp\\monpack\\Network\\b.inf"' in out
    assert "/Recurse" not in out
    assert "reseau seul" in out


def test_rendu_pack_normal_garde_le_recurse(pack):
    """net_driver_infs=None (pack non marqué) → comportement historique inchangé."""
    out = _render("drivers\\hp\\monpack", None)
    assert "/Recurse" in out
    assert "reseau seul" not in out


def test_rendu_vm_n_injecte_rien(pack):
    out = _render("", None)
    assert "injection de drivers ignoree" in out
    assert "/Add-Driver" not in out
