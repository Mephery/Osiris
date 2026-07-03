// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { Machine } from './types'
import { authHeader } from './types'
import { IcoRefresh, IcoCheck, IcoX } from './icons'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

interface CaptureJob { mac: string; wim_name: string; status: string; registered_at: string; finished_at?: string }

export function CaptureTab({ token, machines, refreshSignal }: { token: string; machines: Machine[]; refreshSignal: number }) {
  const [captureJobs, setCaptureJobs] = useState<CaptureJob[]>([])
  const [captureMac, setCaptureMac]   = useState('')
  const [captureWim, setCaptureWim]   = useState('')
  const [captureStep, setCaptureStep] = useState(1)

  const fetchCaptures = () => {
    fetch(`${API_URL}/capture`, { headers: authHeader(token) })
      .then(r => r.json()).then(d => setCaptureJobs(d.jobs ?? []))
      .catch(() => {})
  }

  useEffect(() => { fetchCaptures() }, [token, refreshSignal])

  const handleRegisterCapture = () => {
    if (!captureMac || !captureWim) return
    fetch(`${API_URL}/capture/register?mac=${encodeURIComponent(captureMac)}&wim_name=${encodeURIComponent(captureWim)}`,
      { method: 'POST', headers: authHeader(token) })
      .then(r => { if (!r.ok) throw new Error('Erreur'); return r.json() })
      .then(() => {
        fetchCaptures()
        setCaptureStep(4)
        toast.success('Machine enregistrée en mode capture — démarrez-la en PXE !')
      })
      .catch(() => toast.error('Erreur lors de l\'enregistrement'))
  }

  const handleDeleteCapture = (mac: string) => {
    fetch(`${API_URL}/capture/${mac}`, { method: 'DELETE', headers: authHeader(token) })
      .then(() => { fetchCaptures(); toast.success('Job de capture supprimé') })
  }

  return (
    <div className="osiris-table-wrap overflow-x-auto">
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/80">
        <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Capture d'une Golden Image</h2>
        <button onClick={fetchCaptures} className="osiris-btn-ghost text-[10px]">
          <IcoRefresh cls="w-3 h-3 inline" /> Rafraîchir
        </button>
      </div>

      {/* ── Guide pas-à-pas ── */}
      <div className="px-5 py-4 border-b border-slate-800/60 space-y-5">
        <p className="text-xs text-slate-500 font-mono">
          Suivez les étapes dans l'ordre. La machine de référence doit être sur le même réseau qu'OSIRIS.
        </p>

        {/* Étapes */}
        {[
          { n: 1, titre: 'Préparer la machine de référence', desc: 'Déployez un Windows via OSIRIS (ou installez-le manuellement), installez toutes vos applications (TeamViewer Host, antivirus, Office…). Ne joignez pas de domaine.' },
          { n: 2, titre: 'Lancer Sysprep', desc: 'Sur la machine de référence, ouvrez une invite de commandes en administrateur et lancez :', cmd: 'C:\\Windows\\System32\\Sysprep\\sysprep.exe /generalize /oobe /shutdown', note: 'La machine s\'éteint toute seule. Ne la redémarrez pas avant la capture !' },
          { n: 3, titre: 'Enregistrer la machine dans OSIRIS', desc: 'Renseignez l\'adresse MAC de la machine de référence et le nom du fichier WIM à créer, puis cliquez sur Enregistrer.' },
          { n: 4, titre: 'Démarrer la machine en PXE', desc: 'Démarrez la machine de référence sur le réseau (PXE). OSIRIS détecte automatiquement qu\'elle est en mode capture et lance le script. Attendez la fin (15–40 min).' },
        ].map(step => (
          <div key={step.n} className={`flex gap-4 ${captureStep >= step.n ? '' : 'opacity-40'}`}>
            <div className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold border
              ${captureStep > step.n ? 'bg-emerald-900 border-emerald-700 text-emerald-400' :
                captureStep === step.n ? 'bg-blue-900 border-blue-600 text-blue-300' :
                'border-slate-700 text-slate-600'}`}>
              {captureStep > step.n ? <IcoCheck cls="w-3 h-3" /> : step.n}
            </div>
            <div className="flex-1 space-y-1">
              <p className="text-xs font-semibold text-white">{step.titre}</p>
              <p className="text-[11px] text-slate-500">{step.desc}</p>
              {'cmd' in step && (
                <pre className="text-[10px] bg-slate-950 border border-slate-800 rounded px-3 py-2 text-emerald-400 font-mono overflow-x-auto">{step.cmd}</pre>
              )}
              {'note' in step && (
                <p className="text-[10px] text-amber-600 font-mono">{step.note}</p>
              )}
              {/* Étape 3 : formulaire */}
              {step.n === 3 && (
                <div className="flex gap-2 mt-2 flex-wrap">
                  <select
                    value={captureMac}
                    onChange={e => { setCaptureMac(e.target.value); setCaptureStep(3) }}
                    className="osiris-input text-xs font-mono w-64"
                  >
                    <option value="">— Choisir une machine Windows —</option>
                    {machines
                      .filter(m => m.os === 'windows')
                      .map(m => (
                        <option key={m.mac} value={m.mac}>
                          {m.hostname} ({m.mac})
                        </option>
                      ))}
                  </select>
                  <input
                    placeholder="Nom du fichier  (ex: golden_clientA.wim)"
                    value={captureWim}
                    onChange={e => setCaptureWim(e.target.value)}
                    className="osiris-input text-xs font-mono w-60"
                  />
                  <button
                    onClick={handleRegisterCapture}
                    disabled={!captureMac || !captureWim}
                    className="osiris-btn text-xs disabled:opacity-40"
                  >
                    Enregistrer
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* ── Liste des jobs ── */}
      {captureJobs.length > 0 && (
        <table className="w-full text-sm">
          <thead><tr className="border-b border-slate-800/60">
            {['MAC', 'Fichier WIM', 'Statut', 'Enregistré le', 'Action'].map(h => (
              <th key={h} className="text-left px-4 py-2.5 text-[10px] font-semibold uppercase tracking-widest text-slate-600">{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {captureJobs.map(job => (
              <tr key={job.mac} className="osiris-row">
                <td className="px-4 py-2 font-mono text-xs text-slate-400">{job.mac}</td>
                <td className="px-4 py-2 font-mono text-xs text-white">{job.wim_name}</td>
                <td className="px-4 py-2">
                  <span className={`osiris-status-badge ${
                    job.status === 'done'      ? 'osiris-status--deployed' :
                    job.status === 'capturing' ? 'osiris-status--deploying' :
                    job.status === 'failed'    ? 'osiris-status--failed' :
                                                 'osiris-status--pending'}`}>
                    {job.status === 'waiting' ? 'En attente de boot PXE' :
                     job.status === 'capturing' ? 'Capture en cours…' :
                     job.status === 'done' ? 'Terminé' : 'Échec'}
                  </span>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-slate-600">
                  {new Date(job.registered_at).toLocaleString('fr-FR')}
                </td>
                <td className="px-4 py-2">
                  {(job.status === 'done' || job.status === 'failed') && (
                    <button onClick={() => handleDeleteCapture(job.mac)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
