// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { DriverPack } from './types'
import { authHeader } from './types'
import { IcoRefresh, IcoSearch, IcoDownload, IcoCheck, IcoChevDown, IcoChevRight } from './icons'
import { SkeletonRows } from './Skeleton'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

export function DriversTab({ token }: { token: string }) {
  const [drivers, setDrivers]           = useState<DriverPack[]>([])
  const [driversLoading, setDriversLoading] = useState(false)
  const [syncing, setSyncing]           = useState<string | null>(null)
  const [downloadingPack, setDownloadingPack] = useState<number | null>(null)
  const [driverSearch, setDriverSearch]       = useState('')
  const [expandedVendors, setExpandedVendors] = useState<Set<string>>(new Set())

  const fetchDrivers = (vendor = 'all') => {
    setDriversLoading(true)
    const qs = vendor !== 'all' ? `?vendor=${vendor}` : ''
    fetch(`${API_URL}/drivers${qs}`, { headers: authHeader(token) })
      .then((r) => r.json())
      .then((d) => setDrivers(Array.isArray(d) ? d : []))
      .catch(() => {})
      .finally(() => setDriversLoading(false))
  }

  useEffect(() => { fetchDrivers() }, [token])

  const handleSync = (vendor: string, delay: number) => {
    setSyncing(vendor)
    fetch(`${API_URL}/drivers/sync/${vendor}`, { method: 'POST', headers: authHeader(token) })
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.status }))
          toast.error(`Erreur sync ${vendor} : ${err.detail}`)
          setSyncing(null)
          return
        }
        setTimeout(() => { fetchDrivers(); setSyncing(null) }, delay)
      })
      .catch((err) => { toast.error(`Erreur réseau : ${err.message}`); setSyncing(null) })
  }

  const toggleVendor = (vendor: string) =>
    setExpandedVendors(prev => { const s = new Set(prev); s.has(vendor) ? s.delete(vendor) : s.add(vendor); return s })

  const handleDownloadPack = (id: number) => {
    setDownloadingPack(id)
    fetch(`${API_URL}/drivers/${id}/download`, { method: 'POST', headers: authHeader(token) })
      .then(() => {})
      .catch(() => {})
      .finally(() => setDownloadingPack(null))
  }

  return (
    <div className="osiris-table-wrap overflow-x-auto">
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/80">
        <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Catalogue Drivers</h2>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => fetchDrivers()} className="osiris-btn-ghost text-[10px]">
            {driversLoading ? 'Chargement…' : <><IcoRefresh cls="w-3 h-3 inline" /> Rafraîchir</>}
          </button>
          <button onClick={() => handleSync('dell', 15000)} disabled={syncing !== null} className="osiris-btn text-xs">
            {syncing === 'dell' ? 'Dell en cours…' : <><IcoRefresh cls="w-3 h-3 inline" /> Dell</>}
          </button>
          <button onClick={() => handleSync('hp', 30000)} disabled={syncing !== null} className="osiris-btn text-xs">
            {syncing === 'hp' ? 'HP en cours…' : <><IcoRefresh cls="w-3 h-3 inline" /> HP</>}
          </button>
          <button onClick={() => handleSync('lenovo', 20000)} disabled={syncing !== null} className="osiris-btn text-xs">
            {syncing === 'lenovo' ? 'Lenovo en cours…' : <><IcoRefresh cls="w-3 h-3 inline" /> Lenovo</>}
          </button>
        </div>
      </div>
      {driversLoading ? (
        <SkeletonRows count={6} cols={5} />
      ) : drivers.length === 0 ? (
        <p className="text-slate-700 font-mono text-xs p-5">Aucun driver : lancez une synchronisation pour remplir le catalogue.</p>
      ) : (() => {
        const q = driverSearch.toLowerCase()
        const isSearching = q.length > 0

        // Groupement par vendor
        const groups: Record<string, DriverPack[]> = {}
        for (const d of drivers) {
          if (!groups[d.vendor]) groups[d.vendor] = []
          if (!isSearching || d.model.toLowerCase().includes(q)) groups[d.vendor].push(d)
        }
        const vendorOrder = ['dell', 'hp', 'lenovo']
        const vendorLabel: Record<string, string> = { dell: 'Dell', hp: 'HP', lenovo: 'Lenovo' }

        const DriverRow = ({ d }: { d: DriverPack }) => (
          <tr className="osiris-row">
            <td className="px-4 py-2 font-mono text-xs text-white">
              {d.model}
              {/* Identifiant matériel du constructeur : c'est lui qui sépare un
                  ThinkPad T15 (20S6/20S7) d'un T15g (20UR/20US), que le nom confond. */}
              {d.hw_ids && (
                <span className="ml-2 font-mono text-[10px] uppercase text-slate-500" title="Identifiant matériel constructeur">{d.hw_ids}</span>
              )}
            </td>
            <td className="px-4 py-2 font-mono text-xs text-slate-500">{d.os_code}</td>
            <td className="px-4 py-2 font-mono text-xs text-slate-600 whitespace-nowrap">{d.size_mb ? `${d.size_mb} MB` : '—'}</td>
            <td className="px-4 py-2">
              <span className={`osiris-status-badge ${
                d.status === 'ready'       ? 'osiris-status--deployed' :
                d.status === 'downloading' ? 'osiris-status--deploying' :
                d.status === 'error'       ? 'osiris-status--failed' :
                d.status === 'failed'      ? 'osiris-status--failed' :
                                             'osiris-status--pending'
              }`}>{d.status}</span>
              {d.error && (
                <p className="mt-1 max-w-xs font-mono text-[10px] leading-tight text-rose-400" title={d.error}>{d.error}</p>
              )}
            </td>
            <td className="px-4 py-2">
              {d.status !== 'ready' && d.status !== 'downloading' && (
                <button onClick={() => handleDownloadPack(d.id)} disabled={downloadingPack === d.id} className="osiris-action-btn text-[10px]">
                  {downloadingPack === d.id ? '…' : <IcoDownload />}
                </button>
              )}
              {d.status === 'ready' && <span className="text-emerald-600 font-mono text-[10px] flex items-center gap-1"><IcoCheck cls="w-3 h-3" /> Prêt</span>}
              {d.status === 'downloading' && <span className="text-blue-500 font-mono text-[10px] animate-pulse">En cours…</span>}
            </td>
          </tr>
        )

        return (
          <>
            {/* Barre de recherche */}
            <div className="px-5 py-3 border-b border-slate-800/80 flex items-center gap-3">
              <span className="text-slate-600 flex-shrink-0"><IcoSearch /></span>
              <input type="text" placeholder="Rechercher un modèle…"
                value={driverSearch} onChange={e => setDriverSearch(e.target.value)}
                className="osiris-input text-xs flex-1 max-w-sm" />
              {isSearching && (
                <span className="text-[10px] font-mono text-slate-600">
                  {Object.values(groups).flat().length} résultat{Object.values(groups).flat().length !== 1 ? 's' : ''}
                </span>
              )}
            </div>

            {isSearching ? (
              /* ── Mode recherche : tableau plat ── */
              <table className="w-full text-sm">
                <thead><tr className="border-b border-slate-800/80">
                  {['Modèle', 'OS', 'Taille', 'Statut', 'Action'].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600 whitespace-nowrap">{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {Object.values(groups).flat().slice(0, 100).map(d => <DriverRow key={d.id} d={d} />)}
                </tbody>
              </table>
            ) : (
              /* ── Mode accordéon : dossiers par vendor ── */
              <div className="divide-y divide-slate-800/60">
                {vendorOrder.filter(v => (groups[v]?.length ?? 0) > 0 || drivers.some(d => d.vendor === v)).map(vendor => {
                  const items = groups[vendor] ?? []
                  const total = drivers.filter(d => d.vendor === vendor).length
                  const open  = expandedVendors.has(vendor)
                  const ready = items.filter(d => d.status === 'ready').length
                  return (
                    <div key={vendor}>
                      {/* En-tête du dossier */}
                      <button onClick={() => toggleVendor(vendor)}
                        className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-slate-800/30 transition-colors text-left">
                        <span className="text-slate-500 w-3 flex-shrink-0">{open ? <IcoChevDown /> : <IcoChevRight />}</span>
                        <span className="font-bold text-sm text-white tracking-wide">{vendorLabel[vendor]}</span>
                        <span className="text-[10px] font-mono text-slate-600">{total} modèle{total !== 1 ? 's' : ''}</span>
                        {ready > 0 && <span className="text-[10px] font-mono text-emerald-600">{ready} prêt{ready !== 1 ? 's' : ''}</span>}
                        <span className="ml-auto text-[10px] text-slate-700">{open ? 'Fermer' : 'Ouvrir'}</span>
                      </button>
                      {/* Contenu du dossier */}
                      {open && (
                        <div className="border-t border-slate-800/60 bg-slate-950/40">
                          <table className="w-full text-sm">
                            <thead><tr className="border-b border-slate-800/60">
                              {['Modèle', 'OS', 'Taille', 'Statut', 'Action'].map(h => (
                                <th key={h} className="text-left px-4 py-2.5 text-[10px] font-semibold uppercase tracking-widest text-slate-700 whitespace-nowrap">{h}</th>
                              ))}
                            </tr></thead>
                            <tbody>
                              {items.slice(0, 200).map(d => <DriverRow key={d.id} d={d} />)}
                              {items.length > 200 && (
                                <tr><td colSpan={5} className="px-4 py-3 text-center text-[10px] font-mono text-slate-700">
                                  … {items.length - 200} modèles masqués — utilisez la recherche pour les trouver
                                </td></tr>
                              )}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )
      })()}
    </div>
  )
}
