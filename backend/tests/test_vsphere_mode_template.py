# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le clone nu sur vSphere — la seule voie possible pour Windows sur un site distant.

vSphere n'acceptait que le mode cloud-init, donc que du Linux : Windows n'a pas de
cloud-init pour lire une configuration injectée. Et le PXE, l'autre voie côté
Proxmox, ne traverse pas les tunnels — ni le DHCP ni le TFTP ne se routent.

Restait le clone nu : on duplique un gabarit déjà scellé, sans rien lui injecter.
Il porte l'agent d'amorçage posé avant le sysprep, lit sa propre MAC au premier
démarrage, et demande son script à OSIRIS. C'est le même mécanisme que le mode
`template` de Proxmox, qui fonctionne depuis le 06/08.
"""
import asyncio

import pytest
from fastapi import HTTPException

import vsphere
from main import VmCreateBody


def _body(**overrides) -> VmCreateBody:
    base = dict(hostname="srv-win", client="Namek", os="windows",
                node="Clus01", storage="ds1", bridge="DATA-Infra",
                boot_mode="template", template_id=None)
    base.update(overrides)
    return VmCreateBody(**base)


def _appel(body):
    return asyncio.run(vsphere.VSphereProvider.provision_vm(
        h=None, body=body, vm_id=0,
        mac_colons="aa:bb:cc:dd:ee:ff", mac_plain="aabbccddeeff",
    ))


# ── Le mode est-il accepté ? ──────────────────────────────────────────────────

def test_le_mode_template_est_accepte():
    """Il doit passer le garde de mode et n'échouer que sur le gabarit manquant —
    preuve qu'il n'est plus refusé d'entrée."""
    with pytest.raises(HTTPException) as exc:
        _appel(_body(boot_mode="template", template_id=None))
    assert exc.value.status_code == 400
    assert "template_id" in exc.value.detail


def test_le_mode_cloudinit_fonctionne_toujours():
    """Non-régression : le chemin Linux existant ne doit pas être emporté."""
    with pytest.raises(HTTPException) as exc:
        _appel(_body(boot_mode="cloudinit", os="ubuntu", template_id=None))
    assert "template_id" in exc.value.detail


def test_le_pxe_reste_refuse_avec_sa_raison():
    """Le refus doit expliquer POURQUOI : sans cela, on cherche une panne de
    configuration là où c'est le réseau qui rend la chose impossible."""
    with pytest.raises(HTTPException) as exc:
        _appel(_body(boot_mode="pxe", template_id=1))
    assert exc.value.status_code == 400
    assert "PXE" in exc.value.detail


# ── Que reçoit le clone ? ─────────────────────────────────────────────────────

class _CorpsSimple:
    def __init__(self, boot_mode):
        self.boot_mode = boot_mode


def test_le_clone_nu_ne_recoit_AUCUNE_configuration():
    """Le cœur du mode. Injecter un cloud-init dans un clone Windows serait sans
    effet — rien ne le lirait — mais graverait quand même la configuration, mots
    de passe compris, dans la fiche de la VM côté hyperviseur. Pour rien."""
    rendu = vsphere.payload_cloud_init(
        _CorpsSimple("template"),
        user_data="#cloud-config\nhostname: srv",
        render_user_data=lambda mac: "#cloud-config\nrendu: oui",
        mac_plain="aabbccddeeff",
    )
    assert rendu == ""


def test_le_mode_cloudinit_rend_bien_avec_la_MAC_definitive():
    """Sur vSphere la MAC n'existe qu'une fois le clone fait, et c'est par elle que
    la machine s'identifie : le rendu doit se faire avec la vraie, pas la
    provisoire."""
    vues = []
    rendu = vsphere.payload_cloud_init(
        _CorpsSimple("cloudinit"),
        user_data="ancien",
        render_user_data=lambda mac: vues.append(mac) or f"pour-{mac}",
        mac_plain="005056aabbcc",
    )
    assert vues == ["005056aabbcc"]
    assert rendu == "pour-005056aabbcc"


def test_sans_MAC_on_retombe_sur_le_contenu_deja_rendu():
    """Garde-fou : plutôt que d'appeler le rendu avec une MAC vide, on garde ce
    qui avait été préparé en amont."""
    rendu = vsphere.payload_cloud_init(
        _CorpsSimple("cloudinit"),
        user_data="prepare-en-amont",
        render_user_data=lambda mac: "ne-doit-pas-etre-appele",
        mac_plain="",
    )
    assert rendu == "prepare-en-amont"
