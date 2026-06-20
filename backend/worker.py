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


async def download_iso(ctx, image_id: int):
    """Télécharge une ISO, l'extrait vers NFS et copie vmlinuz/initrd dans static/."""

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

    try:
        # ── 1. Téléchargement ────────────────────────────────────────────────
        async with aiohttp.ClientSession() as http:
            async with http.get(iso_url) as resp:
                resp.raise_for_status()
                total        = int(resp.headers.get("content-length", 0))
                downloaded   = 0
                last_reported = -1
                with open(iso_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(4 * 1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        pct = int(downloaded / total * 100) if total else 0
                        if pct != last_reported and pct % 2 == 0:
                            last_reported = pct
                            _update(progress=pct)

        # ── 2. Extraction vers NFS ───────────────────────────────────────────
        _update(status="extracting", progress=0)
        os.makedirs(nfs_path, exist_ok=True)
        os.makedirs(static_dir, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "xorriso", "-osirrox", "on", "-indev", iso_path, "-extract", "/", nfs_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"xorriso NFS: {err.decode()[:300]}")

        # ── 3. Extraction vmlinuz + initrd vers static/ ──────────────────────
        for src, dst in [
            ("/casper/vmlinuz", f"{static_dir}/vmlinuz"),
            ("/casper/initrd",  f"{static_dir}/initrd"),
        ]:
            proc = await asyncio.create_subprocess_exec(
                "xorriso", "-osirrox", "on", "-indev", iso_path,
                "-extract", src, dst,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()

        os.unlink(iso_path)
        _update(status="ready", progress=100)

    except Exception as exc:
        _update(status="failed", error=str(exc))
        if os.path.exists(iso_path):
            os.unlink(iso_path)


class WorkerSettings:
    functions     = [download_iso]
    redis_settings = RedisSettings()
