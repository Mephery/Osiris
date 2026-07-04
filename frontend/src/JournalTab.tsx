// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useEffect, useState } from 'react'
import type { AuditLogEntry } from './types'
import { ACTION_META, authHeader, formatMac, formatDetails } from './types'
import { IcoSearch, IcoRefresh } from './icons'
import { SkeletonRows } from './Skeleton'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

export function JournalTab({ token, onUnauthorized }: { token: string; onUnauthorized: () => void }) {
  const [auditLogs, setAuditLogs]         = useState<AuditLogEntry[]>([])
  const [auditLoading, setAuditLoading]   = useState(false)
  const [auditFilterAction, setAuditFilterAction] = useState('')
  const [auditFilterEmail, setAuditFilterEmail]   = useState('')
  const [auditFilterMac, setAuditFilterMac]       = useState('')

  const fetchAuditLogs = (action = auditFilterAction, email = auditFilterEmail, mac = auditFilterMac) => {
    setAuditLoading(true)
    const params = new URLSearchParams({ limit: '100' })
    if (action)  params.set('action', action)
    if (email)   params.set('user_email', email)
    if (mac)     params.set('mac', mac)
    fetch(`${API_URL}/audit-logs?${params}`, { headers: authHeader(token) })
      .then((res) => { if (res.status === 401) onUnauthorized(); return res.ok ? res.json() : [] })
      .then((data) => { setAuditLogs(Array.isArray(data) ? data : []); setAuditLoading(false) })
      .catch(() => setAuditLoading(false))
  }

  useEffect(() => { fetchAuditLogs() }, [token])

  return (
    <div className="osiris-table-wrap overflow-x-auto">
      <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-slate-800/80">
        <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500 mr-auto">Journal d'activité</h2>
        <select value={auditFilterAction} onChange={e => setAuditFilterAction(e.target.value)}
          className="osiris-input text-[10px] py-1 w-40">
          <option value="">Toutes les actions</option>
          {Object.entries(ACTION_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <input value={auditFilterEmail} onChange={e => setAuditFilterEmail(e.target.value)}
          placeholder="Utilisateur…" className="osiris-input text-[10px] py-1 w-36" />
        <input value={auditFilterMac} onChange={e => setAuditFilterMac(e.target.value)}
          placeholder="MAC…" className="osiris-input text-[10px] py-1 w-32 font-mono" />
        <button onClick={() => fetchAuditLogs(auditFilterAction, auditFilterEmail, auditFilterMac)}
          className="osiris-btn text-[10px]">
          {auditLoading ? '…' : <><IcoSearch cls="w-3 h-3 inline" /> Filtrer</>}
        </button>
        <button onClick={() => { setAuditFilterAction(''); setAuditFilterEmail(''); setAuditFilterMac(''); fetchAuditLogs('', '', '') }}
          className="osiris-btn-ghost text-[10px]">
          <IcoRefresh cls="w-3 h-3 inline" /> Reset
        </button>
      </div>
      {auditLoading ? (
        <SkeletonRows count={6} cols={5} />
      ) : auditLogs.length === 0 ? (
        <p className="text-slate-700 font-mono text-xs p-5">Aucune entrée de journal</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800/80">
              {['Horodatage', 'Utilisateur', 'Action', 'Machine', 'Détails'].map(h => (
                <th key={h} className="text-left px-4 py-2.5 text-[10px] font-semibold uppercase tracking-widest text-slate-600 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {auditLogs.map((entry) => {
              const meta = ACTION_META[entry.action] ?? { label: entry.action, cls: 'text-slate-500 border-slate-700' }
              return (
                <tr key={entry.id} className="osiris-row">
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-500 whitespace-nowrap">
                    {new Date(entry.timestamp).toLocaleDateString('fr-FR', {
                      day: '2-digit', month: '2-digit', year: '2-digit',
                      hour: '2-digit', minute: '2-digit', second: '2-digit'
                    })}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-400 whitespace-nowrap">{entry.user_email}</td>
                  <td className="px-4 py-2.5 whitespace-nowrap">
                    <span className={`inline-block border rounded px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider ${meta.cls}`}>
                      {meta.label}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-600 whitespace-nowrap">
                    {entry.target_mac ? formatMac(entry.target_mac) : '—'}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-600 max-w-xs truncate" title={formatDetails(entry.details)}>
                    {formatDetails(entry.details)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
