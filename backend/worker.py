# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""
Worker ARQ — exécuté dans un processus séparé.
Lance avec : arq worker.WorkerSettings
"""
import asyncio
import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import aiohttp
from arq.connections import RedisSettings
from dotenv import load_dotenv
from sqlmodel import Session, select, delete

load_dotenv()

from models import DriverPack, OsImage, engine, normalize_model  # noqa: E402

OSIRIS_BASE_URL = os.environ.get("OSIRIS_BASE_URL", "http://10.0.0.1")
OSIRIS_IP       = os.environ.get("OSIRIS_IP", "10.0.0.1")

# Pilotes reseau supplementaires pour WinPE (arborescence : <path>/net/<pilote>/*.inf).
#
# Ils ne sont PLUS bakes dans boot.wim. Historique : bakes a la main le 2026-07-16,
# puis reinjectes automatiquement le 2026-07-21 — et le 2026-07-22 on a constate que
# le WIM ainsi produit ne demarre plus (le poste telecharge tout puis revient au
# Startup Menu, sur ZBook Firefly G8), alors qu'il passe 'wimlib verify' et garde son
# Boot Index. Le seul ecart avec un WIM sain etait le dossier racine \drivers\, et
# wimboot patche justement le repertoire du WIM pour y injecter ses fichiers.
#
# Desormais c'est wimboot qui les livre : tout fichier 'initrd' supplementaire est
# depose dans \Windows\System32\ de l'image demarree, sans modifier boot.wim (voir
# _winpe_driver_initrd_lines dans main.py). startnet.cmd fait ensuite le drvload.
# Pour ajouter un pilote : le deposer dans WINPE_DRIVERS_PATH/net/<nom>/ (INF+SYS+CAT),
# il est servi au prochain boot PXE — plus aucune regeneration de WIM necessaire.
WINPE_DRIVERS_PATH = os.environ.get("WINPE_DRIVERS_PATH", "/srv/data/windows/winpe-drivers")


def _make_startnet_cmd() -> bytes:
    """Génère startnet.cmd.

    Flux :
      1. wpeinit + attente réseau
      2. Monte Y: (SMB) — toujours nécessaire pour l'image Windows
      3. Copie Y:\curl.exe vers X:\ pour pouvoir faire des appels HTTP
      4. Appelle /winpe-auto → script personnalisé par machine (lookup IP→MAC)
      5. Fallback : Y:\osiris-deploy.cmd (script générique sans unattend.xml)
    """
    lines = [
        "@echo off",
        "",
        "REM -- Chargement des pilotes reseau supplementaires",
        "REM WinPE ne dispose que des pilotes *inbox* de l'ISO Windows. Sur les",
        "REM machines dont la carte n'est pas reconnue (Realtek, Intel recentes...),",
        "REM il n'y a AUCUN reseau => blocage total. On ne peut pas aller chercher le",
        "REM pilote sur le partage : il faut le reseau pour ca (oeuf et poule).",
        "REM",
        "REM Les pilotes sont livres par wimboot, qui injecte les fichiers passes en",
        "REM 'initrd' supplementaires dans \\Windows\\System32\\ de l'image demarree.",
        "REM On ne touche donc PLUS au boot.wim : l'y avoir ajoute un dossier racine",
        "REM \\drivers\\ (2026-07-22) produisait un WIM que wimboot ne demarrait plus.",
        "REM WinPE n'a qu'un seul .inf d'origine ici (wdscapture.inf) : balayer le",
        "REM dossier est donc sans risque, un drvload qui echoue est silencieux.",
        "echo [OSIRIS] Chargement des pilotes reseau...",
        "for %%i in (X:\\Windows\\System32\\*.inf) do drvload \"%%i\" >nul 2>&1",
        "REM Repli : anciens boot.wim ou les pilotes avaient ete bakes sous \\drivers\\net",
        "if exist X:\\drivers\\net (",
        "    for /r X:\\drivers\\net %%i in (*.inf) do drvload \"%%i\" >nul 2>&1",
        ")",
        "wpeinit",
        "echo [OSIRIS] Reseau en cours d'initialisation...",
        "set NETTRY=0",
        ":check_net",
        f"ping -n 1 {OSIRIS_IP} >nul 2>&1",
        "if not errorlevel 1 goto net_ok",
        "set /a NETTRY+=1",
        "if %NETTRY% lss 30 (",
        f"    echo [OSIRIS] OSIRIS ({OSIRIS_IP}) injoignable - tentative %NETTRY%/30...",
        "    ping -n 3 127.0.0.1 >nul",
        "    goto check_net",
        ")",
        "echo.",
        f"echo [OSIRIS] ERREUR: impossible de joindre OSIRIS ({OSIRIS_IP}) apres 30 tentatives.",
        "echo [OSIRIS] --- Diagnostic reseau ---",
        "ipconfig /all",
        "echo.",
        "echo [OSIRIS] Si AUCUNE carte reseau n'apparait ci-dessus, son pilote manque",
        "echo [OSIRIS] dans WinPE. Sinon, verifiez le VLAN / le cable / le DHCP.",
        "pause",
        "exit /b 1",
        ":net_ok",
        # ~5s pour laisser le client SMB se stabiliser (timeout non dispo en WinPE)
        "ping -n 6 127.0.0.1 >nul",
        "",
        "REM -- Montage du partage SMB (necessaire pour l'image Windows)",
        "REM Retry : un montage peut echouer (error 53) si la pile reseau n'est pas",
        "REM prete ou si une session zombie cote serveur n'est pas encore nettoyee.",
        "echo [OSIRIS] Connexion au partage SMB...",
        "set SMBTRY=0",
        ":smb_retry",
        "net use Y: /delete /y >nul 2>&1",
        f"net use Y: \\\\{OSIRIS_IP}\\windows /user:guest \"\"",
        "if not errorlevel 1 goto smb_ok",
        "set /a SMBTRY+=1",
        "if %SMBTRY% lss 8 (",
        "    echo [OSIRIS] Montage SMB echoue - nouvelle tentative %SMBTRY%/8...",
        "    ping -n 6 127.0.0.1 >nul",
        "    goto smb_retry",
        ")",
        "echo [OSIRIS] ERREUR: impossible de monter le partage SMB apres 8 tentatives !",
        "pause",
        "exit /b 1",
        ":smb_ok",
        "",
        "REM -- curl.exe depuis le partage pour identifier la machine via HTTP",
        "if exist Y:\\curl.exe copy Y:\\curl.exe X:\\curl.exe >nul",
        "",
        "REM -- Numero de serie : identite STABLE de la machine, independante de la",
        "REM carte reseau. Indispensable avec les adaptateurs USB-Ethernet : la MAC",
        "REM vue au PXE (firmware, option 'MAC Address Pass Through') peut differer",
        "REM de celle vue ici (pilote Windows = MAC gravee de l'adaptateur), et un",
        "REM meme adaptateur sert a deployer plusieurs machines.",
        "REM ATTENTION : findstr.exe N'EXISTE PAS dans ce WinPE (verifie sur l'image :",
        "REM 0 occurrence sur 26666 fichiers) - on utilise find.exe, bien present.",
        "REM On passe par un fichier : wmic sort de l'UTF-16 et laisse un retour chariot",
        "REM parasite ; le pipe normalise l'encodage et 'for /f' sur un FICHIER supprime",
        "REM proprement les CRLF - sinon le CR finirait dans l'URL et casserait curl.",
        "REM Lecture best-effort : si elle echoue, OSSERIAL reste vide et OSIRIS retombe",
        "REM sur le lookup IP->MAC. Cette etape ne doit JAMAIS bloquer le deploiement.",
        "set OSSERIAL=",
        "wmic bios get serialnumber /value 2>nul | find \"SerialNumber=\" > X:\\osiris-sn.txt 2>nul",
        "if exist X:\\osiris-sn.txt for /f \"usebackq tokens=2 delims==\" %%s in (\"X:\\osiris-sn.txt\") do if not defined OSSERIAL set OSSERIAL=%%s",
        "del X:\\osiris-sn.txt >nul 2>&1",
        "REM Retrait des espaces finaux. Boucle SANS '&' : en batch, 'if cond cmd & goto'",
        "REM execute le goto INCONDITIONNELLEMENT (le & decoupe au niveau superieur),",
        "REM ce qui produisait une boucle infinie.",
        ":trimsn",
        "if not defined OSSERIAL goto snready",
        "if not \"%OSSERIAL:~-1%\"==\" \" goto snready",
        "set OSSERIAL=%OSSERIAL:~0,-1%",
        "goto trimsn",
        ":snready",
        "if not defined OSSERIAL echo [OSIRIS] Numero de serie illisible - repli sur l'identification par MAC",
        "if defined OSSERIAL echo [OSIRIS] Numero de serie : %OSSERIAL%",
        "",
        "REM -- Identification de la machine (script personnalise par machine)",
        "REM Le serial prime cote serveur ; a defaut OSIRIS retombe sur le lookup IP->MAC.",
        "echo [OSIRIS] Identification de la machine...",
        f"X:\\curl.exe -sf --connect-timeout 15 -o X:\\osiris-machine.cmd \"{OSIRIS_BASE_URL}/winpe-auto?serial=%OSSERIAL%\" 2>nul",
        "if not errorlevel 1 (",
        "    echo [OSIRIS] Script personnalise recu - lancement...",
        "    call X:\\osiris-machine.cmd",
        "    goto end",
        ")",
        "",
        "REM -- Fallback : script generique",
        "echo [OSIRIS] Machine inconnue ou curl absent - fallback script generique...",
        "if not exist Y:\\osiris-deploy.cmd (",
        "    echo [OSIRIS] ERREUR: osiris-deploy.cmd absent du partage !",
        "    pause",
        "    exit /b 1",
        ")",
        "call Y:\\osiris-deploy.cmd",
        "",
        ":end",
        "pause",
    ]
    return "\r\n".join(lines).encode("utf-8")


async def _run(cmd: list[str], error_prefix: str):
    """Lance une commande, lève RuntimeError si elle échoue."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{error_prefix}: {err.decode()[:300]}")


async def _process_ubuntu(iso_path: str, nfs_path: str, static_dir: str, _update):
    """Extrait une ISO Ubuntu vers NFS + vmlinuz/initrd vers static/."""
    _update(status="extracting", progress=0)
    os.makedirs(nfs_path, exist_ok=True)
    os.makedirs(static_dir, exist_ok=True)

    await _run(
        ["/usr/bin/xorriso", "-osirrox", "on", "-indev", iso_path, "-extract", "/", nfs_path],
        "xorriso NFS",
    )
    for src, dst in [
        ("/casper/vmlinuz", f"{static_dir}/vmlinuz"),
        ("/casper/initrd",  f"{static_dir}/initrd"),
    ]:
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/xorriso", "-osirrox", "on", "-indev", iso_path, "-extract", src, dst,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()


async def _7z_extract(iso_path: str, iso_src: str, out_dir: str, label: str):
    """Extrait un fichier d'une ISO Windows (UDF) avec 7z."""
    # 7z e extrait le fichier sans son chemin dans out_dir
    await _run(
        ["/usr/bin/7z", "e", iso_path, iso_src, f"-o{out_dir}", "-y"],
        f"7z {label}",
    )


async def _process_windows(iso_path: str, _update, wim_name: str = ""):
    """
    Extrait les fichiers WinPE de l'ISO (UDF), injecte notre startnet.cmd,
    et copie install.wim vers /srv/data/windows/.

    wim_name : nom du .wim cible sur le partage (ex. "server2022.wim"). Vide =>
    "install.wim" (comportement historique). Permet de faire coexister plusieurs
    images Windows (client / Server) sur le meme partage sans ecrasement.
    """
    winpe_dir   = "static/winpe"
    windows_dir = "/srv/data/windows"
    boot_wim    = "/tmp/osiris_boot.wim"
    startnet    = "/tmp/osiris_startnet.cmd"

    os.makedirs(f"{winpe_dir}/boot",    exist_ok=True)
    os.makedirs(f"{winpe_dir}/sources", exist_ok=True)
    os.makedirs(windows_dir,            exist_ok=True)

    _update(status="extracting", progress=10)

    # ── 1. Fichiers de boot WinPE ────────────────────────────────────────────
    # 7z e extrait le nom de fichier seul (sans le chemin) dans le dossier cible
    for iso_src, out_dir in [
        ("bootmgr",          f"{winpe_dir}/"),
        ("bootmgr.efi",      f"{winpe_dir}/"),
        ("boot/bcd",         f"{winpe_dir}/boot/"),
        ("boot/boot.sdi",    f"{winpe_dir}/boot/"),
        ("sources/boot.wim", "/tmp/"),
    ]:
        await _7z_extract(iso_path, iso_src, out_dir, iso_src)

    # 7z a déposé boot.wim dans /tmp/boot.wim — on le renomme
    os.replace("/tmp/boot.wim", boot_wim)

    _update(progress=30)

    # ── 2. Injection de startnet.cmd + winpeshl.ini dans WinPE ──────────────
    # On utilise l'index 2 ("Windows Setup") qui a un env plus riche (findstr, etc.)
    # winpeshl.ini court-circuite setup.exe et appelle notre startnet.cmd
    await _run(
        ["/usr/bin/wimlib-imagex", "info", boot_wim, "2", "--boot"],
        "wimlib set boot index to 2",
    )
    winpeshl = "/tmp/osiris_winpeshl.ini"
    with open(winpeshl, "w") as f:
        f.write("[LaunchApps]\r\n%SYSTEMROOT%\\System32\\cmd.exe,/c %SYSTEMROOT%\\System32\\startnet.cmd\r\n")

    with open(startnet, "wb") as f:
        f.write(_make_startnet_cmd())

    await _run(
        ["/usr/bin/wimlib-imagex", "update", boot_wim, "2",
         "--command", f"add {startnet} /Windows/System32/startnet.cmd"],
        "wimlib inject startnet.cmd into index 2",
    )
    await _run(
        ["/usr/bin/wimlib-imagex", "update", boot_wim, "2",
         "--command", f"add {winpeshl} /Windows/System32/winpeshl.ini"],
        "wimlib inject winpeshl.ini into index 2",
    )
    os.unlink(startnet)
    os.unlink(winpeshl)

    # NOTE : on n'injecte PLUS les pilotes reseau dans boot.wim. Ils sont livres
    # au demarrage par wimboot (cf. _winpe_driver_initrd_lines dans main.py), qui
    # les depose dans \Windows\System32\ sans toucher au WIM. Y ajouter un dossier
    # racine \drivers\ produisait un WIM que wimboot ne demarrait plus.

    os.replace(boot_wim, f"{winpe_dir}/sources/boot.wim")

    _update(progress=50)

    # ── 3. Extraction de install.wim (ou install.esd) ────────────────────────
    # IMPORTANT : 7z ecrit TOUJOURS le nom d'origine (install.wim). Extraire
    # directement dans windows_dir ecraserait un WIM deja en place portant ce nom
    # (typiquement l'image client) AVANT meme le renommage vers wim_name.
    # On passe donc par un dossier de staging, et on ne deplace vers le partage
    # qu'une fois le nom final connu : seul ce nom-la peut etre ecrase.
    staging_dir = os.path.join(windows_dir, ".osiris-staging")
    shutil.rmtree(staging_dir, ignore_errors=True)
    os.makedirs(staging_dir, exist_ok=True)

    extracted = False
    try:
        for iso_src in ["sources/install.wim", "sources/install.esd"]:
            filename = iso_src.split("/")[-1]
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/7z", "e", iso_path, iso_src, f"-o{staging_dir}", "-y",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            src = os.path.join(staging_dir, filename)
            if proc.returncode == 0 and os.path.exists(src):
                # Nom final : wim_name si demande, sinon le nom d'origine.
                # On garde l'extension d'origine (.wim/.esd) si wim_name n'en precise pas.
                if wim_name:
                    target = wim_name if wim_name.lower().endswith((".wim", ".esd")) \
                        else f"{wim_name}.{filename.rsplit('.', 1)[-1]}"
                else:
                    target = filename
                os.replace(src, os.path.join(windows_dir, target))
                extracted = True
                break
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    if not extracted:
        raise RuntimeError("Impossible de trouver install.wim / install.esd dans l'ISO")

    # ── 4. Écriture de osiris-deploy.cmd sur le partage Samba ────────────────
    # Script de SECOURS, appele par startnet.cmd uniquement quand OSIRIS n'a PAS
    # reconnu la machine.
    #
    # Il ne deploie DELIBEREMENT rien. Historiquement il appliquait install.wim
    # index 1 : une machine mal identifiee repartait donc avec une image arbitraire,
    # sans unattend (OOBE manuelle), sans pilotes constructeur et sans firstboot
    # (ni domaine, ni BitLocker, ni LAPS) - un poste inutilisable, disque ecrase,
    # et AUCUN avertissement. Une erreur d'identification ne doit pas couter un
    # deploiement complet : on refuse et on affiche de quoi corriger.
    deploy_script = "\r\n".join([
        "@echo off",
        "setlocal enabledelayedexpansion",
        "echo.",
        "echo ============================================================",
        "echo   [OSIRIS] MACHINE NON RECONNUE - DEPLOIEMENT ANNULE",
        "echo ============================================================",
        "echo.",
        "echo Aucune configuration ne correspond a cette machine dans OSIRIS.",
        "echo Le disque n'a PAS ete modifie.",
        "echo.",
        "echo --- Identifiants detectes sur cette machine ---",
        "set SN=",
        "for /f \"skip=1 delims=\" %%s in ('wmic bios get serialnumber 2^>nul') do if not defined SN set SN=%%s",
        "if defined SN for /f \"tokens=* delims= \" %%a in (\"!SN!\") do set SN=%%a",
        "echo   Numero de serie : !SN!",
        "echo   Adresses MAC    :",
        "getmac /nh /fo table",
        "echo.",
        "echo --- Causes frequentes ---",
        "echo   * la machine n'est pas enregistree dans OSIRIS",
        "echo   * le numero de serie enregistre ne correspond pas a celui ci-dessus",
        "echo   * carte reseau USB : la MAC vue au PXE differe de celle vue ici",
        "echo     (option BIOS HP 'MAC Address Pass Through')",
        "echo.",
        "echo Enregistrez la machine dans OSIRIS avec l'un des identifiants",
        "echo ci-dessus, puis redemarrez en PXE.",
        "echo.",
        "pause",
        "exit /b 1",
    ]) + "\r\n"
    with open(f"{windows_dir}/osiris-deploy.cmd", "w") as f:
        f.write(deploy_script)


async def download_iso(ctx, image_id: int):
    """Télécharge une ISO et la traite selon l'OS (Ubuntu ou Windows)."""

    with Session(engine) as session:
        image = session.get(OsImage, image_id)
        if not image:
            return
        iso_url  = image.iso_url
        os_name  = image.os
        version  = image.version
        wim_name = image.wim_name
        nfs_path = image.nfs_path or f"/srv/nfs/{os_name}-{version}"
        image.status   = "downloading"
        image.progress = 0
        image.nfs_path = nfs_path
        session.add(image)
        session.commit()

    iso_path   = f"/tmp/osiris_{os_name}_{version}.iso"
    static_dir = f"static/{os_name}-{version}"

    def _update(status=None, progress=None, error=None):
        with Session(engine) as s:
            img = s.get(OsImage, image_id)
            if status   is not None: img.status   = status
            if progress is not None: img.progress = progress
            if error    is not None: img.error    = error[:500]
            s.add(img)
            s.commit()

    # Si l'URL est un chemin local (file://...), on l'utilise directement
    local_file = iso_url.startswith("file://")
    if local_file:
        iso_path = iso_url[7:]  # strip "file://"

    try:
        # ── Téléchargement (seulement si URL distante) ────────────────────────
        if not local_file:
            async with aiohttp.ClientSession() as http:
                async with http.get(iso_url) as resp:
                    resp.raise_for_status()
                    total         = int(resp.headers.get("content-length", 0))
                    downloaded    = 0
                    last_reported = -1
                    with open(iso_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(4 * 1024 * 1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            pct = int(downloaded / total * 100) if total else 0
                            if pct != last_reported and pct % 2 == 0:
                                last_reported = pct
                                _update(progress=pct)
        else:
            _update(progress=100)  # Fichier déjà présent

        # ── Traitement selon l'OS ─────────────────────────────────────────────
        if os_name == "ubuntu":
            await _process_ubuntu(iso_path, nfs_path, static_dir, _update)
        elif os_name == "windows":
            await _process_windows(iso_path, _update, wim_name=wim_name)

        if not local_file:
            os.unlink(iso_path)
        _update(status="ready", progress=100)

    except Exception as exc:
        _update(status="failed", error=str(exc))
        if not local_file and os.path.exists(iso_path):
            os.unlink(iso_path)


# ── Catalogue de drivers Dell ───────────────────────────────────────────────

DELL_CATALOG_URL  = "https://downloads.dell.com/catalog/DriverPackCatalog.cab"
DELL_BASE_URL     = "https://downloads.dell.com/"
DELL_TARGET_OS    = {"Windows10", "Windows11"}
DRIVERS_BASE_PATH = "/srv/data/windows/drivers"

# Dossiers pseudo-racines produits par innoextract : ils correspondent aux
# constantes Inno Setup ({app}, {tmp}, {code:GetExtractPath}...) et non a une
# vraie arborescence de pilotes. On remonte leur contenu d'un cran pour obtenir
# la meme forme que les packs Dell/HP : <model_key>/Audio/, /Chipset/, /Network/...
_INNO_PSEUDO_DIRS = {"app", "tmp"}


def _is_inno_setup(path: str) -> bool:
    """Detecte un installeur Inno Setup (cas de TOUS les packs Lenovo).

    7z n'a aucun handler Inno : il ouvre le .exe comme un simple binaire PE et
    en ressort les ressources ([0], CERTIFICATE...) sans jamais toucher au
    payload. Le pack parait extrait alors qu'il ne contient aucun pilote.
    """
    with open(path, "rb") as f:
        head = f.read(512 * 1024)
    return b"Inno Setup" in head


def _move_merge(src: str, dst: str):
    """Deplace src vers dst en fusionnant les dossiers deja presents.

    shutil.move() seul ne suffit pas : si dst existe deja, il deposerait src
    *a l'interieur* (dest/Audio/Audio) au lieu de fusionner les deux.
    """
    if not os.path.exists(dst):
        shutil.move(src, dst)
    elif os.path.isdir(src) and os.path.isdir(dst):
        for child in os.listdir(src):
            _move_merge(os.path.join(src, child), os.path.join(dst, child))
        os.rmdir(src)
    else:
        os.replace(src, dst)


def _flatten_inno_output(staging_dir: str, dest_dir: str):
    """Deplace le contenu de staging_dir vers dest_dir en sautant les pseudo-racines."""
    os.makedirs(dest_dir, exist_ok=True)
    for entry in os.listdir(staging_dir):
        src = os.path.join(staging_dir, entry)
        # "code$GetExtractPath$" (constante {code:...}), "app", "tmp" : on remonte
        # leur contenu. Tout le reste est deplace tel quel.
        if os.path.isdir(src) and ("$" in entry or entry in _INNO_PSEUDO_DIRS):
            for child in os.listdir(src):
                _move_merge(os.path.join(src, child), os.path.join(dest_dir, child))
        else:
            _move_merge(src, os.path.join(dest_dir, entry))


def _count_inf(path: str) -> int:
    """Compte les .inf d'une arborescence — un pack sans .inf n'installe rien."""
    total = 0
    for _, _, files in os.walk(path):
        total += sum(1 for f in files if f.lower().endswith(".inf"))
    return total


async def _extract_driver_archive(archive_path: str, dest_dir: str, label: str):
    """Extrait un pack de pilotes vers dest_dir, en choisissant l'outil selon le format."""
    if _is_inno_setup(archive_path):
        staging_dir = f"{archive_path}.d"
        shutil.rmtree(staging_dir, ignore_errors=True)
        os.makedirs(staging_dir, exist_ok=True)
        try:
            await _run(
                ["/usr/bin/innoextract", "-e", "-s", "--collisions=overwrite",
                 "-d", staging_dir, archive_path],
                f"innoextract {label}",
            )
            _flatten_inno_output(staging_dir, dest_dir)
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
    else:
        os.makedirs(dest_dir, exist_ok=True)
        await _run(
            ["/usr/bin/7z", "x", archive_path, f"-o{dest_dir}", "-y"],
            f"7z {label}",
        )


async def sync_dell_catalog(ctx):
    """
    Télécharge le catalogue Dell (fichier CAB ~300 KB), l'extrait, parse le XML,
    et remplit la table driver_pack avec les métadonnées de chaque pack.

    Analogie : on recopie le sommaire du catalogue bibliothèque dans notre système —
    on n'emprunte aucun livre, on note juste où ils sont et ce qu'ils contiennent.
    """
    cab_path    = "/tmp/dell_catalog.cab"
    extract_dir = "/tmp/dell_catalog_xml"

    # ── 1. Télécharger le catalogue ──────────────────────────────────────────
    async with aiohttp.ClientSession() as http:
        async with http.get(DELL_CATALOG_URL) as resp:
            resp.raise_for_status()
            with open(cab_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(512 * 1024):
                    f.write(chunk)

    # ── 2. Extraire le XML depuis le CAB ─────────────────────────────────────
    os.makedirs(extract_dir, exist_ok=True)
    await _run(["/usr/bin/7z", "e", cab_path, f"-o{extract_dir}", "-y"], "7z dell catalog")

    # ── 3. Parser le XML ─────────────────────────────────────────────────────
    # Namespace du fichier Dell
    ns   = {"d": "openmanage/cm/dm"}
    tree = ET.parse(os.path.join(extract_dir, "DriverPackCatalog.xml"))
    root = tree.getroot()
    base = root.get("baseLocation", "downloads.dell.com")

    packs: list[DriverPack] = []

    for pkg in root.findall("d:DriverPackage", ns):
        path     = pkg.get("path", "")
        size_mb  = int(pkg.get("size", 0)) // 1024 // 1024

        # Ne garder que les packs x64 Windows 10/11
        # (on ignore Vista, XP, Win7, Win8, WinPE...)
        os_codes: set[str] = set()
        for os_el in pkg.findall(".//d:OperatingSystem", ns):
            code = os_el.get("osCode", "")
            arch = os_el.get("osArch", "x64")
            if code in DELL_TARGET_OS and arch in ("x64", ""):
                os_codes.add(code)

        if not os_codes:
            continue

        # Windows11 > Windows10 si les deux sont présents
        os_code = "Windows11" if "Windows11" in os_codes else "Windows10"
        url     = f"https://{base}/{path}"

        # Un DriverPackage peut supporter plusieurs modèles → une entrée par modèle
        # On stocke des dicts (pas des objets SQLModel) pour éviter les problèmes
        # de détachement si un objet était ajouté à une session précédente.
        for brand in pkg.findall(".//d:Brand", ns):
            for model_el in brand.findall("d:Model", ns):
                model_name = model_el.get("name", "").strip()
                if not model_name:
                    continue
                packs.append({
                    "vendor":       "dell",
                    "model":        model_name,
                    "model_key":    normalize_model(model_name),
                    "os_code":      os_code,
                    "download_url": url,
                    "size_mb":      size_mb,
                })

    # ── 4. Upsert : mettre à jour les fiches existantes, insérer les nouvelles ──
    # On ne supprime PAS les entrées existantes pour préserver status/local_path
    # des packs déjà téléchargés (status=ready). On met juste à jour les métadonnées.
    with Session(engine) as session:
        for p in packs:
            existing = session.exec(
                select(DriverPack).where(
                    DriverPack.vendor    == p["vendor"],
                    DriverPack.model_key == p["model_key"],
                    DriverPack.os_code   == p["os_code"],
                )
            ).first()
            if existing:
                existing.model           = p["model"]
                existing.download_url    = p["download_url"]
                existing.size_mb         = p["size_mb"]
                existing.catalog_updated = datetime.now(timezone.utc)
                # status et local_path intentionnellement préservés
                session.add(existing)
            else:
                session.add(DriverPack(**p))
        # Supprimer les entrées dont l'URL n'existe plus dans le catalogue
        new_urls = {p["download_url"] for p in packs}
        for orphan in session.exec(select(DriverPack).where(DriverPack.vendor == "dell")).all():
            if orphan.download_url not in new_urls:
                session.delete(orphan)
        session.commit()

    # ── Nettoyage ─────────────────────────────────────────────────────────────
    os.unlink(cab_path)
    shutil.rmtree(extract_dir, ignore_errors=True)

    return {"synced": len(packs)}


async def download_driver_pack(ctx, pack_id: int):
    """
    Télécharge et extrait le pack de drivers d'un modèle précis
    dans le dossier Samba /srv/data/windows/drivers/<vendor>/<model_key>/.

    Le format varie selon le constructeur : CAB auto-extractible chez Dell et HP,
    installeur Inno Setup chez Lenovo. _extract_driver_archive choisit l'outil.

    Analogie : on emprunte enfin le livre et on le range dans notre étagère locale,
    prêt à être consulté par WinPE pendant les déploiements.
    """
    with Session(engine) as session:
        pack = session.get(DriverPack, pack_id)
        if not pack:
            return {"error": "pack introuvable"}
        pack.status = "downloading"
        session.add(pack)
        session.commit()
        pack_id_      = pack.id
        download_url  = pack.download_url
        vendor        = pack.vendor
        model_key     = pack.model_key

    dest_dir     = os.path.join(DRIVERS_BASE_PATH, vendor, model_key)
    staging_dest = f"{dest_dir}.new"   # voisin de dest_dir => rename atomique
    archive_path = f"/tmp/osiris_drivers_{pack_id_}.bin"   # CAB (Dell/HP) ou EXE (Lenovo)

    def _set_status(status: str, local_path: str = "", error: str = ""):
        with Session(engine) as s:
            p = s.get(DriverPack, pack_id_)
            p.status = status
            p.error  = error[:300]
            if local_path:
                p.local_path = local_path
            s.add(p)
            s.commit()

    try:
        # ── 1. Télécharger l'archive (peut être 1-3 GB, patience) ────────────
        async with aiohttp.ClientSession() as http:
            async with http.get(download_url) as resp:
                resp.raise_for_status()
                with open(archive_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(4 * 1024 * 1024):
                        f.write(chunk)

        # ── 2. Extraire dans un dossier voisin, jamais directement dans dest ──
        # Un re-telechargement ne doit pas pouvoir casser un pack qui marche :
        # on extrait a cote, on valide, et on ne permute qu'a la fin. Si quoi que
        # ce soit echoue en route, l'ancien pack reste intact et utilisable.
        shutil.rmtree(staging_dest, ignore_errors=True)
        await _extract_driver_archive(archive_path, staging_dest, f"driver pack {pack_id_}")

        # ── 3. Valider : un pack sans .inf n'installe aucun pilote ───────────
        # Sans ce garde-fou, un pack vide passe "ready", le deploiement se
        # deroule normalement et la machine arrive sans reseau ni chipset.
        inf_count = _count_inf(staging_dest)
        if inf_count == 0:
            raise RuntimeError(
                "extraction sans aucun fichier .inf — pack inutilisable"
            )

        # ── 4. Permuter : rename sur le meme filesystem, donc atomique ────────
        shutil.rmtree(dest_dir, ignore_errors=True)
        os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
        os.rename(staging_dest, dest_dir)

        os.unlink(archive_path)
        _set_status("ready", local_path=dest_dir)
        return {"status": "ready", "path": dest_dir, "inf_count": inf_count}

    except Exception as exc:
        if os.path.exists(archive_path):
            os.unlink(archive_path)
        shutil.rmtree(f"{archive_path}.d", ignore_errors=True)
        shutil.rmtree(staging_dest, ignore_errors=True)
        _set_status("error", error=str(exc))
        return {"error": str(exc)[:300]}


HP_CATALOG_URL  = "https://ftp.hp.com/pub/caps-softpaq/cmit/HPClientDriverPackCatalog.cab"


async def sync_hp_catalog(ctx):
    """
    Télécharge le catalogue HP, parse les SoftPaq de type 'Driver Pack',
    extrait le modèle et l'OS depuis le champ Name.
    Ex: "HP EliteBook x360 830 G8 Windows 10 Driver Pack" → model + Windows10
    """
    import re
    cab_path    = "/tmp/hp_catalog.cab"
    extract_dir = "/tmp/hp_catalog_xml"

    async with aiohttp.ClientSession() as http:
        async with http.get(HP_CATALOG_URL) as resp:
            resp.raise_for_status()
            with open(cab_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(512 * 1024):
                    f.write(chunk)

    os.makedirs(extract_dir, exist_ok=True)
    await _run(["/usr/bin/7z", "e", cab_path, f"-o{extract_dir}", "-y"], "7z hp catalog")

    xml_path = os.path.join(extract_dir, "HPClientDriverPackCatalog.xml")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    catalog  = root.find("HPClientDriverPackCatalog")
    softpaqs = catalog.find("SoftPaqList") if catalog is not None else None

    packs: list[dict] = []
    os_re     = re.compile(r"[Ww]in(?:dows)?\s*(10|11)", re.IGNORECASE)
    suffix_re = re.compile(r"\s+[Ww]in(?:dows)?.*$", re.IGNORECASE)

    for sp in (softpaqs or []):
        if sp.findtext("Category", "") != "Manageability - Driver Pack":
            continue
        name = sp.findtext("Name", "").strip()
        url  = sp.findtext("Url",  "").strip()
        size = int(sp.findtext("Size", "0"))
        if not name or not url:
            continue
        m = os_re.search(name)
        if not m:
            continue
        os_code = f"Windows{m.group(1)}"
        model = name
        if model.upper().startswith("HP "):
            model = model[3:]
        model = suffix_re.sub("", model).strip()
        packs.append({
            "vendor":       "hp",
            "model":        model,
            "model_key":    normalize_model(model),
            "os_code":      os_code,
            "download_url": url,
            "size_mb":      size // 1024 // 1024,
        })

    with Session(engine) as session:
        new_urls = set()
        for p in packs:
            new_urls.add(p["download_url"])
            existing = session.exec(
                select(DriverPack).where(
                    DriverPack.vendor    == p["vendor"],
                    DriverPack.model_key == p["model_key"],
                    DriverPack.os_code   == p["os_code"],
                )
            ).first()
            if existing:
                existing.model           = p["model"]
                existing.download_url    = p["download_url"]
                existing.size_mb         = p["size_mb"]
                existing.catalog_updated = datetime.now(timezone.utc)
                session.add(existing)
            else:
                session.add(DriverPack(**p))
        for orphan in session.exec(select(DriverPack).where(DriverPack.vendor == "hp")).all():
            if orphan.download_url not in new_urls:
                session.delete(orphan)
        session.commit()

    os.unlink(cab_path)
    shutil.rmtree(extract_dir, ignore_errors=True)
    return {"synced": len(packs)}


LENOVO_CATALOG_URL = "https://download.lenovo.com/cdrt/td/catalogv2.xml"


async def sync_lenovo_catalog(ctx):
    """
    Télécharge le catalogue Lenovo (XML ~5 MB), parse les entrées
    et remplit la table driver_pack avec les packs Lenovo.
    """
    xml_path = "/tmp/lenovo_catalog.xml"

    async with aiohttp.ClientSession() as http:
        async with http.get(LENOVO_CATALOG_URL) as resp:
            resp.raise_for_status()
            with open(xml_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(512 * 1024):
                    f.write(chunk)

    tree = ET.parse(xml_path)
    root = tree.getroot()

    packs: list[dict] = []

    for model_el in root.findall(".//Model"):
        model_name = model_el.get("name", "").strip()
        if not model_name:
            continue
        for pack_el in model_el.findall(".//SCCM"):
            os_attr  = pack_el.get("os", "")
            os_code  = "Windows11" if "11" in os_attr else "Windows10" if "10" in os_attr else None
            if not os_code:
                continue
            url = pack_el.text.strip() if pack_el.text else ""
            if not url.startswith("http"):
                continue
            packs.append({
                "vendor":       "lenovo",
                "model":        model_name,
                "model_key":    normalize_model(model_name),
                "os_code":      os_code,
                "download_url": url,
                "size_mb":      0,
            })

    with Session(engine) as session:
        new_urls = set()
        for p in packs:
            new_urls.add(p["download_url"])
            existing = session.exec(
                select(DriverPack).where(
                    DriverPack.vendor    == p["vendor"],
                    DriverPack.model_key == p["model_key"],
                    DriverPack.os_code   == p["os_code"],
                )
            ).first()
            if existing:
                existing.model           = p["model"]
                existing.download_url    = p["download_url"]
                existing.catalog_updated = datetime.now(timezone.utc)
                session.add(existing)
            else:
                session.add(DriverPack(**p))
        for orphan in session.exec(select(DriverPack).where(DriverPack.vendor == "lenovo")).all():
            if orphan.download_url not in new_urls:
                session.delete(orphan)
        session.commit()

    os.unlink(xml_path)
    return {"synced": len(packs)}


class WorkerSettings:
    functions      = [download_iso, sync_dell_catalog, download_driver_pack,
                      sync_hp_catalog, sync_lenovo_catalog]
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379"))
