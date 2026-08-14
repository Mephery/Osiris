# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""
Pilotage d'un vCenter VMware, via l'API SOAP vSphere (pyvmomi).

Pourquoi pyvmomi et pas l'API REST : l'API REST moderne (`/api/vcenter/...`)
n'existe qu'à partir de vSphere 7, et **ne sait pas cloner une VM** avant
vSphere 8. pyvmomi couvre le clonage depuis toujours et parle à toutes les
versions, de la 6.0 à la 8.x — un seul chemin de code, qui survivra à une
montée de version du vCenter.

Correspondance de vocabulaire avec l'UI, qui est celle de Proxmox :

    nœud     -> cluster de calcul
    stockage -> datastore
    réseau   -> port group (standard ou distribué)
    template -> VM marquée `template`

⚠️ Les identifiants vSphere sont des chaînes (« vm-1234 »), là où Proxmox
utilise des entiers. Pour ne pas propager deux types dans tout OSIRIS, on
n'expose QUE la partie numérique et on reconstruit « vm-N » au moment de
parler au vCenter (cf. `_vm_moref`).

pyvmomi est synchrone : chaque appel bloquant part dans un thread pour ne pas
figer la boucle asyncio de l'API.
"""
import asyncio
import base64
import logging
import secrets
import ssl
from typing import Any, Optional

from fastapi import HTTPException
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim, vmodl

from crypto import decrypt
from models import Hypervisor

_log = logging.getLogger("osiris.vsphere")

# Une session vCenter reste valide tant qu'on l'utilise. On la garde par
# hyperviseur : la création d'une VM enchaîne une dizaine d'appels, et
# rouvrir une session à chaque fois coûte une seconde à chaque fois.
_sessions: dict[int, Any] = {}


def _contexte_ssl(h: Hypervisor):
    """Même politique que côté Proxmox : `tls_verify` décide, `ca_cert` dit contre quoi.

    pyvmomi attend un contexte SSL, ou `None` pour son défaut — on lui en donne
    toujours un explicite, pour que le comportement se lise ici et pas dans la
    bibliothèque.
    """
    if not h.tls_verify:
        _log.warning(
            "vCenter « %s » joint SANS vérification du certificat : les identifiants "
            "du compte de service circulent sur une session interceptable.", h.name)
        return ssl._create_unverified_context()
    pem = (getattr(h, "ca_cert", "") or "").strip()
    if not pem:
        return ssl.create_default_context()
    try:
        return ssl.create_default_context(cadata=pem)
    except ssl.SSLError as e:
        raise HTTPException(status_code=502, detail=(
            f"Le certificat d'autorité de « {h.name} » est illisible ({e}) — recoller "
            f"le PEM complet, en-têtes BEGIN/END compris."))


def _host(h: Hypervisor) -> str:
    return h.url.replace("https://", "").replace("http://", "").rstrip("/").split("/")[0]


def _connect(h: Hypervisor):
    """Ouvre (ou réutilise) une session vCenter. Bloquant — à appeler via _run()."""
    si = _sessions.get(h.id)
    if si is not None:
        try:
            si.content.sessionManager.currentSession   # ping applicatif
            return si
        except Exception:
            _sessions.pop(h.id, None)                  # session expirée

    user = (h.token_id or "").strip()
    password = decrypt(h.token_secret or "")
    if not user or not password:
        raise HTTPException(
            status_code=502,
            detail="Identifiants vCenter absents ou non déchiffrables — renseigner "
                   "le compte de service (ex. osiris@vsphere.local) et son mot de passe",
        )
    ctx = _contexte_ssl(h)
    try:
        si = SmartConnect(host=_host(h), user=user, pwd=password, sslContext=ctx)
    except vim.fault.InvalidLogin:
        raise HTTPException(status_code=502, detail="vCenter : identifiants refusés")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Impossible de joindre le vCenter : {e}")
    _sessions[h.id] = si
    return si


async def _run(fn, *args, **kwargs):
    """Exécute un appel pyvmomi bloquant hors de la boucle asyncio."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def _all(si, kind) -> list:
    """Tous les objets d'un type dans l'inventaire."""
    content = si.content
    view = content.viewManager.CreateContainerView(content.rootFolder, [kind], True)
    try:
        return list(view.view)
    finally:
        view.Destroy()


def _vm_moref(vm_id: int) -> str:
    """Reconstruit l'identifiant vSphere à partir de la partie numérique."""
    return f"vm-{vm_id}"


def _moid_number(obj) -> int:
    """Partie numérique d'un moref (« vm-1234 » -> 1234), 0 si illisible."""
    raw = obj._moId.rsplit("-", 1)[-1]
    return int(raw) if raw.isdigit() else 0


def _find_vm(si, vm_id: int):
    moref = _vm_moref(vm_id)
    for vm in _all(si, vim.VirtualMachine):
        if vm._moId == moref:
            return vm
    return None


def _cluster(si, name: str):
    for c in _all(si, vim.ClusterComputeResource):
        if c.name == name or c._moId == name:
            return c
    raise HTTPException(status_code=404, detail=f"Cluster vSphere introuvable : {name}")


def _wait(task):
    """Attend une tâche vSphere et lève l'erreur métier si elle échoue."""
    while task.info.state in (vim.TaskInfo.State.running, vim.TaskInfo.State.queued):
        import time
        time.sleep(2)
    if task.info.state != vim.TaskInfo.State.success:
        msg = getattr(task.info.error, "msg", None) or str(task.info.error)
        raise HTTPException(status_code=502, detail=f"vCenter : {msg}")
    return task.info.result


def _vm_folder(si, template):
    """
    Dossier d'accueil des VM créées : la racine « VM et modèles » du datacenter.

    Surtout PAS `template.parent` : les templates vivent dans un dossier dédié,
    et y déposer les VM de production le transforme en fourre-tout où l'on ne
    distingue plus les modèles des machines réelles.
    """
    node = template.parent
    while node is not None and not isinstance(node, vim.Datacenter):
        node = getattr(node, "parent", None)
    return node.vmFolder if node is not None else template.parent


def _datastores(si) -> list[dict]:
    """
    Datastores de l'inventaire, dédoublonnés et au même format que les stockages
    Proxmox — l'interface affiche les deux dans le même tableau.

    `_all` rend chaque datastore UNE fois, quel que soit le nombre d'hôtes qui le
    montent : contrairement à `cluster/resources` côté Proxmox, il n'y a rien à
    replier ici. `shared` reflète tout de même le montage multi-hôtes, qui est
    l'information utile — un datastore local à un hôte ne sert pas à grand-chose
    pour une VM qu'on voudra pouvoir migrer.
    """
    out = []
    for ds in _all(si, vim.Datastore):
        s = ds.summary
        if not getattr(s, "accessible", False):
            continue
        total, libre = s.capacity or 0, s.freeSpace or 0
        out.append({
            "storage":  ds.name,
            "node":     "",
            "type":     s.type,
            "shared":   len(ds.host) > 1,
            "online":   True,
            "total_gb": round(total / 1073741824, 1),
            "avail_gb": round(libre / 1073741824, 1),
            "used_pct": round((total - libre) / total * 100, 1) if total else 0.0,
            "roles":    ["images"],
        })
    return sorted(out, key=lambda d: d["storage"])


def _cluster_usage(cluster) -> dict:
    """
    Ressources d'un cluster, dans le vocabulaire de l'UI (héritée de Proxmox).

    L'usage est agrégé depuis les hôtes (`quickStats`) et non lu sur le cluster :
    `summary.effectiveMemory` n'est PAS la mémoire libre — s'en servir affichait
    730 Go « utilisés » sur 767 pour un cluster à peine chargé.
    """
    used_mem_mb = total_mem_mb = 0
    used_mhz = total_mhz = 0
    cores = 0
    for host in cluster.host:
        hs = host.summary
        if not hs.hardware:
            continue
        cores += hs.hardware.numCpuCores or 0
        total_mem_mb += (hs.hardware.memorySize or 0) / 1048576
        total_mhz += (hs.hardware.cpuMhz or 0) * (hs.hardware.numCpuCores or 0)
        qs = hs.quickStats
        used_mem_mb += qs.overallMemoryUsage or 0
        used_mhz += qs.overallCpuUsage or 0
    return {
        "node": cluster.name,
        "status": "online",
        "cpu": round(used_mhz / total_mhz * 100, 1) if total_mhz else 0,
        "maxcpu": cores,
        "mem_gb": round(used_mem_mb / 1024, 1),
        "maxmem_gb": round(total_mem_mb / 1024, 1),
    }


def _nic_backing(network):
    """
    Rattachement d'une carte réseau à un port group.

    Un port group distribué ne se branche pas comme un port group standard :
    il faut passer par une connexion de port référençant le switch distribué.
    Namek utilise les deux, d'où le test.
    """
    if isinstance(network, vim.dvs.DistributedVirtualPortgroup):
        return vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
            port=vim.dvs.PortConnection(
                portgroupKey=network.key,
                switchUuid=network.config.distributedVirtualSwitch.uuid,
            )
        )
    return vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
        network=network, deviceName=network.name
    )


class VSphereProvider:
    """vCenter Server. Même contrat que `ProxmoxProvider`."""

    label = "VMware vCenter"

    @staticmethod
    def generate_mac() -> str:
        """
        MAC provisoire, le temps d'écrire la fiche avant le clone.

        Elle sera REMPLACÉE par celle que vCenter attribue : imposer une MAC,
        même dans la plage documentée pour l'attribution manuelle
        (00:50:56:00:00:00–00:50:56:3F:FF:FF), fait échouer l'allumage avec un
        « No host is compatible with the virtual machine » qui ne dit pas son
        nom (constaté le 2026-07-31 sur vCenter 6.7 ; la même VM démarre sans
        broncher dès qu'on laisse vCenter choisir). Toutes les VM de l'inventaire
        sont d'ailleurs en `addressType=assigned` : on s'aligne sur la plateforme.
        """
        return "005056%02x%02x%02x" % (
            secrets.randbelow(0x40), secrets.randbelow(0x100), secrets.randbelow(0x100)
        )

    @staticmethod
    async def test(h: Hypervisor) -> dict:
        def work():
            si = _connect(h)
            about = si.content.about
            return {
                "ok": True,
                "type": h.type,
                "version": about.fullName,
                "nodes": [_cluster_usage(c) for c in _all(si, vim.ClusterComputeResource)],
                "storages": _datastores(si),
            }
        return await _run(work)

    @staticmethod
    async def list_cluster_storages(h: Hypervisor) -> list[dict]:
        """Datastores du datacenter, avec leur remplissage."""
        return await _run(lambda: _datastores(_connect(h)))

    @staticmethod
    async def list_nodes(h: Hypervisor) -> list[dict]:
        def work():
            return [_cluster_usage(c) for c in _all(_connect(h), vim.ClusterComputeResource)]
        return await _run(work)

    @staticmethod
    async def list_storages(h: Hypervisor, node: str) -> list[dict]:
        def work():
            si = _connect(h)
            out = []
            for ds in _cluster(si, node).datastore:
                s = ds.summary
                if not s.accessible:
                    continue
                out.append({
                    "storage": ds.name,
                    "type": s.type,
                    "active": True,
                    "avail_gb": round(s.freeSpace / 1073741824, 1),
                    "total_gb": round(s.capacity / 1073741824, 1),
                    "content": "images",
                })
            return sorted(out, key=lambda d: -d["avail_gb"])
        return await _run(work)

    @staticmethod
    async def list_all_templates(h: Hypervisor) -> list[dict]:
        """Templates de tout le datacenter, avec le cluster qui les héberge."""
        def work():
            si = _connect(h)
            out = []
            for vm in _all(si, vim.VirtualMachine):
                if not vm.config or not vm.config.template:
                    continue
                hote = getattr(vm.runtime, "host", None)
                grappe = getattr(getattr(hote, "parent", None), "name", "") if hote else ""
                out.append({
                    "vmid":      _moid_number(vm),
                    "name":      vm.name,
                    "node":      grappe,
                    "status":    "stopped",
                    "cores":     vm.config.hardware.numCPU if vm.config.hardware else 0,
                    "maxmem_gb": round((vm.config.hardware.memoryMB or 0) / 1024, 1)
                                 if vm.config.hardware else 0,
                })
            return sorted(out, key=lambda d: d["vmid"])
        return await _run(work)

    @staticmethod
    async def list_networks(h: Hypervisor, node: str) -> list[dict]:
        def work():
            si = _connect(h)
            out = []
            for net in _cluster(si, node).network:
                distributed = isinstance(net, vim.dvs.DistributedVirtualPortgroup)
                out.append({
                    "iface": net.name,
                    "type": "dvportgroup" if distributed else "portgroup",
                    "address": "",
                    "comments": "port group distribué" if distributed else "port group standard",
                })
            return sorted(out, key=lambda n: n["iface"])
        return await _run(work)

    @staticmethod
    async def list_templates(h: Hypervisor, node: str) -> list[dict]:
        def work():
            si = _connect(h)
            out = []
            for vm in _all(si, vim.VirtualMachine):
                if not (vm.config and vm.config.template):
                    continue
                out.append({
                    "vmid": _moid_number(vm),
                    "name": vm.name,
                    "status": "template",
                    "cores": vm.config.hardware.numCPU,
                    "maxmem_gb": round(vm.config.hardware.memoryMB / 1024, 1),
                })
            return sorted(out, key=lambda t: t["name"])
        return await _run(work)

    @staticmethod
    async def next_vm_id(h: Hypervisor) -> int:
        """
        vCenter attribue lui-même l'identifiant à la création : il n'existe pas
        d'équivalent de `nextid`. On renvoie 0, et l'identifiant réel est relu
        après le clone (cf. `provision_vm`, qui le retourne).
        """
        return 0

    @staticmethod
    async def provision_vm(h: Hypervisor, body, vm_id: int, mac_colons: str,
                           mac_plain: str, user_data: str = "",
                           render_user_data=None) -> Optional[dict]:
        """
        Clone le template, injecte la configuration cloud-init et démarre la VM.
        Retourne `{"vm_id": …, "mac": …}` — les deux étant décidés par vCenter.

        Déroulé en deux temps, imposé par la plateforme : on ne peut pas choisir
        la MAC (cf. `generate_mac`), donc on clone d'abord, on relit la MAC
        attribuée, et seulement ensuite on écrit le `guestinfo` — dont le contenu
        dépend de cette MAC, puisque c'est par elle que la machine s'identifiera
        auprès d'OSIRIS. Injecter le cloud-init dès le clone graverait l'ancienne.

        Le mode PXE n'a pas de sens ici : le réseau de déploiement d'OSIRIS n'est
        pas routable jusqu'à Namek (DHCP et TFTP ne se routent pas).
        """
        if body.boot_mode != "cloudinit":
            raise HTTPException(
                status_code=400,
                detail="vSphere : seul le mode cloud-init est supporté "
                       "(le PXE d'OSIRIS ne traverse pas les tunnels).",
            )
        if not body.cloud_template_id:
            raise HTTPException(status_code=400, detail="cloud_template_id requis")

        def work():
            si = _connect(h)
            template = _find_vm(si, body.cloud_template_id)
            if template is None:
                raise HTTPException(status_code=404, detail="Template vSphere introuvable")
            cluster = _cluster(si, body.node)

            datastore = next((d for d in cluster.datastore if d.name == body.storage), None)
            if datastore is None:
                raise HTTPException(status_code=404, detail=f"Datastore introuvable : {body.storage}")
            network = next((n for n in cluster.network if n.name == body.bridge), None)
            if network is None:
                raise HTTPException(status_code=404, detail=f"Port group introuvable : {body.bridge}")

            # ── Carte réseau et disque de données : APRÈS le clone ──
            # Toucher à la carte dans la spécification de clone transmet aussi la
            # MAC du template, que vCenter recopie telle quelle : toutes les VM
            # créées se retrouveraient avec la même adresse. On clone donc sans y
            # toucher — vCenter en attribue alors une neuve — et on rebranche la
            # carte sur le bon port group juste après (cf. `_finish`).
            nic_changes = []

            config = vim.vm.ConfigSpec(
                numCPUs=body.vcpus,
                memoryMB=body.ram_mb,
                deviceChange=nic_changes,
                annotation=f"Créée par OSIRIS — {body.hostname} ({body.client})",
            )
            relocate = vim.vm.RelocateSpec(datastore=datastore, pool=cluster.resourcePool)
            clone = vim.vm.CloneSpec(location=relocate, config=config,
                                     powerOn=False, template=False)
            vm = _wait(template.CloneVM_Task(folder=_vm_folder(si, template),
                                             name=body.hostname, spec=clone))
            try:
                return _finish(vm, network, body, user_data, render_user_data)
            except Exception:
                # Le clone EXISTE : si la suite échoue, c'est à NOUS de le
                # détruire. L'appelant, lui, ne connaît pas encore l'identifiant
                # attribué par vCenter — il ne pourrait rien nettoyer, et la VM
                # resterait sur l'hyperviseur sans fiche ni trace.
                try:
                    if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
                        _wait(vm.PowerOffVM_Task())
                except Exception:
                    pass
                try:
                    _wait(vm.Destroy_Task())
                    _log.warning("VM vSphere %s détruite après échec de sa configuration",
                                 body.hostname)
                except Exception:
                    _log.exception("VM %s laissée sur le vCenter — la supprimer à la main",
                                   body.hostname)
                raise

        return await _run(work)


    @staticmethod
    async def destroy_vm(h: Hypervisor, node: str, vm_id: Any,
                         nom_attendu: str = "") -> None:
        """Suppression best-effort : ne masque jamais l'erreur d'origine.

        `nom_attendu` : même garde-fou que côté Proxmox. vCenter ne recycle pas ses
        moID comme Proxmox recycle ses VMID, donc le risque de viser une VM
        étrangère y est bien plus faible — mais « plus faible » n'est pas « nul »
        (restauration, ré-enregistrement d'inventaire), et un `Destroy_Task` ne se
        rattrape pas. On vérifie donc aussi ici.
        """
        if not vm_id:
            return

        def work():
            si = _connect(h)
            vm = _find_vm(si, int(vm_id))
            if vm is None:
                return
            if nom_attendu and (vm.name or "").strip().lower() != nom_attendu.strip().lower():
                _log.error(
                    "DESTRUCTION REFUSÉE : la VM %s s'appelle « %s » et non « %s » — "
                    "elle n'appartient pas à ce déploiement, on n'y touche pas.",
                    vm_id, vm.name, nom_attendu)
                return
            try:
                if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
                    _wait(vm.PowerOffVM_Task())
            except Exception:
                pass
            _wait(vm.Destroy_Task())
            _log.warning("VM vSphere %s détruite", vm_id)

        try:
            await _run(work)
        except Exception:
            _log.exception("Impossible de détruire la VM vSphere %s", vm_id)


def _metadata(body, mac_plain: str) -> str:
    """
    Métadonnées cloud-init (format NoCloud) injectées en `guestinfo`.

    Y compris la configuration réseau quand une adresse fixe est demandée : un
    VLAN serveur n'a généralement pas de DHCP, et une VM sans bail démarre,
    tourne, et ne rappelle jamais OSIRIS — panne silencieuse s'il en est.

    La route par défaut est écrite en `routes:` et non en `gateway4:`, déprécié
    par netplan et source d'avertissements sur Ubuntu 24.04.
    """
    meta = (f"instance-id: osiris-{mac_plain}\n"
            f"local-hostname: {body.hostname}\n")
    ip = (getattr(body, "ip_cidr", "") or "").strip()
    if not ip:
        return meta                      # pas d'adresse imposée : cloud-init fera du DHCP
    lines = [
        "network:",
        "  version: 2",
        "  ethernets:",
        "    osiris0:",
        "      match:",
        "        name: en*",             # nom d'interface imprévisible selon le matériel virtuel
        "      dhcp4: false",
        f"      addresses: [{ip}]",
    ]
    gw = (getattr(body, "gateway", "") or "").strip()
    if gw:
        lines += ["      routes:", "        - to: default", f"          via: {gw}"]
    dns = [d.strip() for d in (getattr(body, "dns_servers", "") or "").split(",") if d.strip()]
    if dns:
        lines += ["      nameservers:", f"        addresses: [{', '.join(dns)}]"]
    return meta + "\n".join(lines) + "\n"


def _finish(vm, network, body, user_data: str, render_user_data) -> dict:
    """
    Rebranche la carte, ajoute le disque de données, injecte le cloud-init et
    démarre le clone. Tout se joue ici et pas dans la spécification de clone :
    la MAC définitive n'existe qu'une fois la VM créée, et c'est elle l'identité
    de la machine pour OSIRIS — tous les rappels du premier démarrage passent
    par /firstboot-linux/<mac>.
    """
    changes = []
    for dev in vm.config.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualEthernetCard):
            dev.backing = _nic_backing(network)
            dev.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
                startConnected=True, allowGuestControl=True, connected=True)
            changes.append(vim.vm.device.VirtualDeviceSpec(
                operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=dev))
            break

    if getattr(body, "data_disk_gb", 0):
        controller = next((d for d in vm.config.hardware.device
                           if isinstance(d, vim.vm.device.VirtualSCSIController)), None)
        disks = [d for d in vm.config.hardware.device
                 if isinstance(d, vim.vm.device.VirtualDisk)]
        if controller is not None:
            # Pas de `fileName` : vCenter place le disque à côté de la VM. Le
            # renseigner à vide fait échouer le placement (« No host is
            # compatible »), sans jamais dire que c'est le disque en cause.
            backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
                diskMode="persistent", thinProvisioned=True)
            changes.append(vim.vm.device.VirtualDeviceSpec(
                operation=vim.vm.device.VirtualDeviceSpec.Operation.add,
                fileOperation=vim.vm.device.VirtualDeviceSpec.FileOperation.create,
                device=vim.vm.device.VirtualDisk(
                    capacityInKB=body.data_disk_gb * 1024 * 1024,
                    controllerKey=controller.key,
                    unitNumber=max((d.unitNumber for d in disks), default=-1) + 1,
                    key=-101, backing=backing)))

    if changes:
        _wait(vm.ReconfigVM_Task(spec=vim.vm.ConfigSpec(deviceChange=changes)))

    real_mac = next((d.macAddress for d in vm.config.hardware.device
                     if isinstance(d, vim.vm.device.VirtualEthernetCard)), "")
    real_plain = real_mac.replace(":", "").lower()

    # ── Configuration cloud-init par guestinfo ──
    # L'équivalent vSphere des snippets Proxmox, et sans son défaut : la
    # donnée voyage dans la config de la VM, aucun stockage à préparer,
    # aucun téléversement qui puisse être refusé.
    payload = user_data
    if render_user_data and real_plain:
        payload = render_user_data(real_plain)
    if payload:
        meta = _metadata(body, real_plain)
        _wait(vm.ReconfigVM_Task(spec=vim.vm.ConfigSpec(extraConfig=[
            vim.option.OptionValue(
                key="guestinfo.userdata",
                value=base64.b64encode(payload.encode()).decode()),
            vim.option.OptionValue(key="guestinfo.userdata.encoding", value="base64"),
            vim.option.OptionValue(
                key="guestinfo.metadata",
                value=base64.b64encode(meta.encode()).decode()),
            vim.option.OptionValue(key="guestinfo.metadata.encoding", value="base64"),
        ])))

    # Le disque système du template est rarement à la bonne taille.
    _grow_system_disk(vm, body.disk_gb)

    _wait(vm.PowerOnVM_Task())
    # `vm_uuid` : l'UUID SMBIOS attribué par vCenter, ancre d'identité de la fiche
    # OSIRIS (cf. `Machine.vm_uuid`). Même rôle que le `smbios1: uuid=…` de Proxmox.
    return {
        "vm_id":   _moid_number(vm),
        "mac":     real_plain,
        "vm_uuid": (getattr(vm.config, "uuid", "") or "").lower(),
    }


def _grow_system_disk(vm, disk_gb: int) -> None:
    """Agrandit le disque système si la taille demandée dépasse celle du template."""
    if not disk_gb:
        return
    disk = next((d for d in vm.config.hardware.device
                 if isinstance(d, vim.vm.device.VirtualDisk)), None)
    if disk is None:
        return
    wanted_kb = disk_gb * 1024 * 1024
    # On n'agrandit JAMAIS vers le bas : vSphere refuse, et une réduction
    # silencieuse détruirait des données.
    if disk.capacityInKB >= wanted_kb:
        return
    disk.capacityInKB = wanted_kb
    spec = vim.vm.ConfigSpec(deviceChange=[
        vim.vm.device.VirtualDeviceSpec(
            operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=disk)
    ])
    _wait(vm.ReconfigVM_Task(spec=spec))
