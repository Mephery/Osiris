# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le script de premier démarrage voyage avec la VM, il n'est plus téléchargé.

Constaté le 2026-08-19 en déployant sur un VLAN sans route de retour vers OSIRIS :
le tout premier `runcmd` du cloud-init téléchargeait le script depuis OSIRIS, donc
il ne s'exécutait pas du tout. Cloud-init posait bien le hostname, le compte et sa
clé SSH — ce sont des directives natives — mais tout ce que porte le script (volume
de données, agent Zabbix, jonction au domaine, smoke tests) était perdu avec le
téléchargement, sans qu'aucune trace ne l'explique.

Embarqué dans le user-data, il s'exécute quoi qu'il arrive. Seul le compte rendu à
OSIRIS dépend encore du réseau, et c'est irréductible.
"""
import base64

import pytest
import yaml

import main
from models import Hypervisor


class _Body:
    """Le corps de création de VM, réduit à ce que le rendu consulte."""
    hostname = "srv-embarque"
    client = "Test"
    os = "ubuntu"
    ou = ""
    profile_id = None
    organization_id = None
    node = "node1"
    storage = "ds"
    bridge = "vmbr0"
    vcpus = 2
    ram_mb = 2048
    disk_gb = 20
    data_disk_gb = 0
    ip_cidr = ""
    gateway = ""
    dns_servers = ""
    boot_mode = "cloudinit"
    template_id = 1
    win_ostype = "win11"
    iso = ""


@pytest.fixture
def user_data(client):
    """Le cloud-init tel qu'OSIRIS l'injecte réellement dans une VM."""
    h = Hypervisor(id=1, name="hv-test", url="https://hv.test", type="vsphere",
                   token_id="osiris@vsphere.local", token_secret="",
                   zabbix_server="10.0.0.50")
    return main._render_cloud_init_user_data(h, _Body(), "aabbccddeeff")


def test_le_cloud_init_reste_un_yaml_valide(user_data):
    """Trois cents lignes de bash dans du YAML : la moindre dérive d'indentation
    casserait le cloud-init entier, et une VM ne dirait jamais pourquoi."""
    doc = yaml.safe_load(user_data)
    assert isinstance(doc, dict)


def test_le_script_est_ecrit_par_cloud_init_lui_meme(user_data):
    doc = yaml.safe_load(user_data)
    fichier = next(f for f in doc["write_files"]
                   if f["path"] == "/usr/local/bin/osiris-firstboot.sh")
    assert fichier["permissions"] == "0755", "le script doit être exécutable"
    assert fichier["encoding"] == "b64"


def test_le_script_embarque_est_du_bash_complet_et_personnalise(user_data):
    """Ce n'est pas un gabarit générique : il porte le nom et la MAC de CETTE VM."""
    doc = yaml.safe_load(user_data)
    fichier = next(f for f in doc["write_files"]
                   if f["path"] == "/usr/local/bin/osiris-firstboot.sh")
    script = base64.b64decode(fichier["content"]).decode()

    assert script.startswith("#!"), "un script sans shebang ne s'exécute pas"
    assert "srv-embarque" in script
    assert "aabbccddeeff" in script


def test_le_demarrage_ne_telecharge_plus_rien(user_data):
    """Le cœur de la régression : plus aucun `curl` ne doit conditionner
    l'exécution du script."""
    doc = yaml.safe_load(user_data)
    commandes = doc["runcmd"]

    assert any("/usr/local/bin/osiris-firstboot.sh" == c.strip() for c in commandes), \
        "le script embarqué doit être lancé"
    assert not any("firstboot-ubuntu" in c or "firstboot-linux" in c for c in commandes), \
        "plus rien ne doit aller chercher le script sur OSIRIS"


def test_la_supervision_suit_lhyperviseur_meme_embarquee(user_data):
    """Le collecteur dépend du site où la VM tourne. Il était résolu en base au
    téléchargement ; embarqué, il doit l'être à la création — sans quoi une VM
    d'un second site partirait sans supervision."""
    doc = yaml.safe_load(user_data)
    fichier = next(f for f in doc["write_files"]
                   if f["path"] == "/usr/local/bin/osiris-firstboot.sh")
    script = base64.b64decode(fichier["content"]).decode()

    assert "10.0.0.50" in script, "le collecteur de l'hyperviseur doit être gravé"


def test_le_rendu_ne_depend_pas_de_la_fiche_machine():
    """Sur vSphere, la MAC définitive n'existe qu'une fois le clone fait : la fiche
    porte encore la MAC provisoire quand le cloud-init est rendu. Un rendu qui
    chercherait la machine en base échouerait donc précisément là où il sert."""
    contenu = main._firstboot_linux_content(
        hostname="srv-hors-base", mac="001122334455", ou="",
        profile_ctx={"os": "ubuntu", "default_user": "humains", "join_domain": False,
                     "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0},
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test",
    )
    assert "srv-hors-base" in contenu
    assert "001122334455" in contenu
