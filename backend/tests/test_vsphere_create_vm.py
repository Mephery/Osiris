# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le déploiement cloud-init sur vSphere était cassé depuis le 06/08, en silence.

`de21c87` a renommé `cloud_template_id` en `template_id` sur le corps de requête
partagé par les deux hyperviseurs, et mis à jour le côté Proxmox — mais pas
`vsphere.py`, qui continuait de lire `body.cloud_template_id`. Ce champ n'existe
plus sur `VmCreateBody` : au premier appel réel, Pydantic levait une simple
`AttributeError` avant même d'atteindre la validation métier, et FastAPI la
renvoyait en 500 nu, sans détail. Repéré le 19/08 en tentant un vrai déploiement
sur le vCenter Namek.

Rien ne l'avait attrapé : les seuls tests touchant `vsphere.py` appelaient
`_metadata()` avec un bouchon `Body` maison, jamais le vrai `VmCreateBody` que
l'API construit. Celui-ci exerce `provision_vm` avec l'objet réel.
"""
import asyncio

import pytest
from fastapi import HTTPException

from main import VmCreateBody
from vsphere import VSphereProvider


def _body(**overrides) -> VmCreateBody:
    base = dict(hostname="nk-test", client="Namek", os="ubuntu",
                node="Clus01", storage="ds1", bridge="HC-DEV",
                boot_mode="cloudinit", template_id=None)
    base.update(overrides)
    return VmCreateBody(**base)


def test_template_id_manquant_leve_une_erreur_metier_pas_une_attributeerror():
    """Le vrai bug : sans template_id, l'appel doit répondre 400 avec un message
    clair — pas planter sur un attribut qui n'existe plus."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(VSphereProvider.provision_vm(
            h=None, body=_body(template_id=None), vm_id=0,
            mac_colons="aa:bb:cc:dd:ee:ff", mac_plain="aabbccddeeff",
        ))
    assert exc.value.status_code == 400
    assert "template_id" in exc.value.detail


def test_vmcreatebody_ne_porte_plus_lancien_nom_du_champ():
    """Verrou direct sur la régression : si `cloud_template_id` réapparaît un jour
    sur ce modèle (ou si `template_id` disparaît), ce test le dit tout de suite."""
    champs = VmCreateBody.model_fields
    assert "template_id" in champs
    assert "cloud_template_id" not in champs
