// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useEffect, useState } from 'react'
import { authHeader } from './types'
import { IcoRefresh } from './icons'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

export function DashboardTab({ token }: { token: string }) {
  const [dashboard, setDashboard] = useState<any>(null)
  const [dashboardLoading, setDashboardLoading] = useState(false)

  const fetchDashboard = () => {
    setDashboardLoading(true)
    fetch(`${API_URL}/dashboard`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setDashboard(data); setDashboardLoading(false) })
      .catch(() => { setDashboard({}); setDashboardLoading(false) })
  }

  useEffect(() => { fetchDashboard() }, [token])

  return (
    <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Tableau de bord</h2>
        <button onClick={fetchDashboard} className="osiris-btn text-xs">
          {dashboardLoading ? 'Chargement...' : <><IcoRefresh cls="w-3 h-3 inline" /> Rafraichir</>}
        </button>
      </div>
      {dashboardLoading ? (
        <p className="text-slate-700 font-mono text-xs">Chargement...</p>
      ) : !dashboard || dashboard.total_machines === 0 ? (
        <p className="text-slate-700 font-mono text-xs">Aucune machine enregistree pour l'instant.</p>
      ) : (
        <>
          {/* Compteurs globaux */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {(['deployed', 'pending', 'deploying', 'failed'] as const).map(s => {
              const colors: Record<string, string> = { deployed: 'text-green-400', pending: 'text-blue-400', deploying: 'text-yellow-400', failed: 'text-red-400' }
              const labels: Record<string, string> = { deployed: 'Deployes', pending: 'En attente', deploying: 'En cours', failed: 'Echoues' }
              return (
                <div key={s} className="bg-slate-900 border border-slate-800/60 rounded p-4 text-center">
                  <p className={`text-3xl font-bold ${colors[s]}`}>{dashboard.status_counts[s] ?? 0}</p>
                  <p className="text-[10px] text-slate-500 mt-1 uppercase tracking-widest">{labels[s]}</p>
                </div>
              )
            })}
          </div>

          {/* Alertes */}
          {dashboard.alerts.length > 0 && (
            <div className="space-y-1">
              <p className="text-[9px] uppercase tracking-widest text-slate-600">Alertes</p>
              {dashboard.alerts.map((a: any, i: number) => (
                <div key={i} className={`text-xs p-2 rounded border font-mono ${a.type === 'stuck_deploying' ? 'border-yellow-800/50 bg-yellow-950/30 text-yellow-400' : 'border-red-800/50 bg-red-950/30 text-red-400'}`}>
                  {a.type === 'stuck_deploying' ? `En cours depuis plus de 30 min` : `Echec recent`} - <strong>{a.hostname}</strong> ({a.mac})
                </div>
              ))}
            </div>
          )}

          {/* Stats par org */}
          {dashboard.org_stats.length > 0 && (
            <div className="space-y-2">
              <p className="text-[9px] uppercase tracking-widest text-slate-600">Par organisation</p>
              {dashboard.org_stats.sort((a: any, b: any) => b.total - a.total).map((o: any) => (
                <div key={o.org_id} className="bg-slate-900 border border-slate-800/60 rounded p-3 flex items-center gap-4">
                  <span className="text-slate-300 text-sm font-medium w-40 truncate">{o.org_name}</span>
                  <div className="flex-1 flex gap-1 h-2">
                    {(['deployed', 'pending', 'deploying', 'failed'] as const).map(s => {
                      const pct = o.total ? Math.round((o[s] ?? 0) / o.total * 100) : 0
                      const colors = { deployed: 'bg-green-500', pending: 'bg-blue-500', deploying: 'bg-yellow-500', failed: 'bg-red-500' }
                      return pct > 0 ? <div key={s} className={`${colors[s]} rounded`} style={{ width: `${pct}%` }} title={`${s}: ${o[s]}`} /> : null
                    })}
                  </div>
                  <span className="text-slate-600 text-[10px] font-mono w-16 text-right">{o.total} machine{o.total > 1 ? 's' : ''}</span>
                </div>
              ))}
            </div>
          )}

          {/* Derniers deploiements */}
          {dashboard.recent_deployments.length > 0 && (
            <div className="space-y-1">
              <p className="text-[9px] uppercase tracking-widest text-slate-600">Deploiements recents</p>
              <div className="border border-slate-800/60 rounded overflow-hidden">
                {dashboard.recent_deployments.map((e: any, i: number) => (
                  <div key={i} className={`flex items-center gap-3 px-3 py-2 text-xs font-mono ${i % 2 === 0 ? 'bg-slate-900/40' : ''}`}>
                    <span className={`w-16 text-center rounded px-1 py-0.5 text-[9px] font-bold ${e.status === 'deployed' ? 'bg-green-900/60 text-green-400' : 'bg-red-900/60 text-red-400'}`}>{e.status}</span>
                    <span className="text-slate-300 w-40 truncate">{e.hostname}</span>
                    <span className="text-slate-600 flex-1 truncate">{e.profile_name}</span>
                    <span className="text-slate-700">{new Date(e.timestamp).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
