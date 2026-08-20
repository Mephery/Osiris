// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useState } from 'react'
import { toast } from 'sonner'
import type { ClusterStorage, Hypervisor, NetworkDefaults, Organization, Profile, ProxmoxNetwork, ProxmoxNode, ProxmoxTemplate } from './types'
import { authHeader } from './types'
import { IcoX } from './icons'
import { buildCreateVmPayload, completerPrefixeCidr, dansLeReseau } from './vmForm'

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
  const [newHv, setNewHv]               = useState({ name: '', url: '', type: 'proxmox', token_id: '', token_secret: '', tls_verify: true, ca_cert: '', pool: '', snippets_storage: '', callback_url: '', zabbix_server: '' })
  const [hvTestResult, setHvTestResult] = useState<Record<number, { ok: boolean; version?: string; proxmox_version?: string; nodes?: ProxmoxNode[]; storages?: ClusterStorage[]; error?: string } | null>>({})
  // Fiche en cours d'édition. Il n'existait AUCUN moyen de modifier un hyperviseur
  // enregistré : ni ici, ni ailleurs dans l'UI. Tout champ ajouté après coup — le
  // pool, la vérification TLS — restait donc hors d'atteinte sur les fiches
  // existantes, alors que ce sont précisément elles qu'il faut corriger.
  const [editHvId, setEditHvId] = useState<number | null>(null)
  const [editHv, setEditHv] = useState<Partial<Hypervisor> & { token_secret?: string; ca_cert?: string }>({})
  const [hvTesting, setHvTesting]       = useState<Record<number, boolean>>({})
  const [showVmForm, setShowVmForm]     = useState(false)
  const [vmHvId, setVmHvId]             = useState<number | ''>('')
  const [vmNode, setVmNode]             = useState('')
  const [vmStorages, setVmStorages]     = useState<{storage:string;type:string;avail_gb:number;total_gb:number}[]>([])
  const [vmNetworks, setVmNetworks]     = useState<ProxmoxNetwork[]>([])
  const [vmNetDef, setVmNetDef]         = useState<NetworkDefaults | null>(null)
  const [vmNodes, setVmNodes]           = useState<ProxmoxNode[]>([])
  const [vmForm, setVmForm]             = useState({ organization_id: selectedOrg ?? '', hostname: '', client: '', os: 'ubuntu', profile_id: '', ou: '', storage: '', bridge: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, data_disk_gb: 0, ip_cidr: '', gateway: '', dns_servers: '', iso: '', boot_mode: 'pxe', template_id: '', post_script: '' })
  const [vmTemplates, setVmTemplates]   = useState<ProxmoxTemplate[]>([])
  const [vmCreating, setVmCreating]     = useState(false)

  const handleCreateHv = (e: React.FormEvent) => {
    e.preventDefault()
    fetch(`${API_URL}/hypervisors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(newHv),
    }).then(r => { if (r.ok) { onRefreshHypervisors(); setNewHv({ name: '', url: '', type: 'proxmox', token_id: '', token_secret: '', tls_verify: true, ca_cert: '', pool: '', snippets_storage: '', callback_url: '', zabbix_server: '' }); toast.success('Hyperviseur ajouté') } else throw new Error() })
      .catch(() => toast.error('Erreur création hyperviseur'))
  }

  const startEditHv = (h: Hypervisor) => {
    setEditHvId(h.id)
    // `token_secret` volontairement vide : l'API renvoie « *** », le renvoyer tel
    // quel écraserait le vrai secret par trois étoiles chiffrées. Vide = on n'y touche pas.
    // `ca_cert` volontairement vide : l'API n'en renvoie qu'un résumé. Vide dans le
    // formulaire = « ne pas y toucher », comme pour le secret du jeton.
    setEditHv({ name: h.name, url: h.url, token_id: h.token_id, token_secret: '', ca_cert: '',
                tls_verify: h.tls_verify, pool: h.pool ?? '',
                snippets_storage: h.snippets_storage ?? '', callback_url: h.callback_url ?? '',
                zabbix_server: h.zabbix_server ?? '' })
  }

  const handleSaveHv = (e: React.FormEvent) => {
    e.preventDefault()
    if (editHvId === null) return
    const body = { ...editHv }
    if (!body.token_secret) delete body.token_secret
    if (!body.ca_cert) delete body.ca_cert     // vide = on garde l'autorité en place
    fetch(`${API_URL}/hypervisors/${editHvId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(body),
    }).then(async r => {
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail ?? 'Erreur') }
      setEditHvId(null); onRefreshHypervisors(); toast.success('Hyperviseur modifié')
    }).catch(err => toast.error(err.message))
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
    setVmStorages([]); setVmNetworks([]); setVmNetDef(null)
    const h = authHeader(token)
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/storages`, { headers: h })
      .then(r => r.json()).then(setVmStorages).catch(() => {})
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/networks`, { headers: h })
      .then(r => r.json()).then(setVmNetworks).catch(() => {})
  }

  const handleVmHvChange = (hvId: number) => {
    setVmHvId(hvId); setVmNode(''); setVmStorages([]); setVmNetworks([]); setVmNodes([]); setVmNetDef(null)
    setVmForm(f => ({ ...f, storage: '', bridge: '', template_id: '' }))
    // Les templates sont ceux de TOUT l'hyperviseur, indépendamment du nœud : sur un
    // stockage partagé, le disque d'un template est lisible par tous les nœuds, et
    // OSIRIS sait cloner vers celui qu'on choisit. Les lier au nœud enfermait le
    // formulaire — un template posé sur un nœud condamnait ses VM à ce nœud.
    fetch(`${API_URL}/hypervisors/${hvId}/templates`, { headers: authHeader(token) })
      .then(r => r.json()).then(setVmTemplates).catch(() => {})
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
    setVmStorages([]); setVmNetworks([]); setVmNetDef(null)
    setVmForm(f => ({ ...f, storage: '', bridge: '' }))
    if (vmHvId) loadVmResources(Number(vmHvId), node)
  }

  // Choisir un réseau, c'est aussi choisir une passerelle et un DNS : ces deux
  // valeurs appartiennent au réseau, pas à la machine. On ne remplit que les champs
  // encore vides — une saisie de l'opérateur n'est jamais écrasée par une
  // proposition, même mieux informée.
  const handleVmBridgeChange = (bridge: string) => {
    setVmForm(f => ({ ...f, bridge }))
    setVmNetDef(null)
    if (!vmHvId || !vmNode || !bridge) return
    fetch(`${API_URL}/hypervisors/${vmHvId}/nodes/${vmNode}/network-defaults?bridge=${encodeURIComponent(bridge)}`,
          { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : null)
      .then((d: NetworkDefaults | null) => {
        if (!d) return
        setVmNetDef(d)
        setVmForm(f => ({
          ...f,
          gateway:     f.gateway     || d.gateway,
          dns_servers: f.dns_servers || d.dns_servers,
        }))
      })
      .catch(() => {})
  }

  // L'adresse est saisie par l'opérateur — OSIRIS n'en propose jamais. Mais quand le
  // préfixe du réseau est connu, l'oubli du « /24 » n'a pas à coûter un aller-retour
  // avec le serveur : on complète ce qui manque, sans toucher au reste.
  const completerPrefixe = () => {
    if (!vmNetDef?.prefixe) return
    setVmForm(f => ({ ...f, ip_cidr: completerPrefixeCidr(f.ip_cidr, vmNetDef.prefixe) }))
  }

  const handleCreateVm = (e: React.FormEvent) => {
    e.preventDefault()
    if (!vmHvId || !vmNode) return
    setVmCreating(true)
    fetch(`${API_URL}/hypervisors/${vmHvId}/create-vm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(buildCreateVmPayload(vmForm, vmNode)),
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
      setVmNetDef(null)
      setVmForm({ organization_id: selectedOrg ?? '', hostname: '', client: '', os: 'ubuntu', profile_id: '', ou: '', storage: '', bridge: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, data_disk_gb: 0, ip_cidr: '', gateway: '', dns_servers: '', iso: '', boot_mode: 'pxe', template_id: '', post_script: '' })
      onVmCreated()
    }).catch(err => toast.error(err.message))
      .finally(() => setVmCreating(false))
  }

  // Recalculés à chaque frappe : ils ne bloquent rien, ils avertissent. Un VLAN peut
  // légitimement porter plusieurs réseaux, et OSIRIS ne voit que ses propres fiches —
  // dans les deux cas c'est l'opérateur qui tranche, pas nous.
  const adresseSaisie = vmForm.ip_cidr.split('/')[0].trim()
  const horsReseau    = !!(vmNetDef?.reseau && vmForm.ip_cidr
                           && dansLeReseau(vmForm.ip_cidr, vmNetDef.reseau) === false)
  const dejaPrise     = !!(adresseSaisie && vmNetDef?.occupees.includes(adresseSaisie))
  const provenance    = vmNetDef
    ? [...new Set(Object.values(vmNetDef.origines))]
        .map(o => o === 'bridge' ? "lu sur l'hyperviseur" : 'repris des déploiements précédents')
        .join(' · ')
    : ''

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
                    {h.tls_verify && <span className="inline-block border border-emerald-800/60 text-emerald-400 rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider">TLS verifie</span>}
                    {h.ca_present && (
                      <span className="inline-block border border-slate-700 text-slate-400 rounded px-1.5 py-0.5 text-[9px] font-mono tracking-wider"
                        title="Autorité de certification renseignée pour cet hyperviseur">
                        CA : {h.ca_resume?.erreur
                          ? <span className="text-red-400">illisible</span>
                          : `${h.ca_resume?.autorite ?? '?'} — exp. ${h.ca_resume?.expire_le ?? '?'}`}
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] font-mono text-slate-500 mt-0.5 truncate">{h.url}</p>
                  <p className="text-[10px] font-mono text-slate-600">{h.token_id || '—'}</p>
                </div>
                <div className="flex gap-1.5 flex-shrink-0">
                  <button onClick={() => handleTestHv(h.id)} disabled={hvTesting[h.id]}
                    className="osiris-btn text-xs px-3 disabled:opacity-50">
                    {hvTesting[h.id] ? '...' : 'Tester'}
                  </button>
                  <button onClick={() => editHvId === h.id ? setEditHvId(null) : startEditHv(h)}
                    className="osiris-btn text-xs px-3">
                    {editHvId === h.id ? 'Annuler' : 'Modifier'}
                  </button>
                  <button onClick={() => handleDeleteHv(h.id)} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                </div>
              </div>

              {/* Formulaire d'édition */}
              {editHvId === h.id && (
                <form onSubmit={handleSaveHv} className="border-t border-slate-800/60 pt-3 space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <input placeholder="Nom" value={editHv.name ?? ''}
                      onChange={e => setEditHv({ ...editHv, name: e.target.value })}
                      className="osiris-input text-xs" />
                    <input placeholder="URL" value={editHv.url ?? ''}
                      onChange={e => setEditHv({ ...editHv, url: e.target.value })}
                      className="osiris-input text-xs font-mono" />
                    <input placeholder={h.type === 'vsphere' ? 'Compte de service' : 'Token ID'}
                      value={editHv.token_id ?? ''}
                      onChange={e => setEditHv({ ...editHv, token_id: e.target.value })}
                      className="osiris-input text-xs font-mono" />
                    <input type="password" placeholder="Nouveau secret — vide = inchangé"
                      value={editHv.token_secret ?? ''}
                      onChange={e => setEditHv({ ...editHv, token_secret: e.target.value })}
                      className="osiris-input text-xs font-mono" />
                    {h.type === 'proxmox' && (
                      <input placeholder="Pool d'accueil des VM (ex: osiris)" value={editHv.pool ?? ''}
                        onChange={e => setEditHv({ ...editHv, pool: e.target.value })}
                        className="osiris-input text-xs font-mono"
                        title="Ranger les VM d'OSIRIS dans un pool permet de n'attribuer son jeton que sur /pool/<pool> au lieu de /vms. L'hyperviseur refuse alors lui-meme toute ecriture sur une VM tierce." />
                    )}
                    {h.type === 'proxmox' && (
                      <input placeholder="Stockage snippets cloud-init" value={editHv.snippets_storage ?? ''}
                        onChange={e => setEditHv({ ...editHv, snippets_storage: e.target.value })}
                        className="osiris-input text-xs font-mono" />
                    )}
                    <input placeholder="URL de rappel — vide = URL globale" value={editHv.callback_url ?? ''}
                      onChange={e => setEditHv({ ...editHv, callback_url: e.target.value })}
                      className="osiris-input text-xs font-mono col-span-2" />
                    <input placeholder="Collecteur Zabbix du site — vide = celui de l'organisation"
                      value={editHv.zabbix_server ?? ''}
                      onChange={e => setEditHv({ ...editHv, zabbix_server: e.target.value })}
                      className="osiris-input text-xs font-mono col-span-2"
                      title="Chaque site a son propre proxy Zabbix. Vise depuis l'hyperviseur, le collecteur est presque toujours un voisin du meme sous-reseau : la supervision ne traverse aucun pare-feu. Vide = celui de l'organisation de la machine." />
                    {/* Un cluster Proxmox signe ses noeuds avec SA propre autorite, qu'aucun
                        magasin public ne connait. La coller ici rend le certificat verifiable,
                        sans Let's Encrypt ni nom de domaine. Ce n'est pas un secret. */}
                    <textarea rows={3}
                      placeholder={h.type === 'vsphere'
                        ? "Certificat de l'autorité du vCenter (PEM) — vide = magasin système"
                        : "Certificat de l'autorité : contenu de /etc/pve/pve-root-ca.pem — vide = inchangé"}
                      value={editHv.ca_cert ?? ''}
                      onChange={e => setEditHv({ ...editHv, ca_cert: e.target.value })}
                      className="osiris-input text-[10px] font-mono col-span-2"
                      title="Coller le PEM complet, lignes BEGIN/END comprises. Un certificat d'autorité est public : ce n'est pas un secret." />
                  </div>
                  <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                      <input type="checkbox" checked={editHv.tls_verify ?? false}
                        onChange={e => setEditHv({ ...editHv, tls_verify: e.target.checked })}
                        className="accent-blue-500" />
                      Verifier le certificat TLS
                    </label>
                    <button type="submit" className="osiris-btn text-xs px-4">Enregistrer</button>
                  </div>
                  {/* Un certificat auto-signe (le defaut de Proxmox) fait echouer TOUS les
                      appels des qu'on coche : le dire ici evite de chercher la panne ailleurs. */}
                  {!h.tls_verify && editHv.tls_verify && !h.ca_present && !editHv.ca_cert && (
                    <p className="text-[10px] font-mono text-amber-500">
                      Aucune autorité renseignée : la vérification se fera contre le magasin
                      système, qui ne connaît pas l'autorité d'un cluster Proxmox — chaque appel
                      échouera en 502. Coller /etc/pve/pve-root-ca.pem ci-dessus.
                    </p>
                  )}
                </form>
              )}

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

                      {/* ── Stockages ────────────────────────────────────────────
                          Séparé du tableau des nœuds à dessein : le « maxdisk »
                          que Proxmox donne par nœud est la RACINE de
                          l'hyperviseur, pas l'endroit où atterrissent les VM. Un
                          stockage partagé n'apparaît qu'une fois — quatre lignes
                          pour un Ceph laisseraient croire à quatre réserves. */}
                      {result.storages && result.storages.length > 0 && (
                        <div className="pt-1">
                          <p className="text-slate-500 mb-1">Stockages utilisables ({result.storages.length})</p>
                          <table className="w-full text-[10px]">
                            <thead>
                              <tr className="text-slate-500">
                                <th className="text-left pr-4">Stockage</th>
                                <th className="text-left pr-4">Type</th>
                                <th className="text-left pr-4">Portée</th>
                                <th className="text-left pr-4">Usage</th>
                                <th className="text-right pr-4">Rempli</th>
                                <th className="text-right">Libre</th>
                              </tr>
                            </thead>
                            <tbody>
                              {result.storages.map(s => {
                                // Un stockage plein interdit toute création : on le
                                // signale AVANT que le déploiement échoue.
                                const alerte = s.used_pct >= 90 ? 'text-red-400'
                                             : s.used_pct >= 75 ? 'text-amber-400'
                                             : 'text-slate-300'
                                return (
                                  <tr key={`${s.storage}/${s.node}`} className="text-slate-300">
                                    <td className="pr-4 font-semibold">
                                      {s.storage}
                                      {!s.online && <span className="text-red-400"> (hors ligne)</span>}
                                    </td>
                                    <td className="pr-4 text-slate-500">{s.type}</td>
                                    <td className="pr-4 text-slate-500">{s.shared ? 'cluster' : s.node}</td>
                                    <td className="pr-4 text-slate-500">
                                      {s.roles.map(r => r === 'images' ? 'disques' : r === 'iso' ? 'ISO' : r).join(' + ')}
                                    </td>
                                    <td className={`text-right pr-4 ${alerte}`}>{s.used_pct}%</td>
                                    <td className="text-right">
                                      {s.avail_gb >= 1024
                                        ? `${(s.avail_gb / 1024).toFixed(1)} To`
                                        : `${s.avail_gb} Go`} / {s.total_gb >= 1024
                                        ? `${(s.total_gb / 1024).toFixed(1)} To`
                                        : `${s.total_gb} Go`}
                                    </td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
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
                <select required value={vmForm.bridge} onChange={e => handleVmBridgeChange(e.target.value)} className="osiris-input text-xs" disabled={vmNetworks.length === 0}>
                  <option value="">Bridge réseau...</option>
                  {/* Le commentaire porté par le bridge est le nom du VLAN côté réseau
                      (« ADMIN », « Clients_MUTU »…) : c'est cela que l'exploitant a en
                      tête, pas « vmbr320 ». */}
                  {vmNetworks.map(n => (
                    <option key={n.iface} value={n.iface}>
                      {n.iface}{n.comments ? ` — ${n.comments}` : ''}{n.cidr ? ` (${n.cidr})` : ''}
                    </option>
                  ))}
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
                    <input placeholder={vmNetDef?.reseau ? `adresse dans ${vmNetDef.reseau}` : '10.0.0.60/24'}
                      value={vmForm.ip_cidr}
                      onChange={e => setVmForm(f => ({...f, ip_cidr: e.target.value}))}
                      onBlur={completerPrefixe}
                      className="osiris-input text-xs font-mono" />
                    <input placeholder="Passerelle" value={vmForm.gateway}
                      onChange={e => setVmForm(f => ({...f, gateway: e.target.value}))}
                      className="osiris-input text-xs font-mono" />
                    {/* Exigé dès qu'une adresse fixe est saisie : sans DHCP pour en
                        fournir un, la VM n'aurait AUCUN résolveur — et le dirait si peu
                        qu'elle se déclarerait déployée. L'API refuse aussi, mais autant
                        le dire avant d'envoyer le formulaire. */}
                    <input placeholder={vmForm.ip_cidr ? 'DNS — obligatoire' : 'DNS (séparés par ,)'}
                      required={!!vmForm.ip_cidr} value={vmForm.dns_servers}
                      onChange={e => setVmForm(f => ({...f, dns_servers: e.target.value}))}
                      className="osiris-input text-xs font-mono" />
                  </div>
                  <p className="text-[9px] text-slate-600">
                    À renseigner sur un VLAN sans DHCP : sans adresse, la VM démarre et ne rappelle jamais OSIRIS. Adresse en notation CIDR (préfixe /24 obligatoire), passerelle sans préfixe. En adressage fixe, le DNS est obligatoire — aucun bail ne viendra en fournir un.
                  </p>

                  {/* Passerelle et DNS sont des propriétés du RÉSEAU, pas de la machine :
                      les retaper de mémoire à chaque déploiement n'apporte rien qu'un
                      risque de faute de frappe. L'adresse, elle, reste saisie à la main —
                      OSIRIS ne voit que ses propres fiches et ne peut affirmer qu'une
                      adresse est libre. On dit donc ce qu'on sait pris, jamais ce qu'on
                      croit disponible. */}
                  {vmNetDef && (
                    <div className="text-[9px] space-y-0.5 border-l-2 border-slate-800 pl-2">
                      {vmNetDef.reseau ? (
                        <p className="text-slate-500">
                          Réseau <span className="font-mono text-slate-400">{vmNetDef.reseau}</span>
                          {vmNetDef.gateway && <> · passerelle <span className="font-mono text-slate-400">{vmNetDef.gateway}</span></>}
                          {vmNetDef.dns_servers && <> · DNS <span className="font-mono text-slate-400">{vmNetDef.dns_servers}</span></>}
                          {provenance && <span className="text-slate-600"> — {provenance}</span>}
                        </p>
                      ) : (
                        <p className="text-slate-600">
                          Adressage inconnu pour {vmNetDef.bridge} : ce réseau ne porte aucune adresse sur le nœud, et OSIRIS n'y a encore rien déployé. Tout est à saisir — cette fois seulement, le prochain déploiement reprendra ces valeurs.
                        </p>
                      )}
                      {vmNetDef.occupees.length > 0 && (
                        <p className="text-slate-600">
                          Déjà attribuées par OSIRIS : <span className="font-mono">{vmNetDef.occupees.join(', ')}</span> — il ignore tout des machines posées à la main, cette liste dit ce qui est pris, jamais ce qui est libre.
                        </p>
                      )}
                    </div>
                  )}

                  {horsReseau && (
                    <p className="text-[9px] text-amber-400">
                      ⚠ {adresseSaisie} est hors de {vmNetDef?.reseau}. Une VM adressée hors de son réseau démarre, ne route nulle part et reste « en attente » sans un mot d'explication. À vérifier — un VLAN peut légitimement porter plusieurs réseaux.
                    </p>
                  )}
                  {dejaPrise && (
                    <p className="text-[9px] text-amber-400">
                      ⚠ {adresseSaisie} est déjà l'adresse d'une machine enregistrée dans OSIRIS.
                    </p>
                  )}
                </div>

                {vmForm.boot_mode === 'pxe' ? (
                  <input placeholder="ISO Proxmox (ex: local:iso/ubuntu-24.04.iso) — optionnel" value={vmForm.iso} onChange={e => setVmForm(f => ({...f, iso: e.target.value}))} className="osiris-input text-xs font-mono col-span-2" />
                ) : (
                  <select required value={vmForm.template_id} onChange={e => setVmForm(f => ({...f, template_id: e.target.value}))} className="osiris-input text-xs col-span-2" disabled={vmTemplates.length === 0}>
                    <option value="">{vmTemplates.length === 0 ? (vmNode ? 'Aucun template trouvé sur ce noeud' : 'Choisir un noeud d\'abord') : 'Template Proxmox...'}</option>
                    {/* Le nœud du template est affiché : il n'a plus besoin d'être celui du
                        déploiement, mais savoir où vit un modèle reste utile — c'est le
                        seul indice si un clone échoue faute de stockage partagé. */}
                    {vmTemplates.map(t => <option key={t.vmid} value={t.vmid}>{t.name} (VMID {t.vmid}){t.node ? ` · sur ${t.node}` : ''} — {t.cores} vCPU · {t.maxmem_gb} Go</option>)}
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
              <div className="space-y-1">
                <p className="text-[9px] uppercase tracking-widest text-slate-600">
                  Script de post-installation — propre a CETTE VM (optionnel)
                </p>
                <textarea rows={4} value={vmForm.post_script}
                  onChange={e => setVmForm(f => ({...f, post_script: e.target.value}))}
                  placeholder={vmForm.os === 'windows' ? 'PowerShell, execute en fin de premier demarrage' : 'Commandes bash, executees en fin de premier demarrage'}
                  className="osiris-input text-[10px] font-mono w-full resize-y" />
                <p className="text-[9px] text-slate-600">
                  Joue APRES le script du profil : le profil pose le socle commun, celui-ci
                  ne vaut que pour cette VM. Une erreur est journalisee sans faire echouer le
                  deploiement. Execute en root, et grave dans la configuration de la VM cote
                  hyperviseur : y faire CHERCHER un secret, jamais l'y ecrire.
                </p>
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
          {newHv.type === 'proxmox' && <input placeholder="Pool Proxmox d'accueil des VM (ex: osiris) — recommandé"
            value={newHv.pool} onChange={e => setNewHv({ ...newHv, pool: e.target.value })}
            className="osiris-input text-xs font-mono col-span-2"
            title="Ranger les VM d'OSIRIS dans un pool permet de n'attribuer son jeton que sur /pool/<pool> au lieu de /. L'hyperviseur refuse alors lui-meme toute action sur une VM qu'OSIRIS n'a pas creee." />}
          {newHv.type === 'proxmox' && <input placeholder="Stockage snippets cloud-init (ex: local) — optionnel" value={newHv.snippets_storage} onChange={e => setNewHv({ ...newHv, snippets_storage: e.target.value })} className="osiris-input text-xs font-mono col-span-2" title="Nom du stockage Proxmox avec content-type snippets, requis pour cloud-init complet" />}
          <input placeholder="URL d'OSIRIS vue par les VM de cet hyperviseur — vide = URL globale"
            value={newHv.callback_url} onChange={e => setNewHv({ ...newHv, callback_url: e.target.value })}
            className="osiris-input text-xs font-mono col-span-2"
            title="À renseigner si les VM de cet hyperviseur joignent OSIRIS à une autre adresse que le réseau de déploiement. L'URL est gravée dans les scripts de premier démarrage." />
          <input placeholder="Collecteur Zabbix des VM de cet hyperviseur — vide = celui de leur organisation"
            value={newHv.zabbix_server} onChange={e => setNewHv({ ...newHv, zabbix_server: e.target.value })}
            className="osiris-input text-xs font-mono col-span-2"
            title="Chaque site a son propre proxy Zabbix. Vise depuis l'hyperviseur, le collecteur est presque toujours un voisin du meme sous-reseau : la supervision ne traverse aucun pare-feu. Vide = celui de l'organisation de la machine." />
        </div>
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={newHv.tls_verify} onChange={e => setNewHv({ ...newHv, tls_verify: e.target.checked })} className="accent-blue-500" />
            Verifier le certificat TLS — le decocher expose un jeton qui peut detruire des VM
          </label>
          <button type="submit" className="osiris-btn text-xs px-4">+ Ajouter</button>
        </div>
      </form>
    </div>
  )
}
