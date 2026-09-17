# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un clone nu Linux n'appliquait JAMAIS l'adresse qu'on lui demandait.

OSIRIS écrivait l'adressage dans `guestinfo`, et rien côté Linux ne le lisait :
l'auto-adressage n'avait été fait que pour Windows. Le formulaire acceptait
pourtant l'IP fixe. Résultat, selon le VLAN : machine totalement muette là où il
n'y a pas de DHCP, ou déployée à une AUTRE adresse que celle demandée là où il y
en a un — sans que rien ne le signale dans les deux cas.

Ces tests ne lisent pas seulement le texte de l'agent : ils l'EXÉCUTENT contre
de faux `vmtoolsd`, `ip` et `netplan`. Un agent qui contient les bons mots mais
se trompe d'une accolade passerait une simple relecture et échouerait en réel —
et « en réel » veut dire une console sur une VM qui ne parle pas.
"""
import subprocess
import textwrap

import pytest
from jinja2 import Environment, FileSystemLoader

MARQUEUR = "# ── Adressage d'un clone nu"
FIN = "if adresse_utilisable; then"


@pytest.fixture(scope="module")
def agent() -> str:
    """Le script réellement gravé dans le gabarit (contenu du here-doc)."""
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    rendu = env.get_template("bootstrap-linux.sh.j2").render(osiris_url="http://osiris.test")
    debut = rendu.index("<< 'OSIRIS_BOOTSTRAP_EOF'\n") + len("<< 'OSIRIS_BOOTSTRAP_EOF'\n")
    return rendu[debut:rendu.index("\nOSIRIS_BOOTSTRAP_EOF", debut)]


@pytest.fixture(scope="module")
def fonctions(agent) -> str:
    """Les seules définitions de fonctions, sans le corps qui boucle sur curl."""
    return agent[agent.index(MARQUEUR):agent.index(FIN)]


def _bin_bidon(tmp_path, **scripts):
    """Un dossier de faux exécutables, prioritaire dans le PATH."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    for nom, corps in scripts.items():
        f = d / nom
        f.write_text("#!/bin/bash\n" + corps + "\n")
        f.chmod(0o755)
    return d


def _lancer(fonctions, corps, tmp_path, **scripts):
    scripts.setdefault("ip", 'echo "ip $*" >> "$TRACE"; exit 0')
    scripts.setdefault("netplan", 'echo "netplan $*" >> "$TRACE"; exit 0')
    scripts.setdefault("systemctl", 'echo "systemctl $*" >> "$TRACE"; exit 1')
    d = _bin_bidon(tmp_path, **scripts)
    trace = tmp_path / "trace.txt"
    script = tmp_path / "t.sh"
    for sous in ("cloudcfg", "ifupdown"):
        (tmp_path / sous).mkdir(exist_ok=True)
    script.write_text(
        f'export PATH="{d}:$PATH"\nexport TRACE="{trace}"\n'
        f'export OSIRIS_NETPLAN="{tmp_path}/60-osiris.yaml"\n'
        f'export OSIRIS_NETWORKD="{tmp_path}/60-osiris.network"\n'
        f'export OSIRIS_IFUPDOWN="{tmp_path}/ifupdown"\n'
        f'export OSIRIS_CLOUDCFG="{tmp_path}/cloudcfg"\n'
        f'export OSIRIS_RESOLV="{tmp_path}/resolv.conf"\n'
        f'ts() {{ echo T; }}\n{fonctions}\n{textwrap.dedent(corps)}\n')
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


# ── info_get : la leçon du 21/08, portée côté Linux ───────────────────────────

def test_info_get_rend_la_valeur(fonctions, tmp_path):
    vt = _bin_bidon(tmp_path, vmtoolsd='echo "10.0.5.20/24"') / "vmtoolsd"
    assert "10.0.5.20/24" in _lancer(fonctions, f'info_get {vt} guestinfo.osiris.ip', tmp_path)


def test_info_get_garde_la_valeur_MALGRE_un_code_de_sortie_non_nul(fonctions, tmp_path):
    """LE piège de `775441f`, transposé. Juger sur le code de sortie faisait
    jeter une valeur parfaitement bonne : c'est la VALEUR qui tranche, le code
    n'est qu'un indice, et l'appelant vérifie de toute façon la forme."""
    vt = _bin_bidon(tmp_path, vmtoolsd='echo "10.0.5.20/24"\nexit 3') / "vmtoolsd"
    assert "10.0.5.20/24" in _lancer(fonctions, f'info_get {vt} guestinfo.osiris.ip', tmp_path)


def test_info_get_ne_rend_rien_quand_il_n_y_a_rien(fonctions, tmp_path):
    vt = _bin_bidon(tmp_path, vmtoolsd='exit 1') / "vmtoolsd"
    sortie = _lancer(fonctions, f'echo "[$(info_get {vt} guestinfo.osiris.ip)]"', tmp_path)
    assert "[]" in sortie


def test_info_get_ne_garde_que_la_premiere_ligne_et_rogne_les_blancs(fonctions, tmp_path):
    """Une valeur propre est ce qui décide ensuite de configurer une carte."""
    vt = _bin_bidon(tmp_path, vmtoolsd='printf "  10.0.5.20/24  \\nbruit\\n"') / "vmtoolsd"
    sortie = _lancer(fonctions, f'echo "[$(info_get {vt} guestinfo.osiris.ip)]"', tmp_path)
    assert "[10.0.5.20/24]" in sortie


# ── L'adressage est écrit POUR DE BON ─────────────────────────────────────────

def test_netplan_recoit_adresse_route_et_dns(fonctions, tmp_path):
    """Le firstboot ne configure pas le réseau : si l'agent ne persiste pas
    l'adresse, elle disparaît au premier redémarrage et la machine redevient
    muette APRÈS avoir semblé marcher — pire qu'un échec franc."""
    _lancer(fonctions,
            'appliquer_adressage "10.0.5.20/24" "10.0.5.1" "10.0.5.110,10.0.5.210" ens192',
            tmp_path)
    ecrit = (tmp_path / "60-osiris.yaml").read_text()
    assert "ens192:" in ecrit
    assert "dhcp4: false" in ecrit
    assert "addresses: [10.0.5.20/24]" in ecrit
    assert "to: default" in ecrit and "via: 10.0.5.1" in ecrit
    assert "addresses: [10.0.5.110, 10.0.5.210]" in ecrit


def test_sans_passerelle_aucune_route_n_est_ecrite(fonctions, tmp_path):
    """Un VLAN sans route par défaut existe : ne pas inventer de passerelle."""
    _lancer(fonctions, 'appliquer_adressage "10.0.5.20/24" "" "" ens192', tmp_path)
    ecrit = (tmp_path / "60-osiris.yaml").read_text()
    assert "addresses: [10.0.5.20/24]" in ecrit
    assert "to: default" not in ecrit
    assert "nameservers" not in ecrit


def test_le_fichier_netplan_n_est_pas_lisible_par_tous(fonctions, tmp_path):
    """netplan refuse un fichier trop ouvert, dans un avertissement qu'on ne
    voit jamais depuis ici."""
    _lancer(fonctions, 'appliquer_adressage "10.0.5.20/24" "" "" ens192', tmp_path)
    assert oct((tmp_path / "60-osiris.yaml").stat().st_mode)[-3:] == "600"


def test_sans_AUCUN_moteur_le_repli_DIT_qu_il_est_temporaire(fonctions, tmp_path):
    """Laisser croire qu'une adresse est posée alors qu'elle disparaîtra au
    redémarrage est pire que de ne rien faire."""
    sortie = _lancer(fonctions,
                     'appliquer_adressage "10.0.5.20/24" "10.0.5.1" "" ens192',
                     tmp_path, netplan="exit 127", systemctl="exit 1")
    assert "ne survivra PAS au redemarrage" in sortie


# ── systemd-networkd : le moteur des Debian récentes ──────────────────────────

def test_networkd_prend_le_relais_quand_netplan_est_absent(fonctions, tmp_path):
    """Debian n'installe PAS netplan. Ne gérer que lui revenait à n'adresser
    durablement que la moitié du parc."""
    sortie = _lancer(fonctions,
                     'appliquer_adressage "10.0.5.20/24" "10.0.5.1" "10.0.5.110,10.0.5.210" ens192',
                     tmp_path,
                     netplan="exit 127",                 # netplan absent
                     systemctl='[ "$1" = "is-active" ] && exit 0; exit 0')
    ecrit = (tmp_path / "60-osiris.network").read_text()
    assert "Name=ens192" in ecrit
    assert "Address=10.0.5.20/24" in ecrit
    assert "Gateway=10.0.5.1" in ecrit
    # Une directive par serveur : networkd ne lit pas une liste à virgules.
    assert "DNS=10.0.5.110" in ecrit and "DNS=10.0.5.210" in ecrit
    assert "10.0.5.110,10.0.5.210" not in ecrit
    assert "networkd" in sortie


def test_networkd_inactif_n_est_PAS_choisi(fonctions, tmp_path):
    """Installé n'est pas « gère le réseau » : écrire pour un moteur endormi
    produirait un fichier parfait et aucune adresse."""
    _lancer(fonctions, 'appliquer_adressage "10.0.5.20/24" "" "" ens192',
            tmp_path, netplan="exit 127", systemctl="exit 1")
    assert not (tmp_path / "60-osiris.network").exists()


# ── ifupdown : le moteur des Debian classiques ────────────────────────────────

def test_ifupdown_prend_le_relais_en_dernier(fonctions, tmp_path):
    sortie = _lancer(fonctions,
                     'appliquer_adressage "10.0.5.20/24" "10.0.5.1" "10.0.5.110" ens192',
                     tmp_path,
                     netplan="exit 127", systemctl="exit 1",
                     ifup='exit 0', ifdown='exit 0')
    ecrit = (tmp_path / "ifupdown" / "60-osiris").read_text()
    assert "auto ens192" in ecrit
    assert "iface ens192 inet static" in ecrit
    assert "address 10.0.5.20/24" in ecrit
    assert "gateway 10.0.5.1" in ecrit
    assert "ifupdown" in sortie


# ── cloud-init ne doit pas reprendre la main ──────────────────────────────────

def test_cloud_init_est_neutralise_quand_on_impose_une_adresse(fonctions, tmp_path):
    """cloud-init réécrit le réseau à chaque démarrage et écraserait le nôtre."""
    _lancer(fonctions, 'appliquer_adressage "10.0.5.20/24" "" "" ens192', tmp_path)
    assert "config: disabled" in (tmp_path / "cloudcfg" / "99-osiris-network.cfg").read_text()


# ── Le filet DNS ──────────────────────────────────────────────────────────────

def test_resolv_conf_gere_par_systemd_n_est_PAS_ecrase(fonctions, tmp_path):
    """C'est un lien symbolique : écrire dedans serait réécrit au redémarrage,
    et on aurait cassé la résolution en croyant la réparer."""
    vrai = tmp_path / "resolved.conf"
    vrai.write_text("nameserver 127.0.0.53\n")
    (tmp_path / "resolv.conf").symlink_to(vrai)
    _lancer(fonctions, 'poser_resolv "10.0.5.110"', tmp_path)
    assert vrai.read_text() == "nameserver 127.0.0.53\n"


def test_resolv_conf_ordinaire_recoit_les_serveurs(fonctions, tmp_path):
    (tmp_path / "resolv.conf").write_text("")
    _lancer(fonctions, 'poser_resolv "10.0.5.110,10.0.5.210"', tmp_path)
    ecrit = (tmp_path / "resolv.conf").read_text()
    assert "nameserver 10.0.5.110" in ecrit and "nameserver 10.0.5.210" in ecrit


def test_resolv_conf_ne_recoit_pas_deux_fois_le_meme(fonctions, tmp_path):
    (tmp_path / "resolv.conf").write_text("nameserver 10.0.5.110\n")
    _lancer(fonctions, 'poser_resolv "10.0.5.110"', tmp_path)
    assert (tmp_path / "resolv.conf").read_text().count("10.0.5.110") == 1


def _code(script: str) -> str:
    """Le script sans ses commentaires — sinon une phrase qui EXPLIQUE pourquoi
    on n'utilise pas un réglage se lit comme si on l'utilisait."""
    return "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))


def test_la_route_par_defaut_n_utilise_pas_gateway4_deprecie(agent):
    """`gateway4:` est ignoré en silence par les netplan récents — le genre de
    réglage qui ne produit ni erreur, ni route."""
    assert "gateway4" not in _code(agent)
    assert "to: default" in _code(agent)


# ── Chaque cause porte un nom distinct ────────────────────────────────────────

def test_chaque_issue_DIT_laquelle(agent):
    """Le 21/08, le même « vide » couvrait trois causes et il a fallu une console
    pour trancher. Chaque branche doit se nommer dans le journal."""
    for phrase in ("vmtoolsd introuvable",              # pas VMware : normal
                   "aucune adresse dans guestinfo",     # DHCP voulu : normal
                   "pas encore lisible",                # Tools pas prêts
                   "aucune carte physique",             # cas tordu
                   "ne survivra PAS au redemarrage"):   # repli honnête
        assert phrase in agent, phrase


def test_l_agent_attend_que_vmware_tools_soit_pret(agent):
    """Les Tools démarrent APRÈS l'agent : lire une seule fois rend du vide.
    Constaté côté Windows le 21/08 — vide à 16:59, vide à 17:04, la valeur à
    17:14 en tapant la même commande à la main.

    L'attente longue vaut quand la machine n'a AUCUNE adresse : elle ne peut de
    toute façon rien faire d'autre.
    """
    assert "ESSAIS_TOOLS=18" in _code(agent)


def test_l_agent_n_impose_RIEN_quand_guestinfo_est_vide(agent):
    """La seule raison légitime de ne pas toucher au réseau : personne n'a rien
    demandé. Ce test remplace un « ne touche à rien s'il a déjà une adresse »
    qui encodait le bug du 17/09 — une adresse héritée du gabarit y faisait
    renoncer, et tous les clones sortaient sur la même."""
    assert "aucune adresse dans guestinfo" in _code(agent)


def test_169_254_n_est_PAS_prise_pour_une_adresse(agent):
    """C'est le symptôme même qu'on corrige : la prendre pour bonne ferait
    renoncer l'agent juste avant de servir à quelque chose."""
    assert "169" in agent and "254" in agent


def test_les_trois_cles_sont_lues(agent):
    for cle in ("guestinfo.osiris.ip", "guestinfo.osiris.gateway",
                "guestinfo.osiris.dns"):
        assert cle in agent, cle


def test_un_hyperviseur_non_VMware_ne_declenche_rien(agent):
    """Proxmox, KVM nu, matériel physique : pas de canal guestinfo, et c'est
    normal. Traiter ça comme une panne ferait chercher un bug inexistant."""
    assert "hyperviseur non VMware" in agent


def test_un_moteur_qui_echoue_ne_laisse_AUCUN_fichier(fonctions, tmp_path):
    """Un fichier de configuration orphelin serait relu au prochain démarrage,
    et imposerait une adresse que plus personne n'a demandée — sur une machine
    dont on croit, elle, qu'elle est en DHCP."""
    _lancer(fonctions, 'appliquer_adressage "10.0.5.20/24" "10.0.5.1" "" ens192',
            tmp_path, netplan="exit 127", systemctl="exit 1")
    assert not (tmp_path / "60-osiris.yaml").exists()
    assert not (tmp_path / "60-osiris.network").exists()
    assert not (tmp_path / "ifupdown" / "60-osiris").exists()


# ── Une adresse héritée du gabarit ne fait PAS renoncer ───────────────────────
# Un gabarit fabriqué à partir d'une VM déployée emporte le réseau de cette VM —
# c'est la méthode recommandée pour en fabriquer un. Chacun de ses clones démarre
# donc avec l'adresse de la machine d'origine. Renoncer là donnerait à TOUS les
# clones la MÊME adresse : le 17/09, un clone demandé en .202 tournait en .201,
# celle de la VM qui avait servi à bâtir le gabarit.

def test_une_adresse_deja_presente_ne_fait_pas_renoncer(agent):
    """`adresse_utilisable` décide de la PATIENCE, pas de l'action."""
    code = _code(agent)
    assert "rien a imposer" not in code, \
        "avoir une adresse ne doit plus court-circuiter la lecture de guestinfo"
    assert "ESSAIS_TOOLS" in code, "la patience doit être la seule variable"


def test_on_attend_moins_longtemps_quand_on_a_deja_une_adresse(agent):
    """Une machine qui peut déjà travailler ne doit pas être retardée de trois
    minutes pour un canal qui, le plus souvent, ne dira rien."""
    code = _code(agent)
    assert "ESSAIS_TOOLS=2" in code and "ESSAIS_TOOLS=18" in code


def test_le_netplan_du_gabarit_est_retire(agent):
    """Il porte une AUTRE clé d'interface que la nôtre : netplan appliquerait
    les deux, et la machine porterait l'adresse imposée ET l'héritée."""
    assert "rm -f /etc/netplan/50-cloud-init.yaml" in _code(agent)


def test_l_adresse_imposee_ECRASE_l_heritee(fonctions, tmp_path):
    """Le cas réel, exécuté : la machine porte déjà une adresse, guestinfo en
    impose une autre, c'est celle de guestinfo qui doit être écrite."""
    _lancer(fonctions,
            'appliquer_adressage "10.0.5.202/24" "10.0.5.1" "10.0.5.110" ens192',
            tmp_path)
    ecrit = (tmp_path / "60-osiris.yaml").read_text()
    assert "addresses: [10.0.5.202/24]" in ecrit
    assert "10.0.5.201" not in ecrit
