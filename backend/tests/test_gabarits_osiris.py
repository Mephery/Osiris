# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Distinguer les gabarits OSIRIS des autres modèles de l'hyperviseur.

Le formulaire proposait tous les modèles. Un clone NU d'un modèle sans agent
démarre, ne rappelle jamais, et la fiche reste « pending » sans une ligne. Le
nom ne suffit pas à trier : « osiris-…-old » porte l'ancien agent.

Le scellement annonce donc le gabarit (UUID SMBIOS + empreinte de l'agent), et
la liste des modèles dit, pour chacun, s'il porte l'agent et lequel. L'annonce
est testée en EXÉCUTANT le fragment tel qu'il sort du rendu de production.
"""
import re
import subprocess

import pytest
from sqlmodel import Session, select

import main
from models import GabaritOsiris, Hypervisor, engine

UUID = "422d5733-9e3e-0674-a95b-0dee8c568dd7"
# Le même, lu par un BIOS antérieur à SMBIOS 2.6 : trois premiers champs inversés
UUID_INVERSE = "33572d42-3e9e-7406-a95b-0dee8c568dd7"


def _enregistrer(client, **kw):
    corps = {"uuid": UUID, "empreinte": main._empreinte_agent("linux"), "os": "linux", "nom": "tpl"}
    corps.update(kw)
    return client.post("/bootstrap/sealed", json=corps)


# ── L'enregistrement au scellement ────────────────────────────────────────────

def test_le_scellement_enregistre_le_gabarit(client, clean_db):
    assert _enregistrer(client).status_code == 204
    with Session(engine) as s:
        g = s.exec(select(GabaritOsiris)).one()
    assert g.uuid == UUID and g.os == "linux"


def test_un_rescellement_met_a_jour_au_lieu_de_doubler(client, clean_db):
    _enregistrer(client, empreinte="ancienne")
    _enregistrer(client, uuid=UUID.upper())
    with Session(engine) as s:
        tous = s.exec(select(GabaritOsiris)).all()
    assert len(tous) == 1
    assert tous[0].empreinte == main._empreinte_agent("linux")


@pytest.mark.parametrize("champ", [{"uuid": "pas-un-uuid"}, {"os": "macos"}])
def test_une_annonce_mal_formee_est_refusee(client, clean_db, champ):
    assert _enregistrer(client, **champ).status_code == 400


# ── L'état annoncé dans la liste ──────────────────────────────────────────────

def _etat(uuid_modele: str):
    return main._annoter_gabarits([{"vmid": 1, "uuid": uuid_modele}])[0]["osiris"]


def test_un_modele_inconnu_n_est_pas_un_gabarit_osiris(clean_db):
    assert _etat(UUID) is None


def test_un_gabarit_scelle_avec_l_agent_courant_est_a_jour(client, clean_db):
    _enregistrer(client)
    assert _etat(UUID)["etat"] == "a_jour"


def test_un_gabarit_scelle_avec_un_autre_agent_est_perime(client, clean_db):
    _enregistrer(client, empreinte="0123456789ab")
    assert _etat(UUID)["etat"] == "perime"


def test_l_uuid_inverse_d_un_vieux_BIOS_est_reconnu(client, clean_db):
    """L'UUID lu dans la VM et celui que publie l'hyperviseur peuvent différer
    par l'ordre des octets : le gabarit ne doit pas passer pour inconnu."""
    _enregistrer(client, uuid=UUID_INVERSE)
    assert _etat(UUID)["etat"] == "a_jour"


def test_l_empreinte_ne_depend_pas_de_l_adresse_d_osiris():
    """Calculée sur le source : deux hyperviseurs aux URL de rappel différentes
    gravent le même agent."""
    assert re.fullmatch(r"[0-9a-f]{12}", main._empreinte_agent("linux"))
    assert main._empreinte_agent("linux") != main._empreinte_agent("windows")


# ── Le marquage à la main, pour les gabarits scellés avant ────────────────────

@pytest.fixture
def hyperviseur(monkeypatch):
    with Session(engine) as s:
        h = Hypervisor(name="pve-test", url="https://pve.test:8006",
                       token_id="root@pam!osiris", token_secret="", tls_verify=False)
        s.add(h)
        s.commit()
        s.refresh(h)

    async def modeles(self_or_h, *a):
        return [{"vmid": 9003, "name": "tpl", "uuid": UUID}]
    monkeypatch.setattr(main.ProxmoxProvider, "list_all_templates", staticmethod(lambda h: modeles(h)))
    return h.id


def test_marquer_puis_demarquer_un_modele(client, admin_headers, hyperviseur):
    r = client.post(f"/hypervisors/{hyperviseur}/templates/9003/osiris", headers=admin_headers)
    assert r.status_code == 204, r.text
    liste = client.get(f"/hypervisors/{hyperviseur}/templates", headers=admin_headers).json()
    # Marqué à la main : OSIRIS sait que c'est un gabarit, pas avec quel agent
    assert liste[0]["osiris"]["etat"] == "inconnu"

    client.delete(f"/hypervisors/{hyperviseur}/templates/9003/osiris", headers=admin_headers)
    assert client.get(f"/hypervisors/{hyperviseur}/templates", headers=admin_headers).json()[0]["osiris"] is None


def test_marquer_ne_remplace_pas_un_vrai_scellement(client, admin_headers, hyperviseur):
    """Un clic sur « marquer » ne doit pas effacer l'empreinte d'un gabarit scellé."""
    _enregistrer(client)
    client.post(f"/hypervisors/{hyperviseur}/templates/9003/osiris", headers=admin_headers)
    assert client.get(f"/hypervisors/{hyperviseur}/templates", headers=admin_headers).json()[0]["osiris"]["etat"] == "a_jour"


def test_un_technicien_ne_marque_rien(client, technician_headers, hyperviseur):
    r = client.post(f"/hypervisors/{hyperviseur}/templates/9003/osiris", headers=technician_headers)
    assert r.status_code == 403


# ── L'annonce dans le script de scellement, exécutée ──────────────────────────

def _annonce(script: str) -> str:
    m = re.search(r"^    _uuid=\$\(.*?^    fi\n", script, re.S | re.M)
    assert m, "l'annonce du gabarit n'est pas dans le script rendu"
    return m.group(0)


def test_le_script_linux_annonce_uuid_empreinte_et_os(tmp_path):
    script = main.get_linux_bootstrap().body.decode()
    (tmp_path / "uuid").write_text(UUID.upper() + "\n")
    faux = ('curl() { for a in "$@"; do echo "ARG $a" >&2; done; }\n'
            'hostname() { echo tpl-ubuntu; }\n'
            'OSIRIS_URL=http://osiris.test\n')
    r = subprocess.run(["bash", "-c", faux + _annonce(script)], capture_output=True, text=True,
                       timeout=30, env={"PATH": "/usr/bin:/bin", "OSIRIS_PRODUCT_UUID": str(tmp_path / "uuid")})
    assert "ARG http://osiris.test/bootstrap/sealed" in r.stderr
    corps = next(l for l in r.stderr.splitlines() if l.startswith("ARG {"))
    assert f'"uuid":"{UUID}"' in corps, "l'UUID doit partir en minuscules"
    assert f'"empreinte":"{main._empreinte_agent("linux")}"' in corps
    assert '"os":"linux"' in corps and '"nom":"tpl-ubuntu"' in corps
    assert "Gabarit enregistre" in r.stdout


def test_le_script_linux_dit_quoi_faire_si_osiris_ne_repond_pas(tmp_path):
    script = main.get_linux_bootstrap().body.decode()
    (tmp_path / "uuid").write_text(UUID)
    r = subprocess.run(["bash", "-c", "curl() { return 7; }\nOSIRIS_URL=http://x\n" + _annonce(script)],
                       capture_output=True, text=True, timeout=30,
                       env={"PATH": "/usr/bin:/bin", "OSIRIS_PRODUCT_UUID": str(tmp_path / "uuid")})
    assert "marquer a la main" in r.stdout


def test_le_script_windows_annonce_aussi_son_gabarit():
    script = main.get_windows_bootstrap().body.decode()
    assert "/bootstrap/sealed" in script
    assert f'empreinte = "{main._empreinte_agent("windows")}"' in script
    # Avant sysprep : après, la VM s'éteint et n'annoncerait plus rien
    assert script.index("/bootstrap/sealed") < script.index("sysprep.exe")


# ── La famille de système, lue sur l'hyperviseur ──────────────────────────────

@pytest.mark.parametrize("guest_id,famille", [
    ("windows2019srv_64Guest", "windows"), ("debian11_64Guest", "linux"),
    ("ubuntu64Guest", "linux"), ("", "")])
def test_la_famille_vient_du_type_d_invite_vsphere(guest_id, famille):
    """Un gabarit marqué à la main n'a pas de système connu d'OSIRIS : sans la
    famille déclarée à l'hyperviseur, un Windows se proposait sous Debian."""
    import vsphere
    assert vsphere._famille_invite(guest_id) == famille


def test_la_famille_vient_de_l_ostype_proxmox(monkeypatch):
    import asyncio

    async def ressources(h, chemin):
        return [{"vmid": 9001, "template": 1, "node": "n"}, {"vmid": 9002, "template": 1, "node": "n"},
                {"vmid": 9003, "template": 1, "node": "n"}]

    async def config(h, node, vmid):
        return {9001: {"ostype": "win11"}, 9002: {"ostype": "l26"}, 9003: {}}[vmid]
    monkeypatch.setattr(main, "_proxmox_get", ressources)
    monkeypatch.setattr(main, "_config_vm", config)
    modeles = asyncio.run(main.ProxmoxProvider.list_all_templates(None))
    assert [m["famille"] for m in modeles] == ["windows", "linux", ""]
