# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""La licence WithSecure d'une machine est celle de SON organisation.

Le 22/10, deux postes d'un client se sont enregistrés sur l'abonnement WithSecure
d'un autre : la clé était écrite dans l'application, le profil du client avait
été copié depuis celui de l'autre, et rien ne faisait le lien avec l'organisation
de la machine. La clé vit maintenant sur l'organisation ; sans clé, la machine
est refusée, jamais rabattue sur une autre licence.

Clés d'exemple uniquement.
"""
import pytest
from sqlmodel import Session

import licences
from crypto import decrypt, encrypt
from models import Application, Machine, Organization, Profile, engine

CLE_A = "AAAA-BBBB-CCCC-DDDD-0001"
CLE_B = "ZZZZ-YYYY-XXXX-WWWW-0002"
MAC = "aabbccddee42"
ARGS = (f"/qn VOUCHER={licences.MARQUEUR_CLE} LANGUAGE=fr "
        f"PROFILE_ID={licences.MARQUEUR_PROFIL} UNIQUE_SIGNUP_ID=smbios")


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _monde(args=ARGS, cle_org=CLE_A, profil_org="111"):
    """Une organisation, l'appli WithSecure, un profil Windows qui l'installe."""
    with Session(engine) as s:
        org = Organization(name="Client A", slug="client-a",
                           withsecure_voucher=encrypt(cle_org) if cle_org else "",
                           withsecure_profile_id=profil_org)
        sans = Organization(name="Client sans clé", slug="client-sans-cle")
        ws = Application(name="WithSecure", install_type="msi",
                         installer_file="ElementsAgentOfflineInstaller.msi", install_args=args)
        s.add_all([org, sans, ws])
        s.commit()
        prof = Profile(name="Windows A", os="windows", app_ids=str(ws.id))
        s.add(prof)
        s.commit()
        return org.id, sans.id, prof.id


def _machine(org_id, prof_id, **kw):
    champs = dict(mac=MAC, hostname="PC-42", client="c", os="windows", status="pending",
                  password_hash="$6$x", organization_id=org_id, profile_id=prof_id)
    champs.update(kw)
    with Session(engine) as s:
        s.add(Machine(**champs))
        s.commit()


# ── Le module ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("brut,attendu", [
    ("aaaa-bbbb-cccc-dddd-0001", CLE_A),       # la casse est normalisée
    ("  AAAA-BBBB-CCCC-DDDD-0001 ", CLE_A),
    ("", ""), (None, ""),                      # vide = effacement
])
def test_cle_normalisee(brut, attendu):
    assert licences.normaliser_cle(brut) == attendu


@pytest.mark.parametrize("brut", [
    "AAAA-BBBB-CCCC-DDDD",                     # un groupe manquant
    "AAAA-BBBB-CCCC-DDDD-0001' ; rm",          # recopiée dans une chaîne PowerShell
])
def test_cle_malformee_refusee(brut):
    with pytest.raises(ValueError):
        licences.normaliser_cle(brut)


def test_une_cle_ecrite_dans_l_application_est_refusee_meme_si_l_org_a_la_sienne():
    """C'est exactement l'incident : l'appli porte la clé d'un autre client."""
    app = Application(name="WithSecure (autre)", install_args=f"/qn VOUCHER={CLE_B} LANGUAGE=fr")
    assert licences.refus(app, CLE_A, "111", "Client A")


def test_une_application_sans_licence_n_est_jamais_concernee():
    app = Application(name="Office", install_args="/configure conf.xml")
    assert licences.refus(app, "", "", "") is None


def test_les_marqueurs_sont_remplaces_par_la_licence_de_l_organisation():
    app = Application(name="WithSecure", install_args=ARGS)
    args = licences.args_installation(app, CLE_A, "111")
    assert f"VOUCHER={CLE_A}" in args and "PROFILE_ID=111" in args
    assert "%" not in args


# ── Le premier démarrage ───────────────────────────────────────────────────────

def test_firstboot_installe_avec_la_cle_de_l_organisation(client, clean_db):
    org, _, prof = _monde()
    _machine(org, prof)
    script = client.get(f"/firstboot-windows/{MAC}").text
    assert f"VOUCHER={CLE_A}" in script
    assert "PROFILE_ID=111" in script
    assert licences.MARQUEUR_CLE not in script


def test_firstboot_sans_cle_n_installe_pas_et_le_dit(client, clean_db):
    """Dernier filet, si une machine a échappé aux refus en amont (fiche
    antérieure, base retouchée) : pas d'installation, une erreur au journal, et
    un contrôle de présence en échec, au lieu d'une licence étrangère."""
    _, sans, prof = _monde()
    _machine(sans, prof)
    script = client.get(f"/firstboot-windows/{MAC}").text
    assert "ElementsAgentOfflineInstaller.msi" not in script
    assert "VOUCHER=" not in script
    assert "ERREUR : WithSecure non installe" in script
    assert 'Add-SmokeTest "App : WithSecure" $false' in script


def test_firstboot_n_installe_pas_une_cle_ecrite_dans_l_application(client, clean_db):
    org, _, prof = _monde(args=f"/qn VOUCHER={CLE_B} LANGUAGE=fr")
    _machine(org, prof)
    script = client.get(f"/firstboot-windows/{MAC}").text
    assert CLE_B not in script


# ── Les refus en amont ─────────────────────────────────────────────────────────

def _corps_machine(org_id, prof_id):
    return {"mac": MAC, "hostname": "PC-42", "client": "c", "os": "windows",
            "organization_id": org_id, "profile_id": prof_id}


def test_creation_refusee_pour_une_organisation_sans_cle(client, admin_token, clean_db):
    _, sans, prof = _monde()
    r = client.post("/machines", json=_corps_machine(sans, prof), headers=_h(admin_token))
    assert r.status_code == 409
    assert "Client sans clé" in r.json()["detail"]


def test_creation_acceptee_avec_la_cle_de_l_organisation(client, admin_token, clean_db):
    org, _, prof = _monde()
    r = client.post("/machines", json=_corps_machine(org, prof), headers=_h(admin_token))
    assert r.status_code == 201, r.text


def test_changer_d_organisation_vers_une_sans_cle_est_refuse(client, admin_token, clean_db):
    org, sans, prof = _monde()
    _machine(org, prof)
    r = client.patch(f"/machines/{MAC}", json={"organization_id": sans}, headers=_h(admin_token))
    assert r.status_code == 409


def test_modifier_l_ou_d_une_machine_existante_reste_possible(client, admin_token, clean_db):
    """Un champ sans rapport avec la licence ne doit pas bloquer une fiche."""
    _, sans, prof = _monde()
    _machine(sans, prof)
    r = client.patch(f"/machines/{MAC}", json={"ou": "OU=Postes"}, headers=_h(admin_token))
    assert r.status_code == 200, r.text


def test_redeploiement_refuse_sans_cle(client, admin_token, clean_db):
    _, sans, prof = _monde()
    _machine(sans, prof, status="deployed")
    r = client.post(f"/machines/{MAC}/redeploy-now", headers=_h(admin_token))
    assert r.status_code == 409


def test_une_machine_linux_n_est_pas_concernee(client, admin_token, clean_db):
    _, sans, prof = _monde()
    corps = {**_corps_machine(sans, prof), "os": "ubuntu"}
    r = client.post("/machines", json=corps, headers=_h(admin_token))
    assert r.status_code == 201, r.text


# ── La fiche organisation ──────────────────────────────────────────────────────

def test_la_cle_est_chiffree_et_jamais_renvoyee_en_clair(client, admin_token, clean_db):
    _, sans, _ = _monde()
    r = client.patch(f"/organizations/{sans}",
                     json={"withsecure_voucher": CLE_B.lower(), "withsecure_profile_id": "222"},
                     headers=_h(admin_token))
    assert r.status_code == 200, r.text
    assert CLE_B not in r.text
    assert r.json()["has_withsecure_voucher"] is True
    assert r.json()["withsecure_voucher_fin"] == "0002"
    with Session(engine) as s:
        o = s.get(Organization, sans)
        assert o.withsecure_voucher != CLE_B and decrypt(o.withsecure_voucher) == CLE_B


def test_cle_malformee_refusee_par_l_api(client, admin_token, clean_db):
    _, sans, _ = _monde()
    r = client.patch(f"/organizations/{sans}", json={"withsecure_voucher": "n'importe quoi"},
                     headers=_h(admin_token))
    assert r.status_code == 400


def test_chaine_vide_efface_la_cle(client, admin_token, clean_db):
    org, _, _ = _monde()
    r = client.patch(f"/organizations/{org}", json={"withsecure_voucher": ""}, headers=_h(admin_token))
    assert r.json()["has_withsecure_voucher"] is False


# ── Politique WithSecure choisie par le profil ─────────────────────────────────
# Un client peut avoir plusieurs politiques (Bureau, Direction) sous la même clé.

def _profil_ws(prof_id, valeur):
    with Session(engine) as s:
        p = s.get(Profile, prof_id)
        p.withsecure_profile_id = valeur
        s.add(p)
        s.commit()


def test_le_profil_choisit_sa_politique_et_garde_la_cle_de_l_organisation(client, clean_db):
    org, _, prof = _monde()
    _profil_ws(prof, "999")
    _machine(org, prof)
    script = client.get(f"/firstboot-windows/{MAC}").text
    assert "PROFILE_ID=999" in script
    assert f"VOUCHER={CLE_A}" in script


def test_une_politique_sur_le_profil_ne_remplace_pas_une_cle_absente(client, admin_token, clean_db):
    """La politique ne dit pas QUI paie : sans clé d'organisation, toujours refusé."""
    _, sans, prof = _monde()
    _profil_ws(prof, "999")
    r = client.post("/machines", json=_corps_machine(sans, prof), headers=_h(admin_token))
    assert r.status_code == 409


def test_politique_du_profil_enregistree_et_validee(client, admin_token, clean_db):
    _, _, prof = _monde()
    r = client.patch(f"/profiles/{prof}", json={"withsecure_profile_id": " 999 "}, headers=_h(admin_token))
    assert r.status_code == 200 and r.json()["withsecure_profile_id"] == "999"
    r = client.patch(f"/profiles/{prof}", json={"withsecure_profile_id": "abc"}, headers=_h(admin_token))
    assert r.status_code == 400
    r = client.patch(f"/profiles/{prof}", json={"withsecure_profile_id": ""}, headers=_h(admin_token))
    assert r.json()["withsecure_profile_id"] == ""


def test_le_catalogue_signale_l_appli_a_licence_d_organisation(client, admin_token, clean_db):
    _monde()
    apps = client.get("/apps", headers=_h(admin_token)).json()
    assert [a["licence_org"] for a in apps if a["name"] == "WithSecure"] == [True]
