# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un clone nu rejouait l'identité de la machine qui avait servi à bâtir son gabarit.

Un gabarit fabriqué à partir d'une VM déployée en cloud-init emporte les
métadonnées de cette VM — et c'est la manière NORMALE d'en fabriquer un. Le
clone en hérite, cloud-init y trouve une source de données VMware parfaitement
valide, et rejoue ce qu'elle contient : nom d'hôte, adressage, et jusqu'au
script de premier démarrage de la machine de construction.

Constaté le 17/09 : une VM demandée sous le nom `valid-debian` en 198.51.100.203
tournait sous le nom de la VM de construction. L'agent avait bien posé l'adresse
à 14:30:00 ; cloud-init a reposé l'identité du gabarit à 14:30:18.

C'est le même piège que les `guestinfo.osiris.*` héritées, corrigé le matin même,
sur un autre jeu de clés — et la même réponse : on ÉCRASE, on n'omet pas.
"""
import pytest

import vsphere
from main import VmCreateBody

CLES_CLOUD_INIT = {"guestinfo.userdata", "guestinfo.userdata.encoding",
                   "guestinfo.metadata", "guestinfo.metadata.encoding"}


def _body(**o):
    base = dict(hostname="valid-debian", client="Namek", os="debian",
                node="Clus01", storage="ds1", bridge="DATA-Infra",
                boot_mode="template", template_id=42,
                ip_cidr="10.0.5.203/24", gateway="10.0.5.1",
                dns_servers="10.0.5.110")
    base.update(o)
    return VmCreateBody(**base)


def test_un_clone_nu_ne_recoit_AUCUNE_charge_cloud_init():
    """Le contrat du mode gabarit : rien n'est injecté."""
    assert vsphere.payload_cloud_init(_body(), "", None, "005056aa0042") == ""


def test_le_mode_cloudinit_recoit_bien_la_sienne():
    """Contrôle du contrôle : sans lui, le test précédent passerait même si la
    fonction rendait toujours une chaîne vide."""
    charge = vsphere.payload_cloud_init(
        _body(boot_mode="cloudinit", os="ubuntu"), "#cloud-config\n", None, "005056aa0042")
    assert charge == "#cloud-config\n"


def test_les_cles_cloud_init_sont_VIDEES_sur_un_clone_nu(monkeypatch):
    """Le cœur du correctif, vérifié sur ce qui part vraiment vers l'hyperviseur.

    Ne rien écrire laissait les clés du gabarit intactes — donc une source de
    données valide, donc l'identité de la machine de construction rejouée.
    """
    ecrits = _capturer(monkeypatch, _body())
    assert CLES_CLOUD_INIT <= set(ecrits), \
        f"clés cloud-init non écrasées : {sorted(CLES_CLOUD_INIT - set(ecrits))}"
    for cle in CLES_CLOUD_INIT:
        assert ecrits[cle] == "", f"{cle} doit être vidée, pas remplie"


def test_l_adressage_osiris_reste_ecrit_lui(monkeypatch):
    """Les deux jeux de clés cohabitent : on vide celui de cloud-init, on
    renseigne celui que l'agent gravé va lire."""
    ecrits = _capturer(monkeypatch, _body())
    assert ecrits["guestinfo.osiris.ip"] == "10.0.5.203/24"


def test_en_mode_cloudinit_les_cles_sont_REMPLIES(monkeypatch):
    """L'autre moitié : on ne vide que là où rien ne doit être injecté."""
    ecrits = _capturer(monkeypatch, _body(boot_mode="cloudinit", os="ubuntu"),
                       user_data="#cloud-config\nbonjour: oui\n")
    assert ecrits["guestinfo.metadata"], "les métadonnées doivent être posées"
    assert ecrits["guestinfo.metadata.encoding"] == "base64"


# ── Harnais ───────────────────────────────────────────────────────────────────

def _capturer(monkeypatch, body, user_data: str = "") -> dict:
    """Rejoue `_finish` en interceptant tout ce qui est écrit en extraConfig."""
    ecrits: dict = {}

    class FauxTache:
        info = type("I", (), {"state": "success", "result": None})()

    class FauxVm:
        name = "valid-debian"
        _moId = "vm-1"

        class config:
            uuid = "42010000-0000-4000-8000-000000000001"
            files = type("F", (), {"vmPathName": "[ds1] x/x.vmx"})()

            class hardware:
                device = []

        def ReconfigVM_Task(self, spec):
            for o in (spec.extraConfig or []):
                ecrits[o.key] = o.value
            return FauxTache()

        def PowerOnVM_Task(self):
            return FauxTache()

    monkeypatch.setattr(vsphere, "_wait", lambda t: None)
    monkeypatch.setattr(vsphere, "_grow_system_disk", lambda vm, gb: None)
    monkeypatch.setattr(vsphere, "_nic_backing", lambda net: object())
    vsphere._finish(FauxVm(), object(), body, user_data, None)
    return ecrits


def test_un_cloudinit_SANS_charge_vide_quand_meme(monkeypatch):
    """Cas limite, et le vidage y reste la bonne réponse : pas d'injection veut
    dire pas d'héritage non plus."""
    ecrits = _capturer(monkeypatch, _body(boot_mode="cloudinit", os="ubuntu"), user_data="")
    assert ecrits["guestinfo.metadata"] == ""


# ── Le motif d'interface ──────────────────────────────────────────────────────

def test_le_motif_couvre_le_nommage_CLASSIQUE(monkeypatch):
    """`en*` exclut `eth0`.

    Le nommage « prévisible » donne `ens192` ou `enp11s0`, mais une image qui
    démarre avec `net.ifnames=0` garde le `eth0` classique. Avec `en*`, le
    netplan ne matchait AUCUNE interface : cloud-init se rabattait en DHCP, et
    la machine tournait sur une adresse qui n'était pas celle de sa fiche —
    sans qu'aucun appel n'échoue. Constaté le 17/09 sur une image Debian 12.
    """
    import fnmatch
    meta = vsphere._metadata(_body(boot_mode="cloudinit", os="ubuntu"), "005056aa0042")
    # `l.strip().startswith` et non `"name:" in l` : sinon on attrape
    # `local-hostname:` qui apparait plus haut dans le document.
    motif = next(l.split(":", 1)[1].strip() for l in meta.splitlines()
                 if l.strip().startswith("name:"))
    for carte in ("eth0", "ens192", "enp11s0", "eno1"):
        assert fnmatch.fnmatch(carte, motif), f"« {motif} » ne couvre pas {carte}"


def test_le_motif_n_attrape_PAS_le_reste(monkeypatch):
    """Assez large pour l'Ethernet, pas au point de prendre la boucle locale
    ou le sans-fil — netplan refuserait une carte qu'il ne sait pas configurer."""
    import fnmatch
    meta = vsphere._metadata(_body(boot_mode="cloudinit", os="ubuntu"), "005056aa0042")
    # `l.strip().startswith` et non `"name:" in l` : sinon on attrape
    # `local-hostname:` qui apparait plus haut dans le document.
    motif = next(l.split(":", 1)[1].strip() for l in meta.splitlines()
                 if l.strip().startswith("name:"))
    for carte in ("lo", "wlan0", "wlp3s0", "docker0", "virbr0"):
        assert not fnmatch.fnmatch(carte, motif), f"« {motif} » attrape {carte}"
