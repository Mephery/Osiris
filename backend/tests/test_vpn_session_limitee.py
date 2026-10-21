# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Sessions VPN à durée limitée.

Le besoin d'origine : un tunnel restait connecté des mois d'affilée avec le compte
nominatif d'une personne sur le pare-feu du client — ce qui, vu de l'admin du
pare-feu, ressemble trait pour trait à un compte volé. Une session s'ouvre
désormais pour une durée choisie et se referme seule : à l'échéance (plafond dur),
ou quand l'organisation ne déploie plus rien.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import Session, select

import main
import vpn
from crypto import encrypt
from models import AuditLog, DeployLogLine, Machine, Organization, Profile, VpnTunnel, engine

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
INACTIF = timedelta(minutes=30)


def _maintenant():
    return datetime.now(timezone.utc)


# ── La règle de fermeture ──────────────────────────────────────────────────────

def test_l_echeance_ferme_meme_en_plein_deploiement():
    """Plafond DUR : c'est la garantie donnée à l'admin du pare-feu."""
    t = _maintenant()
    assert vpn.raison_de_fermer(t, t - timedelta(hours=4), t - timedelta(seconds=1),
                                t - timedelta(seconds=5), True, INACTIF) == "expiree"


def test_une_session_ouverte_sans_aucun_deploiement_se_ferme_apres_le_delai():
    t = _maintenant()
    assert vpn.raison_de_fermer(t, t - timedelta(minutes=31), t + timedelta(hours=3),
                                None, False, INACTIF) == "inactif"
    assert vpn.raison_de_fermer(t, t - timedelta(minutes=29), t + timedelta(hours=3),
                                None, False, INACTIF) is None


def test_une_activite_recente_garde_la_session_ouverte():
    t = _maintenant()
    assert vpn.raison_de_fermer(t, t - timedelta(hours=2), t + timedelta(hours=2),
                                t - timedelta(minutes=10), False, INACTIF) is None


def test_une_machine_qui_vient_de_demarrer_en_pxe_suspend_l_inactivite():
    """Statut deploying mais journal encore vide : WinPE est en train de charger."""
    t = _maintenant()
    assert vpn.raison_de_fermer(t, t - timedelta(hours=1), t + timedelta(hours=3),
                                None, True, INACTIF) is None


def test_journal_en_utc_naif_et_colonnes_avisees_se_comparent():
    """DeployLogLine.timestamp est naïf-UTC, vpn_tunnel.* est TIMESTAMPTZ."""
    t = _maintenant()
    ligne_naive = (t - timedelta(minutes=5)).replace(tzinfo=None)
    assert vpn.raison_de_fermer(t, t - timedelta(hours=1), t + timedelta(hours=1),
                                ligne_naive, False, INACTIF) is None


# ── La configuration OpenVPN et le script root ──────────────────────────────────

def test_la_conf_annonce_sa_deconnexion_au_pare_feu():
    conf = vpn.render_ovpn_config("client\nremote vpn.example 1194 udp\n", "", "acme")
    assert conf.count("explicit-exit-notify") == 1


def test_explicit_exit_notify_deja_present_n_est_pas_double():
    conf = vpn.render_ovpn_config("client\nexplicit-exit-notify 3\n", "", "acme")
    assert conf.count("explicit-exit-notify") == 1


def test_le_script_d_application_ne_rend_plus_le_tunnel_permanent():
    """`enable` = remonté à chaque démarrage, pour toujours : l'erreur d'origine."""
    script = (DEPLOY / "osiris-vpn-apply.sh").read_text()
    assert "enable --now" not in script
    assert "osiris-vpn-session.sh" in script


def test_le_sudoers_autorise_le_script_de_session():
    assert "/usr/local/sbin/osiris-vpn-session.sh" in (DEPLOY / "osiris-vpn.sudoers").read_text()


# ── API et surveillance ────────────────────────────────────────────────────────

@pytest.fixture
def systeme(monkeypatch):
    """Remplace tous les appels systemd/sudo : les tests ne touchent jamais un vrai tunnel."""
    etat = {"status": "active", "fermes": [], "rearmes": [], "appliques": []}
    monkeypatch.setattr(vpn, "tunnel_status", lambda slug: etat["status"])
    monkeypatch.setattr(vpn, "close_tunnel", lambda slug: etat["fermes"].append(slug))
    monkeypatch.setattr(vpn, "rearm_expiry", lambda slug, duree: etat["rearmes"].append((slug, duree)))
    monkeypatch.setattr(vpn, "apply_tunnel",
                        lambda session, tunnel, totp_code=None, duree=None: etat["appliques"].append(duree))
    return etat


@pytest.fixture
def tunnel(clean_db):
    with Session(engine, expire_on_commit=False) as session:
        org = Organization(name="Acme", slug="acme")
        session.add(org)
        session.commit()
        t = VpnTunnel(organization_id=org.id, name="Tunnel Acme", slug="acme",
                      ovpn_config=encrypt("client\n"), status="active")
        session.add(t)
        session.commit()
        return t


def _maj(tunnel_id, **champs):
    with Session(engine) as session:
        t = session.get(VpnTunnel, tunnel_id)
        for k, v in champs.items():
            setattr(t, k, v)
        session.add(t)
        session.commit()


def _relire(tunnel_id) -> VpnTunnel:
    with Session(engine, expire_on_commit=False) as session:
        return session.get(VpnTunnel, tunnel_id)


def _machine_de(org_id, status="deployed", run=1) -> Machine:
    with Session(engine, expire_on_commit=False) as session:
        m = Machine(mac="aabbccddee01", hostname="PC-ACME", client="Acme", os="windows",
                    organization_id=org_id, status=status, deploy_log_run=run)
        session.add(m)
        session.commit()
        return m


def test_ouvrir_pose_l_echeance_choisie(client, admin_headers, tunnel, systeme):
    avant = _maintenant()
    r = client.post(f"/vpn-tunnels/{tunnel.id}/apply", json={"duree_heures": 2}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert systeme["appliques"] == [timedelta(hours=2)]
    t = _relire(tunnel.id)
    echeance = vpn._utc(t.expires_at)
    assert avant + timedelta(hours=2) <= echeance <= _maintenant() + timedelta(hours=2)
    assert t.closed_at is None and t.close_reason == ""


def test_une_duree_hors_choix_est_refusee(client, admin_headers, tunnel, systeme):
    r = client.post(f"/vpn-tunnels/{tunnel.id}/apply", json={"duree_heures": 72}, headers=admin_headers)
    assert r.status_code == 400
    assert systeme["appliques"] == []


def test_fermer_a_la_main(client, admin_headers, tunnel, systeme):
    r = client.post(f"/vpn-tunnels/{tunnel.id}/close", headers=admin_headers)
    assert r.status_code == 200
    assert systeme["fermes"] == ["acme"]
    assert _relire(tunnel.id).close_reason == "manuel"


def test_prolonger_est_plafonne(client, admin_headers, tunnel, systeme):
    _maj(tunnel.id, expires_at=_maintenant() + timedelta(hours=11, minutes=30))
    r = client.post(f"/vpn-tunnels/{tunnel.id}/extend", json={"heures": 4}, headers=admin_headers)
    assert r.status_code == 200
    (_, duree), = systeme["rearmes"]
    assert duree <= vpn.DUREE_MAX


def test_prolonger_un_tunnel_ferme_est_refuse(client, admin_headers, tunnel, systeme):
    systeme["status"] = "inactive"
    r = client.post(f"/vpn-tunnels/{tunnel.id}/extend", json={"heures": 1}, headers=admin_headers)
    assert r.status_code == 409


def test_surveillance_ferme_une_session_inactive_et_le_consigne(tunnel, systeme):
    _maj(tunnel.id, last_applied_at=_maintenant() - timedelta(minutes=45),
         expires_at=_maintenant() + timedelta(hours=3))
    main._tour_tunnels_vpn()
    assert systeme["fermes"] == ["acme"]
    assert _relire(tunnel.id).close_reason == "inactif"
    with Session(engine) as session:
        assert session.exec(select(AuditLog).where(AuditLog.action == "vpn_ferme_auto")).first()


def test_surveillance_laisse_ouvert_pendant_un_deploiement(tunnel, systeme):
    _maj(tunnel.id, last_applied_at=_maintenant() - timedelta(hours=2),
         expires_at=_maintenant() + timedelta(hours=2))
    m = _machine_de(tunnel.organization_id, status="deploying")
    with Session(engine) as session:
        session.add(DeployLogLine(mac=m.mac, run=1, line="[..] Application du WIM",
                                  timestamp=(_maintenant() - timedelta(minutes=8)).replace(tzinfo=None)))
        session.commit()
    main._tour_tunnels_vpn()
    assert systeme["fermes"] == []


def test_une_machine_d_une_autre_organisation_ne_compte_pas(tunnel, systeme):
    _maj(tunnel.id, last_applied_at=_maintenant() - timedelta(hours=2),
         expires_at=_maintenant() + timedelta(hours=2))
    _machine_de(None, status="deploying")
    main._tour_tunnels_vpn()
    assert systeme["fermes"] == ["acme"]


def test_une_session_ouverte_sans_echeance_en_recoit_une(tunnel, systeme):
    """Ouverte avant les sessions limitées, ou à la main : pas de session sans fin."""
    _maj(tunnel.id, last_applied_at=_maintenant(), expires_at=None)
    main._tour_tunnels_vpn()
    assert systeme["rearmes"] == [("acme", vpn.DUREE_PAR_DEFAUT)]
    assert _relire(tunnel.id).expires_at is not None


def test_fermeture_par_la_minuterie_est_constatee(tunnel, systeme):
    """La minuterie systemd a fermé pendant qu'OSIRIS ne regardait pas."""
    systeme["status"] = "inactive"
    _maj(tunnel.id, last_applied_at=_maintenant() - timedelta(hours=4),
         expires_at=_maintenant() - timedelta(seconds=30))
    main._tour_tunnels_vpn()
    t = _relire(tunnel.id)
    assert (t.status, t.close_reason) == ("inactive", "expiree")
    assert systeme["fermes"] == []


def test_un_deploiement_lance_tunnel_ferme_le_dit_dans_son_journal(tunnel):
    _maj(tunnel.id, status="inactive")
    with Session(engine, expire_on_commit=False) as session:
        profil = Profile(name="Windows Acme", os="windows", join_domain=True)
        session.add(profil)
        session.commit()
        m = Machine(mac="aabbccddee02", hostname="PC-ACME2", client="Acme", os="windows",
                    organization_id=tunnel.organization_id, profile_id=profil.id)
        session.add(m)
        session.commit()
        main._signaler_tunnel_ferme(session, m)
        session.commit()
        lignes = session.exec(select(DeployLogLine).where(DeployLogLine.mac == m.mac)).all()
    assert len(lignes) == 1 and "Tunnel Acme" in lignes[0].line
