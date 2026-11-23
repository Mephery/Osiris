# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un WinPE qui ne démarre pas doit être DIT, jamais laissé en silence.

17/11/2026 : 5 PC HP « G1i » ont reçu WinPE puis sont repartis sur le Windows de
leur disque. Rien n'est revenu vers OSIRIS, les fiches sont restées « deploying »
indéfiniment et l'équipe a dû deviner. La preuve existait pourtant : le PC
redemandait une adresse DHCP sous le nom « DESKTOP-… » au lieu de celui de WinPE.
"""
from datetime import timedelta

import pytest
from sqlmodel import Session, select

import main
from models import engine, Machine, OsImage, Profile, Organization, DeployLogLine, DeploymentEvent

MAC = "b4e25b395e68"
MAC_FIL = "b4:e2:5b:39:5e:68"


@pytest.fixture
def bail(tmp_path, monkeypatch):
    """Fichier de baux dnsmasq factice ; `bail(exp, nom)` le réécrit."""
    f = tmp_path / "dnsmasq.leases"
    monkeypatch.setattr(main, "DNSMASQ_LEASES", str(f))
    main._bail_a_l_envoi.clear()

    def ecrire(expiration: int, nom: str):
        f.write_text(f"{expiration} {MAC_FIL} 10.0.0.127 {nom} 01:{MAC_FIL}\n")
    return ecrire


def _pc(org_webhook: str = ""):
    with Session(engine) as s:
        s.add(OsImage(name="Win11", version="25H2", os="windows",
                      iso_url="file:///tmp/x.iso", status="ready"))
        org = Organization(name="Francas", slug="francas", webhook_url=org_webhook)
        p = Profile(name="P-Win", os="windows", locale="fr-FR")
        s.add(org)
        s.add(p)
        s.commit()
        s.add(Machine(mac=MAC, hostname="FRCLCL04", client="Francas", os="windows",
                      status="pending", profile_id=p.id, organization_id=org.id,
                      hw_serial="1H861365MD"))
        s.commit()


def _machine() -> Machine:
    with Session(engine) as s:
        return s.exec(select(Machine).where(Machine.mac == MAC)).one()


def _journal() -> str:
    with Session(engine) as s:
        return "\n".join(s.exec(select(DeployLogLine.line).where(DeployLogLine.mac == MAC)
                                .order_by(DeployLogLine.id)).all())


def _vieillir(minutes: int):
    with Session(engine) as s:
        m = s.exec(select(Machine).where(Machine.mac == MAC)).one()
        m.winpe_envoye_le = m.winpe_envoye_le - timedelta(minutes=minutes)
        s.add(m)
        s.commit()


# ── /boot arme la surveillance et ne rend plus la main au firmware en silence ──

def test_boot_arme_la_surveillance_et_rattrape_l_echec_ipxe(client, bail):
    bail(1000, "*")
    _pc()
    r = client.get("/boot", params={"mac": MAC_FIL})
    assert r.status_code == 200
    # Plus de `boot` nu en fin de script : un échec doit être rattrapé et affiché.
    assert "boot || goto osiris_winpe_echec" in r.text
    assert ":osiris_winpe_echec" in r.text
    assert f"/boot?mac={MAC}&echec=${{osiris_err}}" in r.text
    assert "prompt" in r.text
    assert _machine().winpe_envoye_le is not None
    assert "WinPE envoyé au PC" in _journal()


# ── Filet DHCP : le PC repart sur son disque ─────────────────────────────────

def test_pc_reparti_sur_son_windows_passe_en_echec_avec_le_nom_vu(client, bail):
    bail(1000, "*")
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})

    bail(8200, "DESKTOP-JOEK76U")      # nouvelle demande DHCP, par le Windows du disque
    declares = main._tour_winpe()

    assert [d[0] for d in declares] == [MAC]
    m = _machine()
    assert m.status == "failed"
    assert m.winpe_envoye_le is None
    j = _journal()
    assert "DESKTOP-JOEK76U" in j and "reparti sur le Windows de son disque" in j
    assert "À faire" in j
    with Session(engine) as s:
        assert s.exec(select(DeploymentEvent).where(
            DeploymentEvent.mac == MAC, DeploymentEvent.status == "failed")).first()


@pytest.mark.parametrize("nom", ["MININT-8K2J4LA", "minwinpc", "*"])
def test_dhcp_de_winpe_n_est_pas_un_echec(client, bail, nom):
    bail(1000, "*")
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})

    bail(8200, nom)
    assert main._tour_winpe() == []
    assert _machine().status == "deploying"


def test_bail_inchange_meme_nom_desktop_n_est_pas_une_preuve(client, bail):
    """Second essai sur le même PC : le bail porte DÉJÀ « DESKTOP-… » avant l'envoi.
    Seule une NOUVELLE demande DHCP prouve un redémarrage sur le disque."""
    bail(1000, "DESKTOP-L55OLLA")
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})
    assert main._tour_winpe() == []
    assert _machine().status == "deploying"


# ── Filet délai ──────────────────────────────────────────────────────────────

def test_sans_rappel_au_dela_du_delai_echec_avec_consignes(client, bail):
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})

    _vieillir(9)
    assert main._tour_winpe() == []
    _vieillir(2)
    assert len(main._tour_winpe()) == 1
    assert _machine().status == "failed"
    j = _journal()
    assert "n'a pas rappelé OSIRIS 10 min" in j
    assert "OSIRIS injoignable" in j      # la consigne couvre aussi le pilote réseau manquant


def test_rappel_de_winpe_desarme_la_surveillance(client, bail):
    bail(1000, "*")
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})
    r = client.get("/winpe-auto", params={"serial": "1H861365MD"})
    assert r.status_code == 200
    assert _machine().winpe_envoye_le is None
    assert "WinPE a démarré et a rappelé OSIRIS" in _journal()

    bail(9000, "FRCLCL04")             # le Windows installé, plus tard : rien à dire
    assert main._tour_winpe() == []
    assert _machine().status == "deploying"


def test_winpe_tardif_leve_l_echec(client, bail):
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})
    _vieillir(11)
    main._tour_winpe()
    assert _machine().status == "failed"

    bail(1000, "MININT-8K2J4LA")
    client.get("/winpe-auto", params={"serial": "1H861365MD"})
    assert _machine().status == "deploying"
    assert "l'échec signalé plus haut est levé" in _journal()


# ── Filet iPXE : rapport du code d'erreur ───────────────────────────────────

def test_rapport_ipxe_passe_en_echec_avec_lien_d_erreur(client, bail):
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})
    r = client.get("/boot", params={"mac": MAC_FIL, "echec": "0x7f048283"})
    assert r.status_code == 200 and r.text.startswith("#!ipxe")
    assert _machine().status == "failed"
    assert "https://ipxe.org/err/7f048283" in _journal()


def test_rapport_ipxe_code_illisible_ne_s_injecte_pas(client, bail):
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})
    client.get("/boot", params={"mac": MAC_FIL, "echec": "<script>"})
    j = _journal()
    assert "illisible" in j and "<script>" not in j


def test_rapport_ipxe_apres_detection_dhcp_complete_sans_doublon(client, bail):
    bail(1000, "*")
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})
    bail(8200, "DESKTOP-JOEK76U")
    main._tour_winpe()
    client.get("/boot", params={"mac": MAC_FIL, "echec": "0x7f048283"})
    with Session(engine) as s:
        echecs = s.exec(select(DeploymentEvent).where(
            DeploymentEvent.mac == MAC, DeploymentEvent.status == "failed")).all()
    assert len(echecs) == 1
    assert "iPXE confirme" in _journal()


# ── Ce que voit l'opérateur ──────────────────────────────────────────────────

def test_liste_montre_cause_et_consigne_d_une_fiche_en_echec(client, bail, admin_headers):
    _pc()
    client.get("/boot", params={"mac": MAC_FIL})
    _vieillir(11)
    main._tour_winpe()
    fiches = client.get("/machines", headers=admin_headers).json()
    fiche = next(f for f in fiches if f["mac"] == MAC)
    assert "n'a pas rappelé OSIRIS" in fiche["derniere_ligne"]
    assert "À faire" in fiche["derniere_ligne"]


def test_webhook_recoit_une_machine_lisible(client, bail):
    """La machine passée au webhook doit rester lisible après le commit."""
    _pc(org_webhook="https://exemple.invalid/hook")
    client.get("/boot", params={"mac": MAC_FIL})
    _vieillir(11)
    (mac, lignes, webhook, machine), = main._tour_winpe()
    assert webhook == "https://exemple.invalid/hook"
    assert machine.hostname == "FRCLCL04" and machine.status == "failed"


# ── Mode diagnostic : lire wimboot au lieu de le voir défiler ─────────────────

def test_mode_diagnostic_seulement_pour_le_pc_liste(client, bail, tmp_path, monkeypatch):
    liste = tmp_path / "winpe-diagnostic"
    liste.write_text("# tour Plenitude\nAA:BB:CC:00:11:22\n")
    monkeypatch.setattr(main, "WINPE_DIAGNOSTIC", str(liste))
    _pc()

    r = client.get("/boot", params={"mac": MAC_FIL})
    assert "wimboot pause" not in r.text           # pas listé : démarrage normal

    liste.write_text(f"{MAC_FIL}   # tour Plenitude\n")   # relu sans redémarrage
    r = client.get("/boot", params={"mac": MAC_FIL})
    assert "/static/wimboot pause\n" in r.text
    assert "MODE DIAGNOSTIC" in r.text
    assert "boot || goto osiris_winpe_echec" in r.text   # le filet reste en place
    assert "MODE DIAGNOSTIC" in _journal()


def test_mode_diagnostic_fichier_absent_ou_illisible(client, bail, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "WINPE_DIAGNOSTIC", str(tmp_path / "absent"))
    _pc()
    assert "wimboot pause" not in client.get("/boot", params={"mac": MAC_FIL}).text
    f = tmp_path / "casse"
    f.write_text("pas-une-mac\n")
    monkeypatch.setattr(main, "WINPE_DIAGNOSTIC", str(f))
    assert "wimboot pause" not in client.get("/boot", params={"mac": MAC_FIL}).text


def test_mode_diagnostic_bootmgr_classique(client, bail, tmp_path, monkeypatch):
    """`classique` après la MAC : bootx64.efi fourni, wimboot n'utilise plus _EX."""
    liste = tmp_path / "winpe-diagnostic"
    monkeypatch.setattr(main, "WINPE_DIAGNOSTIC", str(liste))
    _pc()

    liste.write_text(f"{MAC_FIL}   # sans option\n")
    assert "bootx64.efi" not in client.get("/boot", params={"mac": MAC_FIL}).text

    liste.write_text(f"{MAC_FIL} classique  # tour Plenitude\n")
    r = client.get("/boot", params={"mac": MAC_FIL}).text
    assert "/static/wimboot pause\n" in r
    lignes = r.splitlines()
    i_bootx64 = next(i for i, l in enumerate(lignes) if "bootx64.efi" in l)
    assert lignes[i_bootx64].endswith("/static/winpe/bootmgfw.efi bootx64.efi")
    assert i_bootx64 < lignes.index("boot || goto osiris_winpe_echec")
    assert "CLASSIQUE" in _journal()


def test_mode_diagnostic_sanboot_sans_wimboot(client, bail, tmp_path, monkeypatch):
    """`sanboot` : l'ISO WinPE démarrée par iPXE, sans wimboot, filet d'échec gardé."""
    liste = tmp_path / "winpe-diagnostic"
    liste.write_text(f"{MAC_FIL} sanboot\n")
    monkeypatch.setattr(main, "WINPE_DIAGNOSTIC", str(liste))
    _pc()
    r = client.get("/boot", params={"mac": MAC_FIL}).text
    assert "static/wimboot" not in r and "initrd" not in r
    assert f"sanboot --no-describe {main.OSIRIS_BASE_URL}/static/{main.WINPE_ISO_NAME} || goto osiris_winpe_echec" in r
    assert ":osiris_winpe_echec" in r
    assert "sanboot iPXE" in _journal()
    assert "WinPE envoyé" in _journal()   # surveillance armée
