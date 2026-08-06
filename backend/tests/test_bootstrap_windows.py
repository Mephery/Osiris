# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Amorçage générique des templates Windows.

Le clone d'un template sysprepé n'a rien de ce dont dispose un poste déployé par
WinPE : ni `osiris.cfg`, ni script de premier démarrage gravé à sa MAC. Il doit
donc découvrir OSIRIS et sa propre identité seul — pendant Windows de
`/bootstrap/linux`.

Ce qui est vérifié ici tient en une phrase : **rien de ce qui distingue une
machine d'une autre ne doit se retrouver dans un template**, puisque le fichier
part à l'identique dans tous les clones.
"""
import re

import main
from models import OsImage, engine
from sqlmodel import Session

MAC = "aabbccddeeff"


def test_les_delimiteurs_de_lamorcage_sont_equilibres(client):
    """
    Aucun PowerShell sur l'hôte de build : à défaut d'un vrai analyseur, on vérifie
    que le script ne part pas déséquilibré. Même garde-fou que sur le firstboot —
    il y avait attrapé une apostrophe française prise pour un début de chaîne.
    """
    script = client.get("/bootstrap/windows").text
    sans_chaines = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "", script)

    assert sans_chaines.count("{") == sans_chaines.count("}")
    assert sans_chaines.count("(") == sans_chaines.count(")")


def test_lamorcage_ne_contient_aucun_secret(client):
    """
    Le pari de tout le mécanisme : le template ne stocke aucun identifiant. C'est
    ce qui a fait écarter le compte Proxmox dédié côté Linux, pour les mêmes
    raisons de sécurité — et ça doit rester vrai ici.
    """
    script = client.get("/bootstrap/windows").text

    assert main.OSIRIS_BASE_URL in script          # l'adresse d'OSIRIS, et elle seule
    # On vise les VALEURS, pas les mots : le script parle de « secret » dans les
    # commentaires qui expliquent précisément qu'il n'en contient aucun.
    assert main.WINDOWS_TEMPLATE_ADMIN_PASSWORD not in script
    assert "gAAAAA" not in script                  # préfixe d'un jeton Fernet chiffré
    assert "PVEAPIToken" not in script


def test_lamorcage_lit_sa_mac_et_appelle_osiris(client):
    """Toute l'astuce : la machine se nomme elle-même, le template n'en sait rien."""
    script = client.get("/bootstrap/windows").text

    assert "Get-NetAdapter -Physical" in script
    assert "/firstboot-windows/$mac" in script
    assert "status=deploying" in script


def test_lamorcage_distingue_les_causes_dechec(client):
    """
    Le 05/08 côté Linux, une 404, une 308 et un serveur injoignable rendaient le
    même silence : le diagnostic a accusé la mauvaise cause pendant cinq minutes.
    L'amorçage Windows ne doit pas répéter l'erreur.
    """
    script = client.get("/bootstrap/windows").text

    assert "-MaximumRedirection 0" in script       # sinon une 308 passe pour un succès
    assert "REDIRECTION" in script
    assert "serveur injoignable" in script
    assert "pas de fiche pour cette MAC" in script


def test_lamorcage_retente_au_demarrage_suivant(client):
    """
    L'ouverture de session automatique ne se déclenche QU'UNE FOIS : sans filet,
    un clone démarré pendant une coupure réseau resterait orphelin pour toujours.
    """
    script = client.get("/bootstrap/windows").text

    assert "OsirisFirstBoot" in script
    assert "New-ScheduledTaskTrigger -AtStartup" in script


def test_le_firstboot_decroche_le_filet_quand_il_a_vraiment_tourne(client, test_machine):
    """
    Le pendant du test précédent. Décrocher plus tôt rendrait toute panne en cours
    de route définitive ; ne jamais décrocher rejouerait le déploiement à chaque
    démarrage.
    """
    with Session(engine) as session:
        session.add(OsImage(name="Windows Server 2025", os="windows", version="2025",
                            status="ready", iso_url="", wim_name="server2025.wim"))
        session.commit()

    firstboot = client.get(f"/firstboot-windows/{MAC}").text

    assert 'Unregister-ScheduledTask -TaskName "OsirisFirstBoot"' in firstboot


def test_le_fichier_de_reponses_ne_grave_aucun_nom_de_machine(client):
    """
    Un `<ComputerName>` dans un fichier de réponses de template donnerait le MÊME
    nom à tous les clones. C'est le firstboot d'OSIRIS qui renomme la machine.
    """
    xml = client.get("/bootstrap/windows/unattend.xml").text

    assert "<ComputerName>" not in xml
    assert "<JoinDomain>" not in xml               # le domaine dépend du profil du clone
    assert "OSIRIS Bootstrap" in xml               # il lance l'amorçage, pas un script figé


def test_le_fichier_de_reponses_saute_loobe(client):
    """Sans ça, chaque clone attendrait qu'un humain choisisse une langue."""
    xml = client.get("/bootstrap/windows/unattend.xml").text

    assert "<HideEULAPage>true</HideEULAPage>" in xml
    assert "<Enabled>true</Enabled>" in xml        # ouverture de session automatique
    assert "osiris-admin" in xml


def test_le_scellement_lance_sysprep_en_generalize(client):
    """`/generalize` est ce qui efface le SID : sans lui, tous les clones le partagent."""
    script = client.get("/bootstrap/windows").text

    assert "/generalize" in script
    assert "/oobe" in script
    assert "/shutdown" in script


def test_la_route_est_declaree_comme_appelee_par_les_machines(client):
    """
    Une route de déploiement absente du matcher du frontal répond 308, et
    l'amorçage échoue en boucle sans que rien ne le signale — le bug du 05/08.
    Le contrôle au démarrage ne couvre que les routes de cette liste.
    """
    assert "/bootstrap/windows" in main._ROUTES_MACHINES
