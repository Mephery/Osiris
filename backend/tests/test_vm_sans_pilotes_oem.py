# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Une VM ne reçoit aucun pilote constructeur.

Le matériel d'une VM est virtuel et standard — SATA + e1000 ont justement été
retenus pour que tout soit *inbox*. Aucun pack Dell/HP/Lenovo ne peut correspondre
à « Standard PC (Q35 + ICH9, 2009) », si bien que la résolution retombait sur le
fallback historique « tout le dossier » : 36 Go et 2046 fichiers .inf poussés par
DISM à travers SMB, des heures durant, pour du matériel qui n'existera jamais.
Observé sur SRV-WIN-ISO le 2026-08-05.
"""
import main
from models import Machine, OsImage, engine
from sqlmodel import Session, select

MAC = "aabbccddeeff"


def _image_windows_prete() -> None:
    """Sans image `ready`, /winpe-script rend un script de repli sans déploiement."""
    with Session(engine) as session:
        session.add(OsImage(name="Windows Server 2025", os="windows", version="2025",
                            status="ready", iso_url="", wim_name="server2025.wim"))
        session.commit()


def _fait_de_la_machine_une_vm() -> Machine:
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        m.proxmox_vm_id, m.proxmox_node = 123, "pve"
        session.add(m)
        session.commit()
        session.refresh(m)
        return m


def test_une_vm_ne_se_voit_attribuer_aucun_dossier_de_pilotes(test_machine):
    assert main._resolve_driver_dir(_fait_de_la_machine_une_vm()) == ""


def test_une_machine_physique_garde_le_repli_historique(test_machine):
    """Le poste physique, lui, a toujours besoin de ses pilotes constructeurs."""
    assert main._resolve_driver_dir(test_machine) == "drivers"


def test_le_script_winpe_dune_vm_ne_lance_aucun_dism_add_driver(client, test_machine):
    """
    Le test porte sur le script REELLEMENT rendu : vérifier la valeur de
    `driver_dir` n'aurait rien prouvé, puisque le gabarit teste `if exist Z:\\...`
    et qu'un chemin vide y aurait désigné la racine du partage — donc TOUT.
    """
    _image_windows_prete()
    _fait_de_la_machine_une_vm()

    script = client.get(f"/winpe-script/{MAC}").text

    assert "/Add-Driver" not in script
    # Le message part dans une URL : les espaces y sont des « + ».
    assert "pilotes+constructeurs+inutiles" in script


def test_le_script_dune_machine_physique_injecte_toujours(client, test_machine):
    _image_windows_prete()

    script = client.get(f"/winpe-script/{MAC}").text

    assert "/Add-Driver" in script
    assert "Z:\\drivers\\" in script
