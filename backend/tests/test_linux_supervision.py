# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""
Premier démarrage Linux : nom d'hôte, supervision Zabbix, crochet de
post-installation applicatif, et mécanisme d'amorçage générique.
"""
import pytest
from sqlmodel import Session as _BaseSession

from models import engine, Machine, Profile, Organization, Application


def Session(bind):
    return _BaseSession(bind, expire_on_commit=False)


@pytest.fixture
def linux_setup(clean_db):
    """Une organisation avec collecteur Zabbix, un profil Ubuntu, une machine supervisée."""
    with Session(engine) as session:
        org = Organization(name="Organisation test", slug="org-test", zabbix_server="192.0.2.130")
        profile = Profile(name="Ubuntu test", os="ubuntu", join_domain=False)
        session.add(org)
        session.add(profile)
        session.commit()
        session.refresh(org)
        session.refresh(profile)
        machine = Machine(mac="0a0b0c0d0e0f", hostname="SRV-LINUX-01", client="Organisation test",
                          os="ubuntu", profile_id=profile.id, organization_id=org.id)
        session.add(machine)
        session.commit()
        session.refresh(machine)
        return {"org": org, "profile": profile, "machine": machine}


def _firstboot(client, mac="0a0b0c0d0e0f"):
    res = client.get(f"/firstboot-linux/{mac}")
    assert res.status_code == 200
    return res.text


# ── Nom d'hôte ────────────────────────────────────────────────────────────────

def test_firstboot_pose_le_nom_dhote(client, linux_setup):
    """Sans ça, une VM clonée garde le nom du template et s'annonce ainsi au DHCP."""
    script = _firstboot(client)
    assert "hostnamectl set-hostname 'SRV-LINUX-01'" in script
    # \t littéral : c'est sed qui l'interprète sur la machine, pas Jinja ici
    assert r"127.0.1.1\tSRV-LINUX-01" in script


def test_firstboot_verrouille_le_nom_contre_cloud_init(client, linux_setup):
    """cloud-init repose le nom du datasource à chaque boot : il faut le neutraliser."""
    script = _firstboot(client)
    assert "preserve_hostname: true" in script
    assert "/etc/cloud/cloud.cfg.d/99-osiris-hostname.cfg" in script


def test_les_rappels_utilisent_la_mac_de_la_fiche(client, linux_setup):
    """La MAC est gravée à la génération, pas redéduite de la route par défaut."""
    script = _firstboot(client)
    assert '_osiris_mac="0a0b0c0d0e0f"' in script
    assert "ip route get 8.8.8.8" not in script


def test_firstboot_signale_la_fin_du_deploiement(client, linux_setup):
    """Sur le chemin cloud-init, c'est le SEUL signal de fin de déploiement."""
    script = _firstboot(client)
    assert "status?status=deployed" in script


# ── Supervision Zabbix ────────────────────────────────────────────────────────

def test_agent_zabbix_configure_en_mode_actif(client, linux_setup):
    script = _firstboot(client)
    assert "ServerActive=192.0.2.130" in script
    assert "Hostname=SRV-LINUX-01" in script
    # Métadonnée lue par l'auto-enregistrement côté Zabbix
    assert "HostMetadata=osiris linux org-test" in script


def test_smoke_test_verifie_le_flux_vers_le_collecteur(client, linux_setup):
    """Distingue « agent mal configuré » de « règle de pare-feu manquante »."""
    script = _firstboot(client)
    assert "/dev/tcp/192.0.2.130/10051" in script


def test_pas_dagent_si_machine_non_supervisee(client, linux_setup):
    with Session(engine) as session:
        machine = session.get(Machine, linux_setup["machine"].id)
        machine.supervised = False
        session.add(machine)
        session.commit()
    script = _firstboot(client)
    assert "zabbix" not in script.lower()


def test_pas_dagent_si_organisation_sans_collecteur(client, linux_setup):
    """Un agent sans adresse de collecteur serait muet : mieux vaut ne rien installer."""
    with Session(engine) as session:
        org = session.get(Organization, linux_setup["org"].id)
        org.zabbix_server = ""
        session.add(org)
        session.commit()
    script = _firstboot(client)
    assert "zabbix" not in script.lower()


def test_pas_dagent_si_machine_sans_organisation(client, linux_setup):
    with Session(engine) as session:
        machine = session.get(Machine, linux_setup["machine"].id)
        machine.organization_id = None
        session.add(machine)
        session.commit()
    script = _firstboot(client)
    assert "zabbix" not in script.lower()


def test_supervision_activee_par_defaut(client, admin_headers):
    res = client.post("/machines", headers=admin_headers, json={
        "mac": "112233445566", "hostname": "PC-NEUF", "client": "X", "os": "ubuntu",
    })
    assert res.status_code == 201
    assert res.json()["supervised"] is True


def test_supervision_desactivable_par_patch(client, admin_headers, linux_setup):
    res = client.patch("/machines/0a0b0c0d0e0f", headers=admin_headers,
                       json={"supervised": False})
    assert res.status_code == 200
    assert res.json()["supervised"] is False


def test_collecteur_zabbix_editable_par_organisation(client, admin_headers, linux_setup):
    res = client.patch(f"/organizations/{linux_setup['org'].id}", headers=admin_headers,
                       json={"zabbix_server": " 10.0.0.9 "})
    assert res.status_code == 200
    assert res.json()["zabbix_server"] == "10.0.0.9"


# ── Compte local et accès SSH ─────────────────────────────────────────────────

def test_compte_local_cree_sil_manque(client, linux_setup):
    """
    Une VM clonée d'un template n'a pas forcément le compte du profil. Sans lui
    elle est hermétique : ni SSH ni console.
    """
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.default_user = "humans"
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    assert "useradd -m -s /bin/bash 'humans'" in script
    assert "id -u 'humans'" in script       # créé seulement s'il manque
    assert "/etc/sudoers.d/osiris-default-user" in script


def test_cles_ssh_posees_meme_sur_un_poste_de_travail(client, linux_setup):
    """Le profil n'est pas 'server' ici : les clés doivent quand même être posées."""
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.default_user = "humans"
        profile.ssh_authorized_keys = "ssh-ed25519 AAAAC3Nz coline@osiris"
        profile.machine_type = "workstation"
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    assert "ssh-ed25519 AAAAC3Nz coline@osiris" in script
    assert "authorized_keys" in script
    # Une clé sans serveur SSH ne sert à rien
    assert "openssh-server" in script


# ── Crochet de post-installation Linux ────────────────────────────────────────

def test_script_de_post_installation_rendu_apres_le_paquet(client, linux_setup):
    with Session(engine) as session:
        app_obj = Application(name="Nginx test", apt_package="nginx",
                              linux_post_install="rm /etc/nginx/sites-enabled/default")
        session.add(app_obj)
        session.commit()
        session.refresh(app_obj)
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.app_ids = str(app_obj.id)
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    install_pos = script.index("apt-get install -y nginx")
    hook_pos = script.index("rm /etc/nginx/sites-enabled/default")
    assert install_pos < hook_pos


def test_crochet_editable_par_patch(client, admin_headers):
    created = client.post("/apps", headers=admin_headers,
                          json={"name": "Test app", "apt_package": "htop"}).json()
    res = client.patch(f"/apps/{created['id']}", headers=admin_headers,
                       json={"linux_post_install": "echo bonjour"})
    assert res.status_code == 200
    assert res.json()["linux_post_install"] == "echo bonjour"


# ── Amorçage générique ────────────────────────────────────────────────────────

def test_bootstrap_sert_un_script_sans_secret(client):
    """
    Le template ne doit contenir aucun identifiant : c'est la raison même pour
    laquelle cette voie a été retenue plutôt qu'un compte Proxmox dédié.
    """
    res = client.get("/bootstrap/linux")
    assert res.status_code == 200
    script = res.text
    assert "http://localhost:8000" in script
    assert "osiris-firstboot.service" in script
    # Les commentaires parlent de secrets, le code ne doit pas en contenir.
    code = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    for marker in ("password", "token", "secret", "authorization"):
        assert marker not in code.lower()


def test_bootstrap_interroge_osiris_avec_la_mac_locale(client):
    script = client.get("/bootstrap/linux").text
    assert "/sys/class/net/" in script
    assert "/firstboot-linux/$mac" in script


def test_bootstrap_ne_desactive_pas_lunite_en_cas_dechec(client):
    """Une VM démarrée avant que sa fiche existe doit retenter au prochain boot."""
    script = client.get("/bootstrap/linux").text
    bootstrap_body = script[script.index("osiris-bootstrap.sh <<"):]
    assert "systemctl disable" not in bootstrap_body


def test_unite_systemd_sans_delai_de_demarrage(client):
    """Le délai oneshot par défaut (90 s) tuerait le firstboot en plein apt-get."""
    script = client.get("/bootstrap/linux").text
    assert "TimeoutStartSec=infinity" in script


def test_firstboot_linux_inconnu_renvoie_404(client, clean_db):
    assert client.get("/firstboot-linux/ffffffffffff").status_code == 404


# ── Serveur : mot de passe root de secours et disque de données ────────────────

def test_mot_de_passe_root_pose_seulement_si_osiris_confirme(client, linux_setup):
    """
    Dans l'autre ordre, un rappel qui échoue laisserait un root dont plus
    personne n'a le mot de passe — pire que pas de mot de passe du tout.
    """
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.set_root_password = True
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    post_pos = script.index("laps-password")
    chpasswd_pos = script.index('echo "root:$_root_pw" | chpasswd')
    assert post_pos < chpasswd_pos
    # Le mot de passe n'est PAS gravé dans le script : la machine le génère
    assert "_root_pw=$(tr -dc" in script


def test_pas_de_mot_de_passe_root_par_defaut(client, linux_setup):
    script = _firstboot(client)
    assert "chpasswd" not in script


def test_disque_de_donnees_ne_touche_quun_disque_vierge(client, linux_setup):
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.vm_data_disk_gb = 100
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    assert "mkfs.ext4" in script
    # Jamais le disque système, jamais un disque déjà formaté
    assert '[ "$_d" = "$_root_disk" ] && continue' in script
    assert "FSTYPE,PARTTYPE" in script
    # Monté par UUID : l'ordre des disques change d'un démarrage à l'autre
    assert "UUID=%s /data ext4" in script


def test_pas_de_formatage_sans_disque_de_donnees(client, linux_setup):
    script = _firstboot(client)
    assert "mkfs" not in script


# ── URL de rappel par hyperviseur ─────────────────────────────────────────────

def test_url_de_rappel_propre_a_lhyperviseur(client, linux_setup):
    """
    Une VM d'un autre site ne voit pas forcément OSIRIS à la même adresse. Sans
    ça, elle télécharge son script puis n'arrive plus à rappeler personne.
    """
    from models import Hypervisor
    with Session(engine) as session:
        hv = Hypervisor(name="Nova", url="https://198.51.100.10:8006",
                        callback_url="http://198.51.100.250:8000/")
        session.add(hv)
        session.commit()
        session.refresh(hv)
        machine = session.get(Machine, linux_setup["machine"].id)
        machine.hypervisor_id = hv.id
        session.add(machine)
        session.commit()
    script = _firstboot(client)
    # Barre finale retirée, sinon toutes les URL construites auraient un //
    assert 'osiris_url="http://198.51.100.250:8000"' in script


def test_url_globale_si_lhyperviseur_nen_impose_pas(client, linux_setup):
    script = _firstboot(client)
    assert 'osiris_url="http://localhost:8000"' in script


# ── Adressage IP fixe ─────────────────────────────────────────────────────────

def test_metadata_vsphere_avec_adresse_fixe():
    """Un VLAN serveur n'a pas de DHCP : sans adresse, la VM ne rappelle jamais."""
    import vsphere

    class Body:
        hostname = "srv-test"
        ip_cidr = "203.0.113.60/24"
        gateway = "203.0.113.1"
        dns_servers = "203.0.113.10,203.0.113.20"

    meta = vsphere._metadata(Body(), "aabbccddeeff")
    assert "addresses: [203.0.113.60/24]" in meta
    assert "dhcp4: false" in meta
    # `gateway4` est déprécié par netplan : on écrit une route par défaut
    assert "to: default" in meta and "via: 203.0.113.1" in meta
    assert "gateway4" not in meta
    assert "addresses: [203.0.113.10, 203.0.113.20]" in meta


def test_metadata_vsphere_sans_adresse_reste_en_dhcp():
    import vsphere

    class Body:
        hostname = "srv-dhcp"
        ip_cidr = ""
        gateway = ""
        dns_servers = ""

    meta = vsphere._metadata(Body(), "aabbccddeeff")
    assert "local-hostname: srv-dhcp" in meta
    assert "network:" not in meta


def test_adressage_conserve_sur_la_fiche(client, admin_headers, linux_setup):
    res = client.patch("/machines/0a0b0c0d0e0f", headers=admin_headers, json={
        "ip_cidr": "203.0.113.60/24", "gateway": "203.0.113.1",
        "dns_servers": "203.0.113.10",
    })
    assert res.status_code == 200
    machines = client.get("/machines", headers=admin_headers).json()
    fiche = next(m for m in machines if m["mac"] == "0a0b0c0d0e0f")
    assert fiche["ip_cidr"] == "203.0.113.60/24"
    assert fiche["gateway"] == "203.0.113.1"


# ── Signalement des erreurs du premier démarrage ──────────────────────────────

def test_le_piege_derreur_remonte_la_commande_fautive(client, linux_setup):
    """
    Un « failed » nu oblige à se connecter à la machine pour comprendre — ce qui
    est rarement possible, justement quand le déploiement a échoué.
    """
    script = _firstboot(client)
    assert 'trap \'_on_error $LINENO "$BASH_COMMAND"\' ERR' in script
    assert "/log" in script and "--data-urlencode" in script


def test_deployed_nest_annonce_que_si_rien_na_echoue(client, linux_setup):
    """Le statut final ne doit jamais contredire un échec déjà signalé."""
    script = _firstboot(client)
    fin = script[script.index("_osiris_failed"):]
    assert 'if [ "$_osiris_failed" -eq 0 ]; then' in fin
    deployed = script.index("status=deployed")
    garde = script.rindex('if [ "$_osiris_failed" -eq 0 ]; then', 0, deployed)
    assert garde < deployed


def test_desactivation_de_lunite_ne_fait_pas_echouer_le_cloud_init(client, linux_setup):
    """
    Sur le chemin cloud-init l'unité n'existe pas : sans garde, son échec
    repassait la machine en erreur APRÈS l'avoir déclarée déployée.
    """
    script = _firstboot(client)
    assert "systemctl disable osiris-firstboot.service 2>/dev/null || true" in script


def test_le_disque_de_donnees_ignore_le_lecteur_de_disquettes(client, linux_setup):
    """
    VMware expose un /dev/fd0 de 4 Ko que lsblk classe « disk », sans partition
    ni système de fichiers — le profil exact d'un disque vierge, et premier dans
    l'ordre alphabétique. OSIRIS tentait de le formater (constaté le 31/07).
    """
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.vm_data_disk_gb = 100
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    assert '$2=="disk" && $3==0 && $4 > 1073741824' in script, \
        "il faut exclure les périphériques amovibles et ceux de moins de 1 Go"


def test_le_compte_root_est_deverrouille(client, linux_setup):
    """Les images cloud livrent root verrouillé : un mot de passe ne suffit pas."""
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.set_root_password = True
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    assert "passwd -u root" in script
    chpasswd = script.index("chpasswd")
    assert script.index("passwd -u root") > chpasswd


def test_le_volume_de_donnees_est_verifie_par_un_smoke_test(client, linux_setup):
    """Déduire le succès de l'absence d'erreur n'est pas le vérifier."""
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.vm_data_disk_gb = 50
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    assert "mountpoint -q /data" in script
    assert '_add_test "Volume /data"' in script


# ── Diagnostic de l'amorçage Linux ─────────────────────────────────────────
# Le 2026-08-05, une VM a bouclé 30 fois sur « aucune fiche OSIRIS » alors que la
# fiche existait : le frontal renvoyait 308 (route absente du matcher Caddy) et le
# script confondait redirection, absence de fiche et serveur injoignable.

def _bootstrap_rendu():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    return env.get_template("bootstrap-linux.sh.j2").render(osiris_url="http://osiris")


def test_l_amorcage_lit_le_code_http_au_lieu_de_le_masquer():
    """`curl -f` rendait 404, 308 et panne réseau indiscernables."""
    script = _bootstrap_rendu()
    assert "curl -s -o \"$SCRIPT\" -w '%{http_code}'" in script
    assert "curl -sf -o" not in script


def test_chaque_cause_a_son_message():
    script = _bootstrap_rendu()
    for cause in ("serveur injoignable", "pas de fiche pour cette MAC", "REDIRECTION"):
        assert cause in script


def test_le_code_http_apparait_dans_le_journal():
    assert 'details="$details $mac->HTTP $code' in _bootstrap_rendu()


# ── Détection d'une route non proxifiée par le frontal ─────────────────────

def test_les_routes_appelees_par_les_machines_sont_surveillees():
    """Celles qui ont réellement cassé : l'amorçage Linux et le PXE."""
    import main
    assert "/firstboot-linux/000000000000" in main._ROUTES_MACHINES
    assert "/bootstrap/linux" in main._ROUTES_MACHINES
    assert "/boot" in main._ROUTES_MACHINES


# ── Le firstboot Linux doit rendre compte à OSIRIS ─────────────────────────
# Le 2026-08-05, une VM déployée a renvoyé UNE ligne à OSIRIS pour 41 écrites en
# local : le script redirige tout son stdout vers un fichier, donc un `echo` ne
# quitte jamais la machine. Diagnostiquer l'agent Zabbix absent et le /data non
# monté imposait d'ouvrir une console — impossible sur un site client.

def _firstboot_ubuntu_rendu():
    from jinja2 import Environment, FileSystemLoader
    import main
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters["bash_squote"] = main.jinja_env.filters["bash_squote"]
    return env.get_template("firstboot-ubuntu.sh.j2").render(
        machine=type("M", (), {"hostname": "SRV-TEST", "mac": "aabbccddeeff", "ou": ""})(),
        profile={"locale": "fr_FR.UTF-8", "keyboard": "fr", "timezone": "Europe/Paris",
                 "default_user": "osiris", "join_domain": False, "domain": "",
                 "domain_join_user": "", "domain_join_password": "", "post_script": "",
                 "ssh_authorized_keys": "", "extra_packages": ""},
        osiris_url="http://osiris", osiris_ip="10.0.0.1", tv_password="",
        linux_apps=[], zabbix={"server": "10.0.0.2", "hostname": "SRV-TEST",
                               "metadata": "osiris linux hc"},
        data_disk_gb=10, root_password="",
    )


def test_les_etapes_du_firstboot_partent_vers_osiris():
    """Sans ça, une VM distante est un trou noir : le journal reste sur la machine."""
    script = _firstboot_ubuntu_rendu()
    envoyees = script.count('_log "')
    restees_locales = len([l for l in script.splitlines()
                           if l.strip().startswith('echo "[$(ts)]')])
    # 25 sur un profil minimal (ni applications, ni TeamViewer, ni jonction AD :
    # les etapes correspondantes sont derriere des conditions Jinja non rendues).
    assert envoyees >= 20, f"seulement {envoyees} etapes remontees a OSIRIS"
    # Ne restent en local que les separateurs decoratifs et le gestionnaire d'erreur.
    assert restees_locales <= 4, f"{restees_locales} etapes encore invisibles depuis OSIRIS"


def test_la_fonction_de_log_n_est_pas_recursive():
    """Piège de la réécriture automatique : `_log() { _log ...; }` boucle à l'infini."""
    script = _firstboot_ubuntu_rendu()
    # Ancre sur le debut de ligne : "_osiris_log() {" contient "_log() {".
    corps = script.split("\n_log() {", 1)[1].split("}", 1)[0]
    assert "_log " not in corps.replace("_osiris_log ", "")
    assert 'echo "[$(ts)] $1"' in corps


def test_les_etapes_cles_sont_tracees():
    script = _firstboot_ubuntu_rendu()
    for etape in ("Application du nom d'hote", "Supervision Zabbix", "Disque de donnees"):
        assert f'_log "{etape}' in script or f'_log "{etape}"' in script


# ── Détection du disque de données ─────────────────────────────────────────
# Le 2026-08-05, `/data` n'était monté sur aucune VM : la commande de détection
# s'écrivait `lsblk -dnob NAME,TYPE,RM,SIZE`, où le `-o` du groupe avale le `b`
# comme argument. lsblk répondait « unknown column: b » et n'affichait rien, donc
# la boucle ne tournait jamais. Le script accusait alors l'hyperviseur de ne pas
# fournir de disque vierge. Jamais fonctionné, sur aucun hyperviseur.

def test_la_detection_de_disque_s_execute_vraiment():
    """On EXÉCUTE la commande : vérifier sa forme n'aurait pas attrapé le bug,
    puisque `-dnob` est une écriture parfaitement plausible."""
    import re, subprocess
    script = _firstboot_ubuntu_rendu()
    m = re.search(r'^\s*for _d in \$\((lsblk [^\n]+?) \\$', script, re.M)
    assert m, "commande de detection des disques introuvable dans le script"

    res = subprocess.run(m.group(1), shell=True, capture_output=True, text=True)
    assert res.returncode == 0, f"la commande echoue : {res.stderr.strip()}"
    assert "unknown column" not in res.stderr, f"option mal groupee : {res.stderr.strip()}"
    assert res.stdout.strip(), "aucun disque listé : la boucle de détection tournerait à vide"


def test_les_tailles_sont_bien_en_octets():
    """Le filtre compare à 1073741824 : sans `-b`, lsblk renvoie « 10G » et la
    comparaison numérique d'awk vaut 0, donc tout disque serait écarté."""
    import re, subprocess
    script = _firstboot_ubuntu_rendu()
    m = re.search(r'^\s*for _d in \$\((lsblk [^\n]+?) \\$', script, re.M)
    res = subprocess.run(m.group(1), shell=True, capture_output=True, text=True)
    tailles = [l.split()[3] for l in res.stdout.strip().splitlines() if len(l.split()) >= 4]
    assert tailles and all(t.isdigit() for t in tailles), f"tailles non numériques : {tailles}"


# ── Agent Zabbix servi par OSIRIS ──────────────────────────────────────────
# Ubuntu 24.04 « noble » ne fournit plus d'agent Zabbix (vérifié le 2026-08-05).
# Le firstboot retombe donc sur le .deb servi par OSIRIS, comme le MSI WithSecure
# côté Windows : aucune VM n'a à joindre repo.zabbix.com depuis le réseau client.

def test_l_agent_est_recupere_depuis_osiris_si_absent_des_depots():
    script = _firstboot_ubuntu_rendu()
    assert "/static/installers/zabbix-agent2.deb" in script
    # Les dépôts de la distribution restent essayés d'abord (Debian les fournit).
    assert script.index("apt-get install -y \"$_p\"") < script.index("zabbix-agent2.deb")


def test_aucun_depot_tiers_n_est_ajoute_a_la_machine():
    """Le .deb vient d'OSIRIS, pas de repo.zabbix.com : c'est tout l'intérêt.

    L'assertion ignore les commentaires : elle porte sur ce que le script FAIT,
    pas sur ce qu'il explique — un commentaire a le droit de nommer le dépôt
    qu'on a justement choisi de ne pas utiliser.
    """
    code = "\n".join(l for l in _firstboot_ubuntu_rendu().splitlines()
                     if not l.lstrip().startswith("#"))
    assert "repo.zabbix.com" not in code
    assert "add-apt-repository" not in code


def test_l_echec_dit_quoi_faire():
    """« aucun paquet disponible » n'indiquait aucune action à l'opérateur."""
    script = _firstboot_ubuntu_rendu()
    assert "backend/static/installers/zabbix-agent2.deb" in script


def test_la_configuration_suit_l_installation_par_deb():
    """Le .deb installe zabbix-agent2 : la conf doit viser le bon service."""
    script = _firstboot_ubuntu_rendu()
    apres = script.split("zabbix-agent2.deb", 1)[1]
    assert '_zbx_pkg="zabbix-agent2"' in apres
    assert 'if [ -n "$_zbx_pkg" ]; then' in apres
