# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un clone Windows démarrait en 169.254.x.x et ne rappelait jamais OSIRIS.

Le sysprep remet la carte réseau en DHCP. Sur les VLAN serveurs de Namek, qui
n'en ont pas, le clone se rabat sur une adresse d'auto-configuration : il
démarre, VMware Tools tourne, tout va bien — et il ne joint personne. Panne
parfaitement silencieuse : la machine qui devrait signaler le problème est
justement celle qui ne peut pas parler.

Constaté le 21/08 sur le premier clone Windows du vCenter, débloqué à la main
en console. La sortie est de lui donner son adresse par un canal qui ne passe
PAS par le réseau : VMware Tools lit la configuration de la VM directement.

Ces clés sont le strict minimum — trois valeurs, aucun secret. C'est ce qui les
distingue d'une configuration cloud-init, qu'un clone nu ne doit jamais recevoir
(cf. `payload_cloud_init`) : sans elles, la machine ne peut pas aller chercher
le reste.
"""
import pytest
from jinja2 import Environment, FileSystemLoader

import main
import vsphere
from main import VmCreateBody

CLES_AUTORISEES = {"guestinfo.osiris.ip", "guestinfo.osiris.gateway", "guestinfo.osiris.dns"}


def _body(**o):
    base = dict(hostname="nk-win-test01", client="Namek", os="windows",
                node="Clus01", storage="ds1", bridge="DATA-Infra",
                boot_mode="template", template_id=42,
                ip_cidr="10.0.5.20/24", gateway="10.0.5.1",
                dns_servers="10.0.5.110,10.0.5.210")
    base.update(o)
    return VmCreateBody(**base)


def _cles(**o):
    return dict(vsphere.guestinfo_reseau(_body(**o)))


# ── Ce qui est écrit ──────────────────────────────────────────────────────────

def test_l_adresse_la_passerelle_et_les_dns_sont_transmises():
    c = _cles()
    assert c["guestinfo.osiris.ip"] == "10.0.5.20/24"
    assert c["guestinfo.osiris.gateway"] == "10.0.5.1"
    assert c["guestinfo.osiris.dns"] == "10.0.5.110,10.0.5.210"


def test_les_cles_sont_prefixees_guestinfo():
    """Sans ce préfixe, `vmtoolsd --cmd info-get` refuse de lire la valeur depuis
    l'invité : c'est la frontière de sécurité de VMware, pas une convention."""
    assert all(k.startswith("guestinfo.") for k in _cles())


def test_les_dns_sont_nettoyes():
    assert _cles(dns_servers=" 10.0.5.110 , ,10.0.5.210 ")["guestinfo.osiris.dns"] \
        == "10.0.5.110,10.0.5.210"


def test_rien_d_autre_que_l_adressage_ne_part():
    """Ces clés sont lisibles par quiconque ouvre la fiche de la VM côté
    hyperviseur : elles ne doivent JAMAIS transporter autre chose."""
    assert set(_cles()) <= CLES_AUTORISEES


# ── Quand on n'écrit rien ─────────────────────────────────────────────────────

def test_rien_en_mode_cloudinit():
    """C'est `_metadata` qui porte le réseau là-bas ; deux mécanismes concurrents
    finiraient par diverger."""
    assert vsphere.guestinfo_reseau(_body(boot_mode="cloudinit", os="ubuntu")) == []


def test_sans_adresse_demandee_les_cles_sont_VIDEES_pas_omises():
    """Ne pas écrire ne veut PAS dire ne rien imposer : ça veut dire hériter.

    Un clone vSphere reprend l'`extraConfig` de son gabarit. Un gabarit fabriqué
    depuis une VM déployée par OSIRIS porte encore les `guestinfo.osiris.*` de
    cette VM-là — c'est le mode de fabrication normal, pas un accident. Omettre
    les clés laissait donc un clone en DHCP se voir attribuer l'adresse fixe
    d'une autre machine, sans un mot.

    Le bug dormait derrière l'agent cassé, qui ne lisait jamais ces clés. Le
    réparer le réveillait : on écrase donc toujours, et vide vaut « rien
    d'imposé », que l'agent traite en DHCP.
    """
    c = _cles(ip_cidr="", gateway="", dns_servers="")
    assert c == {"guestinfo.osiris.ip": "",
                 "guestinfo.osiris.gateway": "",
                 "guestinfo.osiris.dns": ""}


def test_une_adresse_sans_passerelle_reste_utilisable():
    """Un VLAN sans route par défaut existe : ne pas tout refuser pour autant."""
    c = _cles(gateway="", dns_servers="")
    assert c["guestinfo.osiris.ip"] == "10.0.5.20/24"
    # Vidées, et non omises : sinon le clone hériterait de celles du gabarit.
    assert c["guestinfo.osiris.gateway"] == ""
    assert c["guestinfo.osiris.dns"] == ""


def test_une_adresse_heritee_ne_peut_JAMAIS_survivre_au_clonage():
    """Le garde-fou, exprimé sur ce qui compte : quoi qu'on demande, les trois
    clés sont toujours réécrites, donc rien du gabarit ne passe au travers."""
    for demande in ({}, {"ip_cidr": ""}, {"gateway": "", "dns_servers": ""},
                    {"ip_cidr": "", "gateway": "", "dns_servers": ""}):
        assert set(_cles(**demande)) == CLES_AUTORISEES, demande


# ── L'agent gravé dans le gabarit ─────────────────────────────────────────────

@pytest.fixture
def agent():
    """Le script réellement écrit dans le gabarit : le contenu du here-string."""
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    rendu = env.get_template("bootstrap-windows.ps1.j2").render(osiris_url="http://osiris.test")
    debut = rendu.index("$amorcage = @'")
    return rendu[debut:rendu.index("\n'@", debut)]


def _code(script):
    return "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))


def test_l_agent_lit_les_trois_cles(agent):
    for cle in CLES_AUTORISEES:
        assert cle in _code(agent)


def test_l_agent_ne_touche_a_rien_s_il_a_deja_une_adresse(agent):
    """Sur un réseau avec DHCP, le bail fait le travail. Écraser une
    configuration qui marche serait le meilleur moyen de casser ce qu'on répare
    — et l'agent est rejoué à CHAQUE démarrage tant que le firstboot n'a pas eu
    lieu, donc il doit être sans effet la deuxième fois."""
    code = _code(agent)
    assert "if (-not (AdresseUtilisable))" in code
    assert '169.254.' in code, "l'auto-configuration doit être reconnue comme inutilisable"


def test_l_agent_pose_l_adresse_avant_d_appeler_osiris(agent):
    """Tout l'intérêt : sans adresse, l'appel à OSIRIS ne peut pas aboutir."""
    code = _code(agent)
    assert code.index("guestinfo.osiris.ip") < code.index("/firstboot-windows/$mac")


def test_l_agent_survit_a_l_absence_de_vmware_tools(agent):
    """Le même gabarit peut être cloné sur Proxmox, où vmtoolsd n'existe pas."""
    code = _code(agent)
    bloc = code.split("function CheminVmtoolsd")[1].split("function InfoGet")[0]
    assert "Test-Path" in bloc


# ── Le piège des consoles 32 bits ─────────────────────────────────────────────
# Sur un Windows 64 bits, un processus 32 bits voit C:\Windows\System32 redirigé
# vers SysWOW64 et $env:ProgramFiles valoir "C:\Program Files (x86)". Deux façons
# de chercher une panne là où il n'y a qu'une mauvaise console.
# Constaté le 21/08 : scellement lancé depuis « Windows PowerShell (x86) ».

@pytest.fixture
def scellement():
    """Le script complet, pas seulement l'agent : sysprep vit hors du here-string."""
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    return env.get_template("bootstrap-windows.ps1.j2").render(osiris_url="http://osiris.test")


def test_sysprep_reste_atteignable_depuis_une_console_32_bits(scellement):
    """Sans Sysnative, sysprep.exe est introuvable et le message accuse le
    fichier alors que c'est la console qui est en cause."""
    code = _code(scellement)
    assert "Sysnative" in code
    assert "Is64BitProcess" in code


def test_vmtoolsd_est_cherche_dans_les_deux_program_files(agent):
    code = _code(agent)
    assert "C:\\Program Files\\VMware" in code
    assert "C:\\Program Files (x86)\\VMware" in code


def test_vmtoolsd_absent_ne_fait_pas_echouer_l_amorcage(agent):
    """Le même gabarit doit rester clonable sur Proxmox, sans VMware Tools."""
    code = _code(agent)
    assert "Test-Path" in code.split("function CheminVmtoolsd")[1].split("function InfoGet")[0]
    assert 'return ""' in code.split("function InfoGet")[1].split("if (-not (AdresseUtilisable))")[0]


def test_chaque_echec_de_lecture_DIT_sa_cause(agent):
    """Trois causes rendaient le même « vide » : outil absent, commande en échec,
    valeur absente. Le journal affichait la même phrase dans les trois cas, et il
    a fallu ouvrir une console pour trancher — le 21/08, précisément. Un journal
    qui ne distingue pas les causes ne sert qu'à rassurer."""
    bloc = _code(agent).split("function InfoGet")[1].split("if (-not (AdresseUtilisable))")[0]
    assert "vmtoolsd introuvable" in bloc
    assert "lancement de vmtoolsd impossible" in bloc
    assert "aucune sortie (code" in bloc


def test_on_attend_que_vmware_tools_soit_pret(agent):
    """VMware Tools démarre PENDANT l'amorçage. Constaté le 21/08 : deux lectures
    à 16:59 et 17:04 rendent vide, la même commande tapée à 17:14 rend l'adresse.
    Une lecture unique condamnait la machine — rien ne la ramène dans ce bloc."""
    bloc = _code(agent).split("if (-not (AdresseUtilisable))")[1]
    assert "for ($essaiIp = 1; $essaiIp -le 18" in bloc
    assert "Start-Sleep -Seconds 10" in bloc.split("$carte")[0]


def test_on_n_attend_PAS_hors_vsphere(agent):
    """Sans vmtoolsd, il n'y a rien à attendre : faire patienter trois minutes
    chaque clone Proxmox pour un résultat connu d'avance serait absurde."""
    bloc = _code(agent).split("if (-not (AdresseUtilisable))")[1]
    assert "if (-not (CheminVmtoolsd))" in bloc


def test_le_reessai_s_arrete_des_qu_il_a_l_adresse(agent):
    """Sinon on paierait l'attente complète à chaque déploiement sain."""
    bloc = _code(agent).split("if (-not (AdresseUtilisable))")[1]
    assert "if ($cidr) {" in bloc
    assert "break" in bloc


def test_la_valeur_prime_sur_le_code_de_sortie(agent):
    """Le 21/08, `vmtoolsd` a rendu un code de sortie NUL. Comme `$null -ne 0`,
    la lecture était comptée en échec et la valeur jetée — alors qu'elle était
    peut-être bonne. Le code de sortie est un indice ; la valeur est ce qu'on est
    venu chercher, et l'appelant vérifie de toute façon qu'elle ressemble à une
    adresse. C'est donc elle qui décide."""
    bloc = _code(agent).split("function InfoGet")[1].split("if (-not (AdresseUtilisable))")[0]
    assert "if (-not $texte)" in bloc
    assert "$code -ne 0" not in bloc, "le code de sortie ne doit plus décider"


def test_l_invocation_de_vmtoolsd_est_nue(agent):
    """Emballée dans une expression, elle rendait une sortie vide ET un
    $LASTEXITCODE nul — deux symptômes pour une seule cause."""
    bloc = _code(agent).split("function InfoGet")[1].split("if (-not (AdresseUtilisable))")[0]
    assert '$sortie = & $exe --cmd "info-get $cle" 2>&1' in bloc
