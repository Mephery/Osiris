// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useEffect, useState } from 'react'
import { authHeader } from './types'
import type { LiveEvent } from './types'
import { IcoRefresh } from './icons'
import { SkeletonStatCards } from './Skeleton'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

// Anime un compteur de 0 jusqu'à sa valeur cible (ease-out, pas de rebond) à chaque changement de valeur.
function useCountUp(target: number, duration = 700) {
  const [value, setValue] = useState(0)
  useEffect(() => {
    let raf: number
    const start = performance.now()
    const animate = (now: number) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      setValue(Math.round(target * eased))
      if (t < 1) raf = requestAnimationFrame(animate)
    }
    raf = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])
  return value
}

function CountUp({ value }: { value: number }) {
  return <>{useCountUp(value)}</>
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'en attente de déploiement',
  deploying: 'démarre son déploiement',
  deployed: 'déployée avec succès',
  failed: 'a échoué',
}
const STATUS_DOT: Record<string, string> = {
  pending: 'bg-slate-500',
  deploying: 'bg-blue-500 animate-pulse',
  deployed: 'bg-green-500',
  failed: 'bg-red-500',
}

// Flux d'activité temps réel : les derniers événements reçus par le WebSocket (App.tsx),
// entrent en haut de liste avec une micro-animation.
function LiveActivityStream({ events }: { events: LiveEvent[] }) {
  return (
    <div className="bg-slate-900 border border-slate-800/60 rounded flex flex-col h-full min-h-[320px]">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800/60">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse osiris-live-dot flex-shrink-0" />
        <h3 className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Activité en direct</h3>
      </div>
      <div className="flex-1 overflow-y-auto max-h-[520px] divide-y divide-slate-800/40">
        {events.length === 0 ? (
          <p className="text-slate-700 font-mono text-xs p-4">En attente d'activité…</p>
        ) : (
          events.map(ev => (
            <div key={ev.id} className="osiris-feed-item flex items-start gap-2.5 px-4 py-2.5">
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5 ${
                ev.kind === 'capture'
                  ? (ev.success ? 'bg-green-500' : 'bg-red-500')
                  : STATUS_DOT[ev.status ?? ''] ?? 'bg-slate-500'
              }`} />
              <div className="min-w-0 flex-1">
                <p className="text-xs text-slate-300 leading-tight">
                  <span className="font-mono font-semibold text-white">{ev.hostname}</span>{' '}
                  {ev.kind === 'capture'
                    ? (ev.success ? 'capture terminée avec succès' : 'échec de la capture')
                    : (STATUS_LABEL[ev.status ?? ''] ?? ev.status)}
                </p>
                <p className="text-[10px] font-mono text-slate-700 mt-0.5">
                  {new Date(ev.timestamp).toLocaleTimeString('fr-FR')}
                </p>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export function DashboardTab({ token, liveEvents }: { token: string; liveEvents: LiveEvent[] }) {
  const [dashboard, setDashboard] = useState<any>(null)
  const [dashboardLoading, setDashboardLoading] = useState(false)

  const fetchDashboard = () => {
    setDashboardLoading(true)
    fetch(`${API_URL}/dashboard`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setDashboard(data); setDashboardLoading(false) })
      .catch(() => { setDashboard(null); setDashboardLoading(false) })
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
        <SkeletonStatCards />
      ) : !dashboard || dashboard.total_machines === 0 ? (
        <p className="text-slate-700 font-mono text-xs">Aucune machine enregistree pour l'instant.</p>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          {/* ── Colonne principale (2/3) : stats, alertes, répartition ──────── */}
          <div className="lg:col-span-2 space-y-6">
            {/* Compteurs globaux */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {(['deployed', 'pending', 'deploying', 'failed'] as const).map(s => {
                const colors: Record<string, string> = { deployed: 'text-green-400', pending: 'text-slate-400', deploying: 'text-blue-400', failed: 'text-red-400' }
                const labels: Record<string, string> = { deployed: 'Deployes', pending: 'En attente', deploying: 'En cours', failed: 'Echoues' }
                return (
                  <div key={s} className="bg-slate-900 border border-slate-800/60 rounded p-4 text-center">
                    <p className={`text-3xl font-bold tabular-nums ${colors[s]}`}><CountUp value={dashboard.status_counts[s] ?? 0} /></p>
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
                  <div key={i} className={`text-xs p-2 rounded border font-mono ${a.type === 'stuck_deploying' ? 'border-amber-800/50 bg-amber-950/30 text-amber-400' : 'border-red-800/50 bg-red-950/30 text-red-400'}`}>
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
                        const colors = { deployed: 'bg-green-500', pending: 'bg-slate-500', deploying: 'bg-blue-500', failed: 'bg-red-500' }
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
          </div>

          {/* ── Colonne latérale (1/3) : flux d'activité temps réel ─────────── */}
          <div className="lg:col-span-1">
            <LiveActivityStream events={liveEvents} />
          </div>
        </div>
      )}
    </div>
  )
}
