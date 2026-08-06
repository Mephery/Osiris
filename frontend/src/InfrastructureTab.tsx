// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useState } from 'react'
import { toast } from 'sonner'
import type { Hypervisor, Organization, Profile, ProxmoxNode, ProxmoxTemplate } from './types'
import { authHeader } from './types'
import { IcoX } from './icons'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

interface InfrastructureTabProps {
  token: string
  hypervisors: Hypervisor[]
  profiles: Profile[]
  organizations: Organization[]
  selectedOrg: number | null
  onRefreshHypervisors: () => void
  onVmCreated: () => void
}

export function InfrastructureTab({ token, hypervisors, profiles, organizations, selectedOrg, onRefreshHypervisors, onVmCreated }: InfrastructureTabProps) {
  const [newHv, setNewHv]               = useState({ name: '', url: '', type: 'proxmox', token_id: '', token_secret: '', tls_verify: false, snippets_storage: '', callback_url: '' })
  const [hvTestResult, setHvTestResult] = useState<Record<number, { ok: boolean; version?: string; proxmox_version?: string; nodes?: ProxmoxNode[]; error?: string } | null>>({})
  const [hvTesting, setHvTesting]       = useState<Record<number, boolean>>({})
  const [showVmForm, setShowVmForm]     = useState(false)
  const [vmHvId, setVmHvId]             = useState<number | ''>('')
  const [vmNode, setVmNode]             = useState('')
  const [vmStorages, setVmStorages]     = useState<{storage:string;type:string;avail_gb:number;total_gb:number}[]>([])
  const [vmNetworks, setVmNetworks]     = useState<{iface:string;type:string;address:string}[]>([])
  const [vmNodes, setVmNodes]           = useState<ProxmoxNode[]>([])
  const [vmForm, setVmForm]             = useState({ organization_id: selectedOrg ?? '', hostname: '', client: '', os: 'ubuntu', profile_id: '', ou: '', storage: '', bridge: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, data_disk_gb: 0, ip_cidr: '', gateway: '', dns_servers: '', iso: '', boot_mode: 'pxe', template_id: '' })
  const [vmTemplates, setVmTemplates]   = useState<ProxmoxTemplate[]>([])
  const [vmCreating, setVmCreating]     = useState(false)

  const handleCreateHv = (e: React.FormEvent) => {
    e.preventDefault()
    fetch(`${API_URL}/hypervisors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(newHv),
    }).then(r => { if (r.ok) { onRefreshHypervisors(); setNewHv({ name: '', url: '', type: 'proxmox', token_id: '', token_secret: '', tls_verify: false, snippets_storage: '', callback_url: '' }); toast.success('Hyperviseur ajouté') } else throw new Error() })
      .catch(() => toast.error('Erreur création hyperviseur'))
  }

  const handleDeleteHv = (id: number) => {
    fetch(`${API_URL}/hypervisors/${id}`, { method: 'DELETE', headers: authHeader(token) })
      .then(r => { if (r.ok) { onRefreshHypervisors(); toast.success('Hyperviseur supprimé') } })
  }

  const handleTestHv = (id: number) => {
    setHvTesting(prev => ({ ...prev, [id]: true }))
    setHvTestResult(prev => ({ ...prev, [id]: null }))
    fetch(`${API_URL}/hypervisors/${id}/test`, { method: 'POST', headers: authHeader(token) })
      .then(async r => {
        const data = await r.json()
        if (r.ok) setHvTestResult(prev => ({ ...prev, [id]: { ok: true, ...data } }))
        else setHvTestResult(prev => ({ ...prev, [id]: { ok: false, error: data.detail ?? 'Erreur inconnue' } }))
      })
      .catch(() => setHvTestResult(prev => ({ ...prev, [id]: { ok: false, error: 'Impossible de joindre OSIRIS' } })))
      .finally(() => setHvTesting(prev => ({ ...prev, [id]: false })))
  }

  const loadVmResources = (hvId: number, node: string) => {
    setVmStorages([]); setVmNetworks([])
    const h = authHeader(token)
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/storages`, { headers: h })
      .then(r => r.json()).then(setVmStorages).catch(() => {})
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/networks`, { headers: h })
      .then(r => r.json()).then(setVmNetworks).catch(() => {})
  }

  const handleVmHvChange = (hvId: number) => {
    setVmHvId(hvId); setVmNode(''); setVmStorages([]); setVmNetworks([]); setVmNodes([])
    setVmForm(f => ({ ...f, storage: '', bridge: '' }))
    fetch(`${API_URL}/hypervisors/${hvId}/nodes`, { headers: authHeader(token) })
      .then(r => r.json()).then((nodes: ProxmoxNode[]) => {
        setVmNodes(nodes)
        if (nodes.length === 1) {
          setVmNode(nodes[0].node)
          loadVmResources(hvId, nodes[0].node)
        }
      }).catch(() => {})
  }

  const handleVmNodeChange = (node: string) => {
    setVmNode(node)
    setVmStorages([]); setVmNetworks([]); setVmTemplates([])
    setVmForm(f => ({ ...f, storage: '', bridge: '', template_id: '' }))
    if (vmHvId) {
      loadVmResources(Number(vmHvId), node)
      fetch(`${API_URL}/hypervisors/${vmHvId}/nodes/${node}/templates`, { headers: authHeader(token) })
        .then(r => r.json()).then(setVmTemplates).catch(() => {})
    }
  }

  const handleCreateVm = (e: React.FormEvent) => {
    e.preventDefault()
    if (!vmHvId || !vmNode) return
    setVmCreating(true)
    fetch(`${API_URL}/hypervisors/${vmHvId}/create-vm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify({
        ...vmForm,
        node: vmNode,
        profile_id: vmForm.profile_id ? Number(vmForm.profile_id) : null,
        template_id: vmForm.template_id ? Number(vmForm.template_id) : null,
        organization_id: vmForm.organization_id === '' ? null : Number(vmForm.organization_id),
      }),
    }).then(async r => {
      if (!r.ok) { const e = await r.json(); throw new Error(e.detail ?? 'Erreur') }
      return r.json()
    }).then(data => {
      // Une VM cloud-init démarre seule et rappelle OSIRIS : annoncer « en attente de
      // boot PXE » laissait croire qu'il restait une action à faire.
      toast.success(
        vmForm.boot_mode === 'cloudinit'
          ? `VM "${data.hostname}" créée (VMID ${data.vm_id}) - démarrage en cours`
          : `VM "${data.hostname}" créée (VMID ${data.vm_id}) - en attente de boot PXE`
      )
      setShowVmForm(false)
      setVmForm({ organization_id: selectedOrg ?? '', hostname: '', client: '', os: 'ubuntu', profile_id: '', ou: '', storage: '', bridge: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, data_disk_gb: 0, ip_cidr: '', gateway: '', dns_servers: '', iso: '', boot_mode: 'pxe', template_id: '' })
      onVmCreated()
    }).catch(err => toast.error(err.message))
      .finally(() => setVmCreating(false))
  }

  return (
    <div className="osiris-table-wrap p-5 space-y-6 max-w-4xl">
      <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Hyperviseurs</h2>

      {/* Liste */}
      <div className="space-y-3">
        {hypervisors.length === 0 && <p className="text-slate-700 text-xs font-mono">Aucun hyperviseur enregistré</p>}
        {hypervisors.map(h => {
          const result = hvTestResult[h.id]
          return (
            <div key={h.id} className="border border-slate-800/60 rounded p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-white font-medium">{h.name}</span>
                    <span className="inline-block border border-blue-800/60 text-blue-400 rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider">{h.type}</span>
                    {!h.tls_verify && <span className="inline-block border border-amber-800/60 text-amber-500 rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider">TLS non verifie</span>}
                  </div>
                  <p className="text-[11px] font-mono text-slate-500 mt-0.5 truncate">{h.url}</p>
                  <p className="text-[10px] font-mono text-slate-600">{h.token_id || '—'}</p>
                </div>
                <div className="flex gap-1.5 flex-shrink-0">
                  <button onClick={() => handleTestHv(h.id)} disabled={hvTesting[h.id]}
                    className="osiris-btn text-xs px-3 disabled:opacity-50">
                    {hvTesting[h.id] ? '...' : 'Tester'}
                  </button>
                  <button onClick={() => handleDeleteHv(h.id)} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                </div>
              </div>

              {/* Résultat du test */}
              {result && (
                <div className={`rounded p-3 text-xs font-mono space-y-2 ${result.ok ? 'bg-green-950/40 border border-green-800/40' : 'bg-red-950/40 border border-red-800/40'}`}>
                  {result.ok ? (
                    <>
                      {/* vCenter renvoie son nom complet, Proxmox un simple numéro de version. */}
                      <p className="text-green-400">Connexion OK - {h.type === 'vsphere' ? result.version : `Proxmox ${result.proxmox_version ?? result.version}`}</p>
                      {result.nodes && result.nodes.length > 0 && (
                        <table className="w-full text-[10px]">
                          <thead>
                            <tr className="text-slate-500">
                              <th className="text-left pr-4">Noeud</th>
                              <th className="text-left pr-4">Statut</th>
                              <th className="text-right pr-4">CPU</th>
                              <th className="text-right pr-4">vCPU</th>
                              <th className="text-right">RAM</th>
                            </tr>
                          </thead>
                          <tbody>
                            {result.nodes.map(n => (
                              <tr key={n.node} className="text-slate-300">
                                <td className="pr-4 font-semibold">{n.node}</td>
                                <td className={`pr-4 ${n.status === 'online' ? 'text-green-400' : 'text-red-400'}`}>{n.status}</td>
                                <td className="text-right pr-4">{n.cpu}%</td>
                                <td className="text-right pr-4">{n.maxcpu}</td>
                                <td className="text-right">{n.mem_gb} / {n.maxmem_gb} Go</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </>
                  ) : (
                    <p className="text-red-400">{result.error}</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Formulaire d'ajout */}
      {/* Bouton + formulaire création VM */}
      {hypervisors.length > 0 && (
        <div className="pt-3 border-t border-slate-800/50">
          {!showVmForm ? (
            <button onClick={() => setShowVmForm(true)} className="osiris-btn text-xs px-4">+ Créer une VM</button>
          ) : (
            <form onSubmit={handleCreateVm} className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-[9px] uppercase tracking-widest text-slate-600">Nouvelle VM</p>
                <button type="button" onClick={() => setShowVmForm(false)} className="text-slate-600 hover:text-slate-300 text-xs">Annuler</button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <input required placeholder="Hostname" value={vmForm.hostname} onChange={e => setVmForm(f => ({...f, hostname: e.target.value}))} className="osiris-input text-xs font-mono" />
                <input required placeholder="Client / label" value={vmForm.client} onChange={e => setVmForm(f => ({...f, client: e.target.value}))} className="osiris-input text-xs" />
                {/* L'organisation portait la supervision, le webhook et les reglages
                    materiel, mais n'apparaissait nulle part ici : le formulaire reprenait
                    en silence le filtre « Client » du haut de page. Une VM creee filtre sur
                    « Tous les clients » naissait sans organisation, donc sans agent Zabbix,
                    sans que rien ne le signale. Vecu le 2026-08-05. */}
                <select value={vmForm.organization_id} onChange={e => setVmForm(f => ({...f, organization_id: e.target.value === '' ? '' : Number(e.target.value)}))} className="osiris-input text-xs">
                  <option value="">— Aucune organisation (pas de supervision) —</option>
                  {organizations.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
                <select value={vmForm.os} onChange={e => setVmForm(f => ({
                    ...f, os: e.target.value, profile_id: '',
                    // Windows = PXE uniquement (WinPE) : le cloud-init est spécifique Linux.
                    ...(e.target.value === 'windows' ? { boot_mode: 'pxe', template_id: '' } : {}),
                  }))} className="osiris-input text-xs">
                  <option value="ubuntu">Ubuntu</option>
                  <option value="debian">Debian</option>
                  <option value="windows">Windows</option>
                </select>
                {/* Choisir un profil reprend son gabarit matériel : c'est le profil
                    qui sait ce que demande ce type de serveur, pas l'opérateur. Les
                    valeurs restent modifiables juste en dessous. */}
                <select value={vmForm.profile_id} onChange={e => {
                    const p = profiles.find(p => String(p.id) === e.target.value)
                    setVmForm(f => ({
                      ...f, profile_id: e.target.value,
                      ...(p ? {
                        vcpus: p.vm_vcpus ?? f.vcpus,
                        ram_mb: p.vm_ram_mb ?? f.ram_mb,
                        disk_gb: p.vm_disk_gb ?? f.disk_gb,
                        data_disk_gb: p.vm_data_disk_gb ?? f.data_disk_gb,
                      } : {}),
                    }))
                  }} className="osiris-input text-xs">
                  <option value="">Profil par défaut</option>
                  {profiles.filter(p => p.os === vmForm.os).map(p => (
                    <option key={p.id} value={p.id}>{p.name}{p.machine_type === 'server' ? ' [serveur]' : ''}</option>
                  ))}
                </select>
                <input placeholder="OU (optionnel)" value={vmForm.ou} onChange={e => setVmForm(f => ({...f, ou: e.target.value}))} className="osiris-input text-xs font-mono col-span-2" />
              </div>

              {/* Sélection hyperviseur + noeud */}
              <div className="grid grid-cols-2 gap-2">
                <select required value={vmHvId} onChange={e => handleVmHvChange(Number(e.target.value))} className="osiris-input text-xs">
                  <option value="">Hyperviseur...</option>
                  {hypervisors.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
                </select>
                <select required value={vmNode} onChange={e => handleVmNodeChange(e.target.value)} className="osiris-input text-xs" disabled={!vmHvId || vmNodes.length === 0}>
                  <option value="">Noeud...</option>
                  {vmNodes.map(n => (
                    <option key={n.node} value={n.node}>{n.node} — {n.cpu}% CPU · {n.mem_gb}/{n.maxmem_gb} Go RAM</option>
                  ))}
                </select>
              </div>

              {/* Mode de boot — Windows : PXE ou template sysprep ; Linux : + cloud-init */}
              <div className="flex gap-2">
                {(vmForm.os === 'windows' ? ['pxe', 'template'] as const : ['pxe', 'template', 'cloudinit'] as const).map(mode => (
                  <button key={mode} type="button"
                    onClick={() => setVmForm(f => ({...f, boot_mode: mode, template_id: '', iso: ''}))}
                    className={`flex-1 py-1.5 rounded text-xs border transition-colors ${vmForm.boot_mode === mode ? 'bg-blue-600/20 border-blue-500 text-blue-300' : 'bg-slate-900 border-slate-700 text-slate-500 hover:border-slate-500'}`}>
                    {mode === 'pxe'
                      ? (vmForm.os === 'windows' ? 'PXE / WinPE' : 'PXE (ISO / installation)')
                      : mode === 'template' ? 'Template (clone)' : 'Cloud-init'}
                  </button>
                ))}
              </div>

              {/* Ressources */}
              <div className="grid grid-cols-2 gap-2">
                <select required value={vmForm.storage} onChange={e => setVmForm(f => ({...f, storage: e.target.value}))} className="osiris-input text-xs" disabled={vmStorages.length === 0}>
                  <option value="">Stockage...</option>
                  {vmStorages.map(s => <option key={s.storage} value={s.storage}>{s.storage} ({s.type}) — {s.avail_gb} Go libres</option>)}
                </select>
                <select required value={vmForm.bridge} onChange={e => setVmForm(f => ({...f, bridge: e.target.value}))} className="osiris-input text-xs" disabled={vmNetworks.length === 0}>
                  <option value="">Bridge réseau...</option>
                  {vmNetworks.map(n => <option key={n.iface} value={n.iface}>{n.iface}{n.address ? ` (${n.address})` : ''}</option>)}
                </select>
                <div className="flex items-center gap-1">
                  <label className="text-[10px] text-slate-500 shrink-0">vCPU</label>
                  <input type="number" min={1} max={64} value={vmForm.vcpus} onChange={e => setVmForm(f => ({...f, vcpus: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                </div>
                <div className="flex items-center gap-1">
                  <label className="text-[10px] text-slate-500 shrink-0">RAM Mo</label>
                  <input type="number" min={512} step={512} value={vmForm.ram_mb} onChange={e => setVmForm(f => ({...f, ram_mb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                </div>
                <div className="flex items-center gap-1">
                  <label className="text-[10px] text-slate-500 shrink-0">Disque Go</label>
                  <input type="number" min={8} value={vmForm.disk_gb} onChange={e => setVmForm(f => ({...f, disk_gb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                </div>
                <div className="flex items-center gap-1">
                  <label className="text-[10px] text-slate-500 shrink-0" title="Second disque, formaté et monté sur /data au premier démarrage. 0 = aucun.">/data Go</label>
                  <input type="number" min={0} value={vmForm.data_disk_gb} onChange={e => setVmForm(f => ({...f, data_disk_gb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                </div>

                <div className="col-span-2 space-y-1 pt-1">
                  <p className="text-[9px] uppercase tracking-widest text-slate-600">
                    Adressage IP <span className="normal-case text-slate-700">(vide = DHCP)</span>
                  </p>
                  <div className="grid grid-cols-3 gap-2">
                    <input placeholder="10.0.0.60/24" value={vmForm.ip_cidr}
                      onChange={e => setVmForm(f => ({...f, ip_cidr: e.target.value}))}
                      className="osiris-input text-xs font-mono" />
                    <input placeholder="Passerelle" value={vmForm.gateway}
                      onChange={e => setVmForm(f => ({...f, gateway: e.target.value}))}
                      className="osiris-input text-xs font-mono" />
                    <input placeholder="DNS (séparés par ,)" value={vmForm.dns_servers}
                      onChange={e => setVmForm(f => ({...f, dns_servers: e.target.value}))}
                      className="osiris-input text-xs font-mono" />
                  </div>
                  <p className="text-[9px] text-slate-600">
                    À renseigner sur un VLAN sans DHCP : sans adresse, la VM démarre et ne rappelle jamais OSIRIS.
                  </p>
                </div>

                {vmForm.boot_mode === 'pxe' ? (
                  <input placeholder="ISO Proxmox (ex: local:iso/ubuntu-24.04.iso) — optionnel" value={vmForm.iso} onChange={e => setVmForm(f => ({...f, iso: e.target.value}))} className="osiris-input text-xs font-mono col-span-2" />
                ) : (
                  <select required value={vmForm.template_id} onChange={e => setVmForm(f => ({...f, template_id: e.target.value}))} className="osiris-input text-xs col-span-2" disabled={vmTemplates.length === 0}>
                    <option value="">{vmTemplates.length === 0 ? (vmNode ? 'Aucun template trouvé sur ce noeud' : 'Choisir un noeud d\'abord') : 'Template Proxmox...'}</option>
                    {vmTemplates.map(t => <option key={t.vmid} value={t.vmid}>{t.name} (VMID {t.vmid}) — {t.cores} vCPU · {t.maxmem_gb} Go</option>)}
                  </select>
                )}
              </div>

              <div className="text-[10px] text-slate-600 bg-slate-900/60 rounded p-2 font-mono">
                {vmForm.boot_mode === 'pxe'
                  ? (vmForm.os === 'windows'
                      ? 'WinPE livré en CD-ROM (UEFI/OVMF · disque SATA · carte e1000). La VM s\'installe puis rappelle OSIRIS.'
                      : 'Boot order : PXE → disque → ISO. La VM s\'enregistrera dans OSIRIS au premier boot réseau.')
                  : vmForm.boot_mode === 'template'
                    ? 'Clone du template + MAC neuve. Le clone lit sa MAC au démarrage et rappelle OSIRIS (agent cuit dans le template). Démarrage ~2 min, aucune injection.'
                    : 'Clone complet du template + cloud-init injecté via snippets Proxmox. Démarrage ~30s, pas de PXE requis.'}
              </div>
              <button type="submit" disabled={vmCreating || !vmNode || !vmForm.storage || !vmForm.bridge} className="osiris-btn text-xs px-4 w-full disabled:opacity-50">
                {vmCreating ? 'Création en cours...' : 'Créer et démarrer la VM'}
              </button>
            </form>
          )}
        </div>
      )}

      <form onSubmit={handleCreateHv} className="space-y-3 pt-3 border-t border-slate-800/50">
        <p className="text-[9px] uppercase tracking-widest text-slate-600">Ajouter un hyperviseur</p>
        <div className="grid grid-cols-2 gap-2">
          <input required placeholder="Nom  (ex : Proxmox Lab)" value={newHv.name} onChange={e => setNewHv({ ...newHv, name: e.target.value })} className="osiris-input text-xs" />
          <select value={newHv.type} onChange={e => setNewHv({ ...newHv, type: e.target.value })} className="osiris-input text-xs">
            <option value="proxmox">Proxmox VE</option>
            <option value="vsphere">VMware vCenter</option>
          </select>
          <input required placeholder={newHv.type === 'vsphere' ? 'URL  (https://vcenter.local)' : 'URL  (https://proxmox.local:8006)'} value={newHv.url} onChange={e => setNewHv({ ...newHv, url: e.target.value })} className="osiris-input text-xs font-mono" />
          <input placeholder={newHv.type === 'vsphere' ? 'Compte de service  (osiris@vsphere.local)' : 'Token ID  (osiris@pve!osiris-token)'} value={newHv.token_id} onChange={e => setNewHv({ ...newHv, token_id: e.target.value })} className="osiris-input text-xs font-mono" />
          <input type="password" placeholder={newHv.type === 'vsphere' ? 'Mot de passe du compte' : 'Token secret'} value={newHv.token_secret} onChange={e => setNewHv({ ...newHv, token_secret: e.target.value })} className="osiris-input text-xs font-mono" />
          {newHv.type === 'proxmox' && <input placeholder="Stockage snippets cloud-init (ex: local) — optionnel" value={newHv.snippets_storage} onChange={e => setNewHv({ ...newHv, snippets_storage: e.target.value })} className="osiris-input text-xs font-mono col-span-2" title="Nom du stockage Proxmox avec content-type snippets, requis pour cloud-init complet" />}
          <input placeholder="URL d'OSIRIS vue par les VM de cet hyperviseur — vide = URL globale"
            value={newHv.callback_url} onChange={e => setNewHv({ ...newHv, callback_url: e.target.value })}
            className="osiris-input text-xs font-mono col-span-2"
            title="À renseigner si les VM de cet hyperviseur joignent OSIRIS à une autre adresse que le réseau de déploiement. L'URL est gravée dans les scripts de premier démarrage." />
        </div>
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={newHv.tls_verify} onChange={e => setNewHv({ ...newHv, tls_verify: e.target.checked })} className="accent-blue-500" />
            Verifier le certificat TLS (decocher si cert self-signe)
          </label>
          <button type="submit" className="osiris-btn text-xs px-4">+ Ajouter</button>
        </div>
      </form>
    </div>
  )
}
