"""Poste Ubuntu physique : démarrage réseau en HTTP et bureau ajouté à l'ISO Server.

Trois choses que ce fichier verrouille :
- l'iPXE sert l'ISO par `url=` (plus de NFS, jamais monté en production) ;
- sans image prête, le PC le dit et s'arrête, au lieu d'un 404 sans rapport ;
- un profil POSTE ajoute le bureau et NetworkManager, un profil SERVEUR ne
  change pas d'un octet.
"""
import asyncio
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml

import main
import worker
from models import OsImage, Profile


def _user_data(machine_type: str, extra: str = "") -> dict:
    profile = Profile(name="t", os="ubuntu", machine_type=machine_type, extra_packages=extra)
    contenu = main.jinja_env.get_template("user-data.j2").render(
        machine=SimpleNamespace(hostname="HCKLTEST01", password_hash="$6$x$y"),
        profile=profile, ssh_pubkey="", packages=[p for p in extra.split(",") if p],
        mac="52:54:00:00:00:01", osiris_url="http://osiris",
        status_url="http://osiris/machines/52:54:00:00:00:01/status",
    )
    return yaml.safe_load(contenu)["autoinstall"]


def test_un_poste_recoit_le_bureau():
    assert "ubuntu-desktop-minimal" in _user_data("workstation")["packages"]


def test_un_poste_garde_les_paquets_du_profil():
    paquets = _user_data("workstation", "htop,curl")["packages"]
    assert paquets[0] == "ubuntu-desktop-minimal"
    assert {"htop", "curl"} <= set(paquets)


def test_un_poste_passe_sous_networkmanager():
    commandes = "\n".join(_user_data("workstation")["late-commands"])
    assert "renderer: NetworkManager" in commandes
    assert "rm -f /target/etc/netplan/*.yaml" in commandes
    assert "disable systemd-networkd.service systemd-networkd-wait-online.service" in commandes


def test_le_reseau_bascule_apres_le_firstboot_et_avant_le_statut_final():
    """Le statut « deployed » reste la DERNIÈRE commande : s'il partait avant la
    bascule réseau, une erreur de bascule passerait pour un succès."""
    commandes = _user_data("workstation")["late-commands"]
    assert "status=deployed" in commandes[-1]


def test_un_serveur_ne_change_pas():
    ud = _user_data("server")
    assert "packages" not in ud
    assert "NetworkManager" not in "\n".join(ud["late-commands"])


def _image(version="26.04.1"):
    return OsImage(name=f"Ubuntu {version}", version=version, os="ubuntu", iso_url="x")


def test_l_ipxe_sert_l_iso_en_http_sans_nfs():
    lignes = main._ubuntu_ipxe_lignes(_image(), "52:54:00:00:00:01")
    base = f"{main.OSIRIS_BASE_URL}/static/ubuntu-26.04.1"
    assert f"url={base}/ubuntu.iso" in lignes
    assert f"kernel {base}/vmlinuz" in lignes
    assert f"initrd {base}/initrd" in lignes
    assert "nfs" not in lignes.lower()


def test_cloud_init_de_l_installateur_ne_relit_pas_l_iso():
    """Sans cloud-config-url=/dev/null, cloud-init prend url= pour SA
    configuration et retélécharge l'ISO entière."""
    assert "cloud-config-url=/dev/null" in main._ubuntu_ipxe_lignes(_image(), "52:54:00:00:00:01")


def test_l_autoinstall_est_cherche_chez_osiris_pour_cette_mac():
    lignes = main._ubuntu_ipxe_lignes(_image(), "52:54:00:00:00:01")
    assert f"ds=nocloud-net;s={main.OSIRIS_BASE_URL}/cloud-init/52:54:00:00:00:01/" in lignes
    assert " autoinstall " in lignes


def test_sans_image_le_pc_le_dit_et_ne_demarre_rien():
    lignes = main._ubuntu_ipxe_lignes(None, "52:54:00:00:00:01")
    assert "aucune image Ubuntu" in lignes
    assert "kernel" not in lignes and "exit 1" in lignes


# ── Préparation de l'image par le worker ─────────────────────────────────────

xorriso = pytest.mark.skipif(not shutil.which("xorriso"), reason="xorriso absent")


def _fausse_iso(dossier, *, avec_noyau=True) -> str:
    racine = os.path.join(dossier, "racine")
    os.makedirs(os.path.join(racine, "casper"))
    if avec_noyau:
        for nom in ("vmlinuz", "initrd"):
            with open(os.path.join(racine, "casper", nom), "wb") as f:
                f.write(nom.encode() * 10)
    iso = os.path.join(dossier, "source.iso")
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-o", iso, racine], check=True,
                   capture_output=True)
    return iso


@xorriso
def test_l_image_garde_l_iso_et_son_noyau(tmp_path):
    iso = _fausse_iso(str(tmp_path))
    static = str(tmp_path / "static" / "ubuntu-26.04")
    asyncio.run(worker._process_ubuntu(iso, static, lambda **k: None, deplacer=False))
    assert sorted(os.listdir(static)) == ["initrd", "ubuntu.iso", "vmlinuz"]
    assert os.path.exists(iso), "un fichier local (file://) n'est jamais déplacé"


@xorriso
def test_une_iso_telechargee_est_deplacee_pas_copiee(tmp_path):
    iso = _fausse_iso(str(tmp_path))
    static = str(tmp_path / "static" / "ubuntu-26.04")
    asyncio.run(worker._process_ubuntu(iso, static, lambda **k: None, deplacer=True))
    assert not os.path.exists(iso)
    assert os.path.exists(os.path.join(static, "ubuntu.iso"))


@xorriso
def test_une_iso_sans_noyau_fait_echouer_l_image(tmp_path):
    """Avant : l'échec d'extraction était ignoré et l'image passait « prête »."""
    iso = _fausse_iso(str(tmp_path), avec_noyau=False)
    static = str(tmp_path / "static" / "ubuntu-26.04")
    with pytest.raises(RuntimeError):
        asyncio.run(worker._process_ubuntu(iso, static, lambda **k: None, deplacer=False))
    assert not os.path.exists(os.path.join(static, "ubuntu.iso"))



def test_vendor_data_repond_vide_au_lieu_d_un_404():
    """cloud-init réessaie sur 404 : plusieurs minutes perdues par déploiement."""
    from fastapi.testclient import TestClient
    r = TestClient(main.app).get("/cloud-init/52:54:00:00:00:01/vendor-data")
    assert r.status_code == 200 and r.text == ""


# ── Rapport de premier démarrage d'un poste (faux échecs vus au banc, 23/11) ─

def _firstboot_poste(**profil) -> str:
    ctx = {"os": "ubuntu", "default_user": "osiris", "join_domain": False,
           "machine_type": "workstation", "app_ids": "", "tv_suffix": "",
           "vm_data_disk_gb": 0, "set_root_password": True, **profil}
    return main._firstboot_linux_content(
        hostname="HCKLTEST01", mac="525400000001", ou="", profile_ctx=ctx,
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test")


def test_un_poste_sans_teamviewer_n_est_pas_controle_sur_teamviewer():
    assert '_add_test "TeamViewer"' not in _firstboot_poste()


def test_un_poste_avec_teamviewer_est_controle():
    assert '_add_test "TeamViewer"' in _firstboot_poste(tv_suffix="-x")


def test_une_jonction_impossible_est_dite_au_lieu_d_etre_sautee():
    """Profil neuf : join_domain=True par défaut mais aucun compte de jonction.
    L'étape était sautée en silence et le test disait seulement « absent »."""
    script = _firstboot_poste(join_domain=True, domain="entreprise.local")
    assert "Jonction AD demandee mais NON TENTEE" in script
    assert "domaine ou compte de jonction non renseigne" in script
    assert "realm join" not in script


def test_une_jonction_complete_reste_controlee_par_realm():
    script = _firstboot_poste(join_domain=True, domain="humans.local",
                              domain_join_user="j", domain_join_password="p")
    assert 'grep -q "humans.local"' in script and "NON TENTEE" not in script
