# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un premier démarrage Windows coupé par un redémarrage ne reste plus muet.

Le 04/11 (et déjà le 13/10), l'installeur MSI de WithSecure, lancé en `/qn` sans
`/norestart`, a redémarré le PC en plein premier démarrage. Posé par WinPE, ce
script ne tournait qu'une fois : tout ce qui suivait a été sauté — suppression
du compte de déploiement, smoke tests, effacement du script qui porte des mots
de passe — et la fiche est restée « déployée ».

Trois parades : `/norestart` sur les MSI, reprise du script au démarrage suivant
(étapes faites sautées), et la fiche qui dit « inachevé » tant que les smoke
tests ne sont pas arrivés.
"""
from datetime import datetime, timedelta, timezone

from jinja2 import Environment, FileSystemLoader
from sqlmodel import Session

from models import DeployLogLine, Machine, engine


def _app(**k):
    champs = dict(id=0, name="", winget_id="", install_type="winget", installer_file="",
                  install_args="", installer_config_file="", detect_name="")
    champs.update(k)
    return type("A", (), champs)()


def _rendre(apps, post_script="", bitlocker=False) -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    return env.get_template("firstboot-windows.ps1.j2").render(
        machine=type("M", (), {"hostname": "X", "mac": "aabbccddeeff", "ou": "",
                               "post_script": ""})(),
        profile={
            "locale": "fr-FR", "keyboard": "fr", "timezone": "Europe/Paris",
            "join_domain": False, "domain": "", "domain_join_user": "",
            "domain_join_password": "", "enable_bitlocker": bitlocker,
            "bitlocker_pin": bitlocker, "laps_rotation_days": 0, "network_drives": "",
            "printers": "", "post_script": post_script, "wifi_ssid": "", "wifi_password": "",
            "default_user": "osiris", "machine_type": "workstation",
        },
        tv_password="", win_apps=apps, osiris_url="http://osiris", osiris_ip="10.0.0.1",
        bios_password="", forced_mac="",
    )


WS = _app(id=24, name="WithSecure", install_type="msi", installer_file="ws.msi",
          install_args="/qn VOUCHER=X LANGUAGE=fr")


# ── Le script ─────────────────────────────────────────────────────────────────

def test_un_msi_ne_peut_plus_redemarrer_le_pc_en_plein_premier_demarrage():
    assert "/qn VOUCHER=X LANGUAGE=fr /norestart')" in _rendre([WS])


def test_norestart_n_est_pas_ajoute_deux_fois():
    for args in ("/qn /norestart", "/qn REBOOT=ReallySuppress"):
        script = _rendre([_app(id=2, name="A", install_type="msi", installer_file="a.msi",
                               install_args=args)])
        assert f"{args}')" in script
        assert f"{args} /norestart" not in script


def test_un_exe_garde_ses_arguments_tels_quels():
    script = _rendre([_app(id=3, name="Office", install_type="exe", installer_file="s.exe",
                           install_args="/configure c.xml")])
    assert "-ArgumentList '/configure c.xml'" in script


def test_le_code_3010_est_une_reussite_et_un_echec_est_nomme():
    script = _rendre([WS])
    assert "3010" in script and "redemarrageRequis = $true" in script
    assert "ERREUR : WithSecure - l'installeur a echoue (code $codeInst)" in script


def test_le_script_se_relance_au_demarrage_tant_qu_il_n_est_pas_alle_au_bout():
    script = _rendre([WS])
    pose = script.index("Register-ScheduledTask -TaskName $tacheReprise")
    retire = script.index("Unregister-ScheduledTask -TaskName $tacheReprise -Confirm:$false -EA SilentlyContinue\nRemove-Item")
    # Posé tôt (avant toute installation), retiré seulement à la toute fin.
    assert pose < script.index("Installation des applications")
    assert retire > script.index("===== DEPLOIEMENT TERMINE =====")


def test_la_reprise_ne_boucle_pas_indefiniment():
    script = _rendre([WS])
    assert "$tentativesMax = 3" in script
    assert "if ($tentative -gt $tentativesMax)" in script


def test_ni_laps_ni_bitlocker_ne_sont_refaits_a_la_reprise():
    """Les refaire changerait un mot de passe ou un PIN déjà remis à OSIRIS."""
    script = _rendre([], bitlocker=True)
    assert 'if (Test-EtapeFaite "laps")' in script
    assert 'if (Test-EtapeFaite "bitlocker")' in script
    # Le témoin n'est posé qu'APRÈS la remise à OSIRIS.
    assert script.index("Mot de passe LAPS sauvegarde dans OSIRIS") < script.index('Set-EtapeFaite "laps"')
    assert script.index("PIN et cle de recuperation sauvegardes") < script.index('Set-EtapeFaite "bitlocker"')


def test_un_installeur_deja_passe_n_est_pas_relance():
    script = _rendre([WS])
    assert 'Join-Path $dossierEtapes "app-24-lance"' in script
    assert script.index('Set-EtapeFaite "app-24-lance"') < script.index("msiexec.exe")


def test_un_script_post_install_coupe_n_est_pas_rejoue():
    script = _rendre([], post_script="Write-Log 'x'")
    assert script.index('Set-EtapeFaite "post-profil"') < script.index("Write-Log 'x'")


# ── La fiche ──────────────────────────────────────────────────────────────────

def _machine(mac, smoke_status, lignes):
    with Session(engine) as s:
        s.add(Machine(mac=mac, hostname=f"PC-{mac[-2:]}", client="c", os="windows",
                      status="deployed", password_hash="$6$x", smoke_status=smoke_status,
                      deployed_at=datetime.now(timezone.utc) - timedelta(days=9)))
        for ligne in lignes:
            s.add(DeployLogLine(mac=mac, run=1, line=ligne))
        s.commit()


def test_la_liste_dit_ou_s_est_arrete_un_premier_demarrage(client, admin_token, clean_db):
    _machine("aabbccddee01", "", ["[15:23] Office : installe", "[15:24] Installation de WithSecure en cours"])
    _machine("aabbccddee02", "ok", ["[10:00] ===== DEPLOIEMENT TERMINE ====="])
    r = client.get("/machines", headers={"Authorization": f"Bearer {admin_token}"})
    par_mac = {m["mac"]: m for m in r.json()}
    assert par_mac["aabbccddee01"]["derniere_ligne"] == "[15:24] Installation de WithSecure en cours"
    # Allée au bout : rien à signaler, et pas de requête inutile.
    assert par_mac["aabbccddee02"]["derniere_ligne"] is None
