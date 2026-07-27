# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Résolution du domaine AD quand un profil est lié à une DomainConfig.

Footgun corrigé : une DomainConfig liée fournit des valeurs (domaine, WiFi, et
éventuellement un compte de jonction centralisé), mais elle ne doit PAS écraser
le compte de jonction du profil quand elle n'en définit pas — sinon la jonction
partait avec des credentials vides. Le compte de jonction est un couple
user + password : soit celui de la DomainConfig (si elle en a un), soit celui du profil.
"""
import main
from sqlmodel import Session

from crypto import encrypt
from models import engine, DomainConfig, Profile


def _profile(**kw):
    with Session(engine) as s:
        p = Profile(name="P", os="windows", join_domain=True, **kw)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


def _domain_config(**kw):
    with Session(engine) as s:
        dc = DomainConfig(organization_id=1, name="DC", **kw)
        s.add(dc)
        s.commit()
        s.refresh(dc)
        return dc


def test_domain_config_sans_compte_conserve_celui_du_profil(clean_db):
    """Le cas du footgun : DomainConfig pour le domaine + WiFi seulement, compte sur le profil."""
    dc = _domain_config(domain="midi2i.com", join_user="", join_password="",
                        wifi_ssid="WNHC", wifi_password=encrypt("wpa-secret"))
    p = _profile(domain="ancien.local", domain_join_user="midi2i.com\\svc_join",
                 domain_join_password=encrypt("p@ss"), domain_config_id=dc.id)

    with Session(engine) as s:
        ctx = main._profile_for_template(s.get(Profile, p.id), s)

    # le domaine et le WiFi viennent de la DomainConfig...
    assert ctx["domain"] == "midi2i.com"
    assert ctx["wifi_ssid"] == "WNHC"
    assert ctx["wifi_password"] == "wpa-secret"
    # ...mais le compte de jonction du profil est PRÉSERVÉ (le footgun l'effaçait)
    assert ctx["domain_join_user"] == "midi2i.com\\svc_join"
    assert ctx["domain_join_password"] == "p@ss"


def test_domain_config_avec_compte_prend_le_dessus(clean_db):
    """Compte centralisé dans la DomainConfig : il prime sur celui du profil, en couple complet."""
    dc = _domain_config(domain="corp.local", join_user="corp\\joiner",
                        join_password=encrypt("dc-pass"))
    p = _profile(domain="ancien.local", domain_join_user="profil\\user",
                 domain_join_password=encrypt("profil-pass"), domain_config_id=dc.id)

    with Session(engine) as s:
        ctx = main._profile_for_template(s.get(Profile, p.id), s)

    assert ctx["domain"] == "corp.local"
    assert ctx["domain_join_user"] == "corp\\joiner"
    assert ctx["domain_join_password"] == "dc-pass"


def test_sans_domain_config_utilise_les_champs_inline(clean_db):
    """Sans DomainConfig liée, on utilise les champs inline du profil."""
    p = _profile(domain="inline.local", domain_join_user="inline\\user",
                 domain_join_password=encrypt("inline-pass"))

    with Session(engine) as s:
        ctx = main._profile_for_template(s.get(Profile, p.id), s)

    assert ctx["domain"] == "inline.local"
    assert ctx["domain_join_user"] == "inline\\user"
    assert ctx["domain_join_password"] == "inline-pass"
