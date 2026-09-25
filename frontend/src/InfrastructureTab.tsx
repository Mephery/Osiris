// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useState } from 'react'
import { toast } from 'sonner'
import type { ClusterStorage, Hypervisor, ProxmoxNode, ProxmoxTemplate } from './types'
import { authHeader } from './types'
import { IcoX } from './icons'
import { lireReponse } from './api'
import { InventaireHyperviseur } from './InventaireHyperviseur'
import { Spinner } from './Skeleton'

const API_URL = import.meta.env.VITE_API_URL ?? ''

interface InfrastructureTabProps {
  token: string
  hypervisors: Hypervisor[]
  onRefreshHypervisors: () => void
}


export function InfrastructureTab({ token, hypervisors, onRefreshHypervisors }: InfrastructureTabProps) {
  const [newHv, setNewHv]               = useState({ name: '', url: '', type: 'proxmox', token_id: '', token_secret: '', tls_verify: true, ca_cert: '', pool: '', snippets_storage: '', callback_url: '', zabbix_server: '' })
  const [hvTestResult, setHvTestResult] = useState<Record<number, { ok: boolean; version?: string; proxmox_version?: string; nodes?: ProxmoxNode[]; storages?: ClusterStorage[]; error?: string } | null>>({})
  // Fiche en cours d'édition. Il n'existait AUCUN moyen de modifier un hyperviseur
  // enregistré : ni ici, ni ailleurs dans l'UI. Tout champ ajouté après coup — le
  // pool, la vérification TLS — restait donc hors d'atteinte sur les fiches
  // existantes, alors que ce sont précisément elles qu'il faut corriger.
  const [editHvId, setEditHvId] = useState<number | null>(null)
  const [editHv, setEditHv] = useState<Partial<Hypervisor> & { token_secret?: string; ca_cert?: string }>({})
  const [hvTesting, setHvTesting]       = useState<Record<number, boolean>>({})
  // Modèles de chaque hyperviseur, affichés à la demande : leur liste coûte un
  // appel à l'hyperviseur (et une lecture de config par modèle sur Proxmox).
  const [gabarits, setGabarits]         = useState<Record<number, ProxmoxTemplate[] | 'chargement' | undefined>>({})
  const [inventaireOuvert, setInventaireOuvert] = useState<Record<number, boolean>>({})

  const handleCreateHv = (e: React.FormEvent) => {
    e.preventDefault()
    fetch(`${API_URL}/hypervisors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(newHv),
    }).then(r => lireReponse(r, 'Création refusée')).then(() => { onRefreshHypervisors(); setNewHv({ name: '', url: '', type: 'proxmox', token_id: '', token_secret: '', tls_verify: true, ca_cert: '', pool: '', snippets_storage: '', callback_url: '', zabbix_server: '' }); toast.success('Hyperviseur ajouté') })
      .catch((e: Error) => toast.error(e.message))
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
      .then(r => lireReponse(r, 'Suppression refusée'))
      .then(() => { onRefreshHypervisors(); toast.success('Hyperviseur supprimé') })
      .catch((e: Error) => toast.error(e.message))
  }

  const chargerGabarits = (id: number) => {
    setGabarits(g => ({ ...g, [id]: 'chargement' }))
    fetch(`${API_URL}/hypervisors/${id}/templates`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : [])
      .then((t: ProxmoxTemplate[]) => setGabarits(g => ({ ...g, [id]: Array.isArray(t) ? t : [] })))
      .catch(() => setGabarits(g => ({ ...g, [id]: [] })))
  }

  // Pour les gabarits scellés avant que le scellement ne s'annonce lui-même :
  // sans marque, le formulaire les griserait alors qu'ils fonctionnent.
  const basculerMarque = (hvId: number, t: ProxmoxTemplate) => {
    fetch(`${API_URL}/hypervisors/${hvId}/templates/${t.vmid}/osiris`, {
      method: t.osiris ? 'DELETE' : 'POST', headers: authHeader(token),
    }).then(async r => {
      if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail ?? 'Erreur') }
      toast.success(t.osiris ? `${t.name} n'est plus un gabarit OSIRIS` : `${t.name} marqué comme gabarit OSIRIS`)
      chargerGabarits(hvId)
    }).catch(err => toast.error(err.message))
  }

  const handleTestHv = (id: number) => {
    setHvTesting(prev => ({ ...prev, [id]: true }))
    setHvTestResult(prev => ({ ...prev, [id]: null }))
    fetch(`${API_URL}/hypervisors/${id}/test`, { method: 'POST', headers: authHeader(token) })
      .then(r => lireReponse<Record<string, unknown>>(r, 'Test refusé'))
      .then(data => setHvTestResult(prev => ({ ...prev, [id]: { ok: true, ...data } })))
      .catch((e: Error) => setHvTestResult(prev => ({ ...prev, [id]: { ok: false,
        // Un fetch qui rejette sans réponse : c'est OSIRIS lui-même qu'on ne joint pas
        error: e instanceof TypeError ? 'Impossible de joindre OSIRIS' : e.message } })))
      .finally(() => setHvTesting(prev => ({ ...prev, [id]: false })))
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
                    {hvTesting[h.id] ? <span className="flex items-center gap-1.5"><Spinner cls="w-3 h-3" label="Test en cours" /> Test…</span> : 'Tester'}
                  </button>
                  <button onClick={() => gabarits[h.id] ? setGabarits(g => ({ ...g, [h.id]: undefined })) : chargerGabarits(h.id)}
                    className="osiris-btn text-xs px-3">
                    {gabarits[h.id] ? 'Masquer les gabarits' : 'Gabarits'}
                  </button>
                  <button onClick={() => setInventaireOuvert(o => ({ ...o, [h.id]: !o[h.id] }))}
                    className="osiris-btn text-xs px-3" title="Toutes les VM de l'hyperviseur, leurs réseaux et leurs adresses — lecture seule">
                    {inventaireOuvert[h.id] ? "Masquer l'inventaire" : 'Inventaire'}
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

              {inventaireOuvert[h.id] && (
                <div className="border-t border-slate-800/60 pt-3">
                  <InventaireHyperviseur token={token} hvId={h.id} />
                </div>
              )}

              {/* Gabarits : lesquels portent l'agent, et lequel */}
              {gabarits[h.id] && (
                <div className="border-t border-slate-800/60 pt-3 space-y-1.5">
                  {gabarits[h.id] === 'chargement' ? (
                    <p className="text-[10px] text-slate-500 flex items-center gap-2"><Spinner /> Lecture des modèles sur l'hyperviseur…</p>
                  ) : (gabarits[h.id] as ProxmoxTemplate[]).length === 0 ? (
                    <p className="text-[10px] text-slate-500">Aucun modèle sur cet hyperviseur.</p>
                  ) : (
                    <>
                      <p className="text-[10px] text-slate-500">
                        Seuls les gabarits OSIRIS sont proposés en clone nu. Un gabarit s'enregistre tout seul au scellement ;
                        ceux scellés avant se marquent ici.
                      </p>
                      {(gabarits[h.id] as ProxmoxTemplate[]).map(t => (
                        <div key={t.vmid} className="flex items-center justify-between gap-3 text-xs">
                          <span className="min-w-0 truncate">
                            <span className="text-slate-200">{t.name}</span>
                            {t.node && <span className="text-slate-600 font-mono text-[10px]"> · {t.node}</span>}
                          </span>
                          <span className="flex items-center gap-2 flex-shrink-0">
                            {!t.osiris ? (
                              <span className="text-[10px] text-slate-600">sans agent OSIRIS</span>
                            ) : t.osiris.etat === 'a_jour' ? (
                              <span className="text-[10px] text-emerald-400">✓ agent à jour</span>
                            ) : t.osiris.etat === 'perime' ? (
                              <span className="text-[10px] text-amber-400" title="Scellé avec une version antérieure de l'agent : le resceller pour lui donner les derniers correctifs.">agent ancien — à resceller</span>
                            ) : (
                              <span className="text-[10px] text-slate-400" title="Marqué à la main : OSIRIS ne sait pas avec quelle version de l'agent il a été scellé.">gabarit OSIRIS · agent inconnu</span>
                            )}
                            {(!t.osiris || t.osiris.etat === 'inconnu') && (
                              <button onClick={() => basculerMarque(h.id, t)} className="osiris-btn-ghost text-[10px] border border-slate-700 rounded px-2 py-0.5">
                                {t.osiris ? 'Retirer' : 'Marquer comme gabarit OSIRIS'}
                              </button>
                            )}
                          </span>
                        </div>
                      ))}
                    </>
                  )}
                </div>
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
