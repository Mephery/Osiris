# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Vérifier le certificat de l'hyperviseur contre SON autorité.

OSIRIS joignait ses hyperviseurs sans vérifier leur certificat : le jeton d'API,
qui peut détruire des VM, circulait sur une session que rien n'authentifiait.
Personne n'avait activé la vérification parce qu'elle échouait — aucun magasin
public ne connaît l'autorité d'un cluster Proxmox.

Or cette autorité EXISTE : le cluster la crée à son installation et signe déjà un
certificat par nœud. Il ne manquait qu'un endroit pour la déclarer. D'où trois
états, un seul interrupteur, et des messages qui nomment la bonne cause — les deux
échecs possibles ont des correctifs opposés.
"""
import ssl

import pytest
from sqlmodel import Session

import main
from models import Hypervisor, engine

# Autorité autosignée RÉELLE, générée une fois avec `cryptography` puis figée ici.
# Un PEM écrit à la main ne se charge pas — et c'est précisément le chargement
# qu'on veut exercer. CN « PVE Cluster Test CA », expire en 2036.
CA_PEM = """-----BEGIN CERTIFICATE-----
MIIBTzCB96ADAgECAhQCAFrFiIaz7Y6zpXOkk+rqYZw8TjAKBggqhkjOPQQDAjAe
MRwwGgYDVQQDDBNQVkUgQ2x1c3RlciBUZXN0IENBMB4XDTI2MDgxMjAwMDAwMFoX
DTM2MDgxMjAwMDAwMFowHjEcMBoGA1UEAwwTUFZFIENsdXN0ZXIgVGVzdCBDQTBZ
MBMGByqGSM49AgEGCCqGSM49AwEHA0IABIxHupTpbFlFfyf6HyW91Xx3ZKikjell
8luNBXeIX7auZhqPWDSHeCQVdJD2iTQHpSpOz5zWahKpOx27lj0w3cqjEzARMA8G
A1UdEwEB/wQFMAMBAf8wCgYIKoZIzj0EAwIDRwAwRAIgau6wZAIGMJMwVlLuKc4C
soVZs9td/UbTLv20uSzwVGkCIHFK3HY3ObeQW0kex1MILB0SUABfhXdy7W+lgY/V
nBCf
-----END CERTIFICATE-----"""


def _hv(**o) -> Hypervisor:
    base = dict(name="pve", type="proxmox", url="https://pve.test:8006",
                token_id="osiris@pve!osiris", token_secret="")
    base.update(o)
    return Hypervisor(**base)


# ── Les trois états du contexte SSL ───────────────────────────────────────────

def test_sans_verification_on_ne_verifie_rien():
    """L'état historique, conservé : c'est lui qui garde un retour arrière à un clic."""
    assert main._contexte_ssl(_hv(tls_verify=False, ca_cert=CA_PEM)) is False


def test_verification_sans_autorite_utilise_le_magasin_systeme():
    ctx = main._contexte_ssl(_hv(tls_verify=True, ca_cert=""))

    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_une_autorite_declaree_est_la_seule_reconnue():
    """Restreindre à cet hyperviseur vaut mieux que de l'installer sur tout le
    système : OSIRIS n'a aucune raison de faire confiance à cette autorité ailleurs."""
    ctx = main._contexte_ssl(_hv(tls_verify=True, ca_cert=CA_PEM))

    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    sujets = [c["subject"] for c in ctx.get_ca_certs()]
    assert any("PVE Cluster Test CA" in str(s) for s in sujets), sujets
    assert len(ctx.get_ca_certs()) == 1, "aucune autre autorité ne doit être acceptée"


def test_la_desactivation_est_journalisee(caplog, monkeypatch):
    """Une vérification désactivée en silence est une décision que personne ne
    se rappelle avoir prise."""
    monkeypatch.setattr(main, "_tls_avertis", {})

    with caplog.at_level("WARNING", logger="osiris.hypervisor"):
        main._contexte_ssl(_hv(id=1, tls_verify=False))

    assert any("SANS vérification" in r.getMessage() for r in caplog.records)


# ── Le PEM invalide : refusé tôt, pas au prochain appel ───────────────────────

def test_un_pem_illisible_est_refuse_a_l_enregistrement(client, admin_headers):
    """Sans ce contrôle, un copier-coller tronqué s'enregistre sans broncher et ne
    se manifeste qu'au prochain appel, sous une erreur de bibliothèque."""
    resp = client.post("/hypervisors", headers=admin_headers, json={
        "name": "pve", "url": "https://pve.test:8006",
        "token_id": "osiris@pve!osiris", "token_secret": "s3cret",
        "ca_cert": "-----BEGIN CERTIFICATE-----\ntronque\n-----END CERTIFICATE-----",
    })

    assert resp.status_code == 400, resp.text
    assert "pve-root-ca.pem" in resp.json()["detail"], "le message doit dire QUOI coller"


def test_une_autorite_valide_est_acceptee_et_resumee(client, admin_headers):
    """La fiche ne renvoie pas le PEM : trente lignes de base64 ne disent pas si
    l'on a collé le bon fichier, « l'autorité et sa date d'expiration » si."""
    resp = client.post("/hypervisors", headers=admin_headers, json={
        "name": "pve", "url": "https://pve.test:8006",
        "token_id": "osiris@pve!osiris", "token_secret": "s3cret", "ca_cert": CA_PEM,
    })

    assert resp.status_code in (200, 201), resp.text
    d = resp.json()
    assert d["ca_present"] is True
    assert "PVE Cluster Test CA" in d["ca_resume"]["autorite"]
    assert d["ca_resume"]["expire_le"].startswith("2036")
    assert "BEGIN CERTIFICATE" not in resp.text, "le PEM n'a pas à être renvoyé"


def test_une_autorite_vide_revient_au_magasin_systeme(client, admin_headers):
    hv = client.post("/hypervisors", headers=admin_headers, json={
        "name": "pve", "url": "https://pve.test:8006",
        "token_id": "x", "token_secret": "y", "ca_cert": CA_PEM}).json()

    resp = client.patch(f"/hypervisors/{hv['id']}", headers=admin_headers,
                        json={"ca_cert": ""})

    assert resp.status_code == 200, resp.text
    assert resp.json()["ca_present"] is False


# ── Les messages : deux échecs, deux correctifs opposés ───────────────────────

def test_un_nom_qui_ne_correspond_pas_est_nomme_comme_tel():
    """Certificat valide mais qui ne couvre pas l'adresse appelée : le correctif est
    de changer l'URL ou de régénérer le certificat — pas de toucher à l'autorité."""
    exc = Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                    "IP address mismatch, certificate is not valid for '172.29.12.10'")

    msg = main._diagnostic_tls(_hv(name="cluster"), exc)

    assert "ne couvre" in msg and "PAS l'adresse" in msg
    assert "régénérer" in msg
    assert "pve-root-ca" not in msg, "ce n'est PAS un problème d'autorité"


def test_une_autorite_qui_ne_signe_pas_est_nommee_comme_telle():
    exc = Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                    "unable to get local issuer certificate")

    msg = main._diagnostic_tls(_hv(name="cluster"), exc)

    assert "autorité" in msg and "pve-root-ca.pem" in msg
    assert "adresse" not in msg, "ce n'est PAS un problème de nom d'hôte"


def test_une_panne_reseau_reste_une_panne_reseau():
    """Ne pas transformer un câble débranché en problème de certificat."""
    msg = main._diagnostic_tls(_hv(name="cluster"), Exception("Cannot connect to host"))

    assert "Impossible de joindre Proxmox" in msg
    assert "autorité" not in msg


# ── Le résumé ────────────────────────────────────────────────────────────────

def test_le_resume_dune_autorite_absente_est_vide():
    assert main._resume_autorite("") == {}
    assert main._resume_autorite(None) == {}


def test_le_resume_signale_un_certificat_illisible():
    """Cas d'une fiche remplie avant ce contrôle : l'interface doit le dire."""
    r = main._resume_autorite("pas un certificat")

    assert "erreur" in r and "illisible" in r["erreur"]
