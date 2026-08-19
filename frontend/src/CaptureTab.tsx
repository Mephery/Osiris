// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useCallback, useEffect, useRef, useState } from 'react'
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
  const prevStatuses = useRef<Record<string, string>>({})

  const fetchCaptures = useCallback(() => {
    fetch(`${API_URL}/capture`, { headers: authHeader(token) })
      .then(r => r.json()).then(d => setCaptureJobs(d.jobs ?? []))
      .catch(() => {})
  }, [token])

  useEffect(() => { fetchCaptures() }, [token, refreshSignal, fetchCaptures])

  // Polling live tant qu'une capture est en attente de boot ou en cours,
  // pour refléter les changements de statut sans clic manuel sur « Rafraîchir ».
  useEffect(() => {
    const hasActive = captureJobs.some(j => j.status === 'waiting' || j.status === 'capturing')
    if (!hasActive) return
    const id = setInterval(fetchCaptures, 5000)
    return () => clearInterval(id)
  }, [captureJobs, token, fetchCaptures])

  // Auto-avancement de l'étape + notifications aux transitions de statut.
  // On ne réagit qu'aux VRAIS changements (job déjà vu qui change d'état) :
  // un job vu pour la première fois est enregistré en silence (pas de toast au chargement).
  useEffect(() => {
    captureJobs.forEach(j => {
      const prev = prevStatuses.current[j.mac]
      if (prev !== undefined && prev !== j.status) {
        if (j.status === 'capturing') {
          setCaptureStep(s => Math.max(s, 4))   // boot PXE détecté → étape 4
          toast.info(`Boot PXE détecté — capture de ${j.mac} en cours`)
        } else if (j.status === 'done') {
          toast.success(`Capture terminée : ${j.wim_name}`)
        } else if (j.status === 'failed') {
          toast.error(`Capture échouée : ${j.mac} — voir le fallback manuel`)
        }
      }
      prevStatuses.current[j.mac] = j.status
    })
  }, [captureJobs])

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

        {/* Encart stratégie : 1 golden par modèle */}
        <div className="rounded-lg border border-sky-900/40 bg-sky-950/10 px-4 py-3 space-y-1.5">
          <p className="text-xs font-semibold text-sky-400">Stratégie : une golden par modèle</p>
          <p className="text-[11px] text-slate-400">
            Une golden embarque les <span className="text-slate-300">pilotes du modèle depuis lequel elle a été capturée</span>{' '}
            (le magasin de pilotes survit au sysprep) : déployée sur le <span className="text-slate-300">même modèle</span>, elle est
            ultra-rapide et déjà driverée. Sur un <span className="text-slate-300">modèle différent</span>, ces pilotes ne
            correspondent pas.
          </p>
          <ul className="text-[11px] text-slate-500 list-disc list-inside space-y-0.5">
            <li><span className="text-slate-400">Parc standard</span> : capturez <span className="text-slate-300">une golden par famille de modèle</span> → chaque déploiement rapide et correctement driveré.</li>
            <li><span className="text-slate-400">Modèle rare / one-off</span> : gardez le déploiement <span className="text-slate-300">install.wim + injection ciblée du pack de pilotes</span> (universel, un peu plus lent).</li>
          </ul>
        </div>

        {/* Étapes */}
        {[
          { n: 1, titre: 'Préparer la machine de référence', desc: 'Déployez un Windows via OSIRIS (ou installez-le manuellement), installez toutes vos applications (TeamViewer Host, antivirus, Office…). Ne joignez pas de domaine.' },
          { n: 2, titre: 'Lancer Sysprep', desc: 'Si des applications ont été installées via winget (déploiement OSIRIS ou manuel), supprimez d\'abord le paquet source winget - sinon Sysprep échoue avec "installed for a user, but not provisioned for all users". Puis, dans une invite de commandes en administrateur, lancez :', cmd: 'Get-AppxPackage -Name "Microsoft.Winget.Source*" -AllUsers | Remove-AppxPackage -AllUsers\nC:\\Windows\\System32\\Sysprep\\sysprep.exe /generalize /oobe /shutdown', note: 'La machine s\'éteint toute seule. Ne la redémarrez pas avant la capture !' },
          { n: 3, titre: 'Enregistrer la machine dans OSIRIS', desc: 'Renseignez l\'adresse MAC de la machine de référence et le nom du fichier WIM à créer, puis cliquez sur Enregistrer.' },
          { n: 4, titre: 'Démarrer la machine en PXE', desc: 'Démarrez la machine de référence sur le réseau (PXE). OSIRIS détecte automatiquement qu\'elle est en mode capture et lance le script. Attendez la fin (15–40 min).' },
        ].map(step => (
          <div key={step.n} className={`flex gap-4 transition-opacity ${captureStep >= step.n ? '' : 'opacity-40'}`}>
            <button
              type="button"
              onClick={() => setCaptureStep(step.n)}
              title={`Aller à l'étape ${step.n}`}
              className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold border
                cursor-pointer transition hover:ring-2 hover:ring-blue-500/40 hover:border-blue-500
                ${captureStep > step.n ? 'bg-emerald-900 border-emerald-700 text-emerald-400' :
                  captureStep === step.n ? 'bg-blue-900 border-blue-600 text-blue-300' :
                  'border-slate-700 text-slate-600'}`}>
              {captureStep > step.n ? <IcoCheck cls="w-3 h-3" /> : step.n}
            </button>
            <div className="flex-1 space-y-1">
              <button
                type="button"
                onClick={() => setCaptureStep(step.n)}
                className="text-xs font-semibold text-white text-left hover:text-blue-300 transition cursor-pointer"
              >
                {step.titre}
              </button>
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

      {/* ── Fallback capture manuelle ── */}
      <details className="rounded-lg border border-amber-900/40 bg-amber-950/10 px-4 py-3">
        <summary className="cursor-pointer text-xs font-semibold text-amber-500 select-none">
          La capture automatique a échoué ? → Capture manuelle depuis WinPE
        </summary>
        <div className="mt-3 space-y-3 text-[11px] text-slate-400">
          <p>
            Sur certains disques NVMe rapides, WinPE met plus de temps à monter la partition
            Windows que la fenêtre de détection du script. Si le job passe en <span className="text-red-400 font-semibold">Échec</span>,
            la machine reste sous WinPE avec une invite de commandes : on peut capturer à la main sans rien réinstaller.
          </p>
          <ol className="list-decimal list-inside space-y-2">
            <li>
              Vérifier que le disque et la partition Windows sont bien visibles :
              <pre className="mt-1 text-[10px] bg-slate-950 border border-slate-800 rounded px-3 py-2 text-emerald-400 font-mono overflow-x-auto">{'diskpart\nlist disk\nlist volume\nexit'}</pre>
              <span className="text-slate-500">Repérez la lettre du volume Windows (souvent C:). Tapez <span className="font-mono">exit</span> pour quitter diskpart avant la suite.</span>
            </li>
            <li>
              Lancer la capture DISM (adaptez la lettre <span className="font-mono">C:</span> et le nom du WIM) :
              <pre className="mt-1 text-[10px] bg-slate-950 border border-slate-800 rounded px-3 py-2 text-emerald-400 font-mono overflow-x-auto">{'dism /Capture-Image /ImageFile:Z:\\golden.wim /CaptureDir:C:\\ /Name:"Golden" /ScratchDir:X:\\ /CheckIntegrity'}</pre>
              <span className="text-slate-500">Z: est le partage OSIRIS déjà monté par le script (les WIM y atterrissent). Le fichier apparaîtra ensuite dans le sélecteur d'image de déploiement.</span>
            </li>
          </ol>
          <p className="text-[10px] text-amber-600 font-mono">
            La fenêtre de détection automatique a été portée à ~10 min — un simple redémarrage PXE suffit souvent à repasser en capture auto sur le retry suivant.
          </p>
        </div>
      </details>

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
                  <button onClick={() => handleDeleteCapture(job.mac)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
