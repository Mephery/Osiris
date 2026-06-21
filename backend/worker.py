"""
Worker ARQ — exécuté dans un processus séparé.
Lance avec : arq worker.WorkerSettings
"""
import asyncio
import os

import aiohttp
from arq.connections import RedisSettings
from dotenv import load_dotenv
from sqlmodel import Session

load_dotenv()

from models import OsImage, engine  # noqa: E402 (import après load_dotenv)

OSIRIS_BASE_URL = os.environ.get("OSIRIS_BASE_URL", "http://10.0.0.1")
OSIRIS_IP       = os.environ.get("OSIRIS_IP", "10.0.0.1")


def _make_startnet_cmd() -> bytes:
    """Génère startnet.cmd — net use est le seul transport réseau dispo dans ce WinPE minimal."""
    lines = [
        "@echo off",
        "wpeinit",
        "echo [OSIRIS] Reseau en cours d'initialisation...",
        ":check_net",
        f"ping -n 1 {OSIRIS_IP} >nul 2>&1",
        "if errorlevel 1 (",
        "    timeout /t 2 /nobreak >nul",
        "    goto check_net",
        ")",
        # Délai pour laisser le client SMB de WinPE s'initialiser après wpeinit
        "timeout /t 5 /nobreak >nul",
        "echo [OSIRIS] Connexion au partage OSIRIS (SMB)...",
        f"net use Y: \\\\{OSIRIS_IP}\\windows /user:guest \"\"",
        "if errorlevel 1 (",
        "    echo [OSIRIS] ERREUR: impossible de monter le partage SMB !",
        "    pause",
        "    exit /b 1",
        ")",
        "if not exist Y:\\osiris-deploy.cmd (",
        "    echo [OSIRIS] ERREUR: osiris-deploy.cmd absent du partage !",
        "    pause",
        "    exit /b 1",
        ")",
        "echo [OSIRIS] Lancement du deploiement...",
        "call Y:\\osiris-deploy.cmd",
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


async def _process_windows(iso_path: str, _update):
    """
    Extrait les fichiers WinPE de l'ISO (UDF), injecte notre startnet.cmd,
    et copie install.wim vers /srv/data/windows/.
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
    os.replace(boot_wim, f"{winpe_dir}/sources/boot.wim")

    _update(progress=50)

    # ── 3. Extraction de install.wim (ou install.esd) ────────────────────────
    extracted = False
    for iso_src in ["sources/install.wim", "sources/install.esd"]:
        filename = iso_src.split("/")[-1]
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/7z", "e", iso_path, iso_src, f"-o{windows_dir}", "-y",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        if proc.returncode == 0 and os.path.exists(f"{windows_dir}/{filename}"):
            extracted = True
            break

    if not extracted:
        raise RuntimeError("Impossible de trouver install.wim / install.esd dans l'ISO")

    # ── 4. Écriture de osiris-deploy.cmd sur le partage Samba ────────────────
    # Ce script sera appelé par startnet.cmd via net use Y: \\OSIRIS\windows
    deploy_script = "\r\n".join([
        "@echo off",
        "echo [OSIRIS] ===== Deploiement Windows 11 =====",
        "",
        "echo [OSIRIS] Partitionnement du disque (GPT/UEFI)...",
        "(",
        "echo select disk 0",
        "echo clean",
        "echo convert gpt",
        "echo create partition efi size=512",
        "echo format quick fs=fat32 label=System",
        "echo assign letter=S",
        "echo create partition msr size=16",
        "echo create partition primary",
        "echo format quick fs=ntfs label=Windows",
        "echo assign letter=C",
        ") > X:\\diskpart.txt",
        "diskpart /s X:\\diskpart.txt",
        "if errorlevel 1 ( echo [OSIRIS] ERREUR diskpart & pause & exit /b 1 )",
        "",
        "echo [OSIRIS] Application de l'image Windows (15-30 min, patience)...",
        "if exist Y:\\install.wim (",
        "    dism /Apply-Image /ImageFile:Y:\\install.wim /Index:1 /ApplyDir:C:\\",
        ") else (",
        "    dism /Apply-Image /ImageFile:Y:\\install.esd /Index:1 /ApplyDir:C:\\",
        ")",
        "if errorlevel 1 ( echo [OSIRIS] ERREUR DISM & pause & exit /b 1 )",
        "",
        "echo [OSIRIS] Configuration du demarrage UEFI...",
        "bcdboot C:\\Windows /l fr-FR /s S: /f UEFI",
        "",
        "echo [OSIRIS] ===== Installation terminee ! Redemarrage dans 10s =====",
        "timeout /t 10 /nobreak >nul",
        "wpeutil reboot",
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
            await _process_windows(iso_path, _update)

        if not local_file:
            os.unlink(iso_path)
        _update(status="ready", progress=100)

    except Exception as exc:
        _update(status="failed", error=str(exc))
        if not local_file and os.path.exists(iso_path):
            os.unlink(iso_path)


class WorkerSettings:
    functions      = [download_iso]
    redis_settings = RedisSettings()
