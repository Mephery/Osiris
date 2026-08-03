// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import type { Machine, DeploymentEvent, SnapshotEntry } from './types'
import { IcoX, IcoTerminal, IcoCamera, IcoDownload } from './icons'

interface VmProps {
  consoleUrl: string
  powerState: { status: string; cpu: number; mem_mb: number } | null
  powerLoading: boolean
  onRefreshStatus: () => void
  onPower: (action: string) => void
  snapshots: SnapshotEntry[]
  snapshotsLoading: boolean
  snapshotCreating: boolean
  newSnapName: string
  newSnapDesc: string
  onNewSnapNameChange: (v: string) => void
  onNewSnapDescChange: (v: string) => void
  onCreateSnapshot: () => void
  onDeleteSnapshot: (name: string) => void
  onRollback: (name: string) => void
}

interface MachineDetailPanelProps {
  machine: Machine
  isAdmin: boolean
  profileName: string | null
  deployLog: string[]
  onDownloadLog: () => void
  history: DeploymentEvent[]
  bitlocker?: { key: string | null; pin: string | null }
  onFetchBitlockerKey: () => void
  lapsPassword?: string
  onFetchLapsPassword: () => void
  onSaveUserName: (name: string) => void
  onSaveUserEmail: (email: string) => void
  onSaveNotes: (notes: string) => void
  onClose: () => void
  vm?: VmProps
}

const copy = (text: string, label: string) => {
  navigator.clipboard.writeText(text)
  toast.success(`${label} copié`)
}

export function MachineDetailPanel({
  machine, isAdmin, profileName, deployLog, onDownloadLog, history, bitlocker, onFetchBitlockerKey,
  lapsPassword, onFetchLapsPassword, onSaveUserName, onSaveUserEmail, onSaveNotes, onClose, vm,
}: MachineDetailPanelProps) {
  const logRef = useRef<HTMLPreElement | null>(null)

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [deployLog])

  return (
    <div className="osiris-sheet-overlay" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="osiris-sheet">
        <div className="osiris-modal-header flex-shrink-0">
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-white font-mono truncate">{machine.hostname}</h2>
            <p className="text-[10px] font-mono text-slate-600">{machine.mac.match(/.{1,2}/g)?.join(':').toUpperCase()}{profileName ? ` · ${profileName}` : ''}</p>
            {machine.deploy_mac && (
              /* Adaptateur USB-Ethernet affecté à ce déploiement. Disparaît tout seul
                 une fois la machine déployée : OSIRIS libère le dongle. */
              <p className="text-[10px] font-mono text-amber-600/80" title="Adaptateur USB-Ethernet affecté à ce déploiement — libéré automatiquement une fois la machine déployée">
                dongle : {machine.deploy_mac.match(/.{1,2}/g)?.join(':').toUpperCase()}
              </p>
            )}
          </div>
          <button onClick={onClose} className="text-slate-600 hover:text-slate-300 cursor-pointer transition-colors p-1 flex-shrink-0"><IcoX cls="w-4 h-4" /></button>
        </div>

        <div className="osiris-sheet-body p-5 space-y-4">
          {/* ── Journal de déploiement (style terminal) ── */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-[9px] uppercase tracking-widest text-slate-600">
                {machine.status === 'deploying' ? 'Logs en direct' : 'Journal de déploiement'}
              </p>
              {/* Toujours proposé, même sans ligne à l'écran : le .txt sert l'historique
                  complet, y compris les tentatives précédant le déploiement courant. */}
              <button
                onClick={onDownloadLog}
                className="osiris-btn text-[10px] px-2 py-0.5 flex items-center gap-1"
                title="Télécharger le journal complet (toutes les tentatives) au format .txt"
              >
                <IcoDownload cls="w-3 h-3" /> .txt
              </button>
            </div>
            {deployLog.length > 0 ? (
              <pre ref={logRef} className="osiris-terminal text-[11px] font-mono leading-relaxed whitespace-pre-wrap">
                {deployLog.join('\n')}
                {machine.status === 'deploying' && <span className="osiris-terminal-cursor" />}
              </pre>
            ) : (
              <p className="text-[10px] font-mono text-slate-700">Aucune ligne pour le déploiement en cours</p>
            )}
          </div>

          {/* ── Historique ── */}
          <div>
            <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Historique des déploiements</p>
            {history.length === 0 ? (
              <p className="text-[10px] font-mono text-slate-700">Aucun événement enregistré</p>
            ) : (
              <div className="space-y-px">
                {history.map(ev => {
                  const colors: Record<string, string> = {
                    deployed: 'text-green-400', deploying: 'text-blue-400',
                    pending: 'text-slate-400', failed: 'text-red-400',
                  }
                  const d = new Date(ev.timestamp)
                  const fmt = d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
                  return (
                    <div key={ev.id} className="flex items-center gap-3 text-[10px] font-mono py-0.5">
                      <span className="text-slate-600 shrink-0">{fmt}</span>
                      <span className={`font-bold uppercase w-16 shrink-0 ${colors[ev.status] ?? 'text-slate-400'}`}>{ev.status}</span>
                      <span className="text-slate-500 shrink-0">{ev.os || '-'}</span>
                      <span className="text-slate-600 truncate">{ev.profile_name || '-'}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* ── Smoke tests ── */}
          {machine.smoke_status && (
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">
                Smoke tests
                <span className={`ml-2 font-bold ${machine.smoke_status === 'ok' ? 'text-emerald-500' : 'text-amber-400'}`}>
                  {machine.smoke_status === 'ok' ? 'Tous OK' : 'Alertes detectees'}
                </span>
              </p>
              <div className="space-y-px">
                {(() => {
                  try {
                    const tests: { name: string; ok: boolean; detail?: string }[] = JSON.parse(machine.smoke_results ?? '[]')
                    return tests.map((t, i) => (
                      <div key={i} className="flex items-center gap-2 text-[10px] font-mono py-0.5">
                        <span className={`w-3 h-3 rounded-full shrink-0 ${t.ok ? 'bg-emerald-600' : 'bg-amber-500'}`} />
                        <span className={t.ok ? 'text-slate-400' : 'text-amber-300'}>{t.name}</span>
                        {t.detail && !t.ok && <span className="text-slate-600">- {t.detail}</span>}
                      </div>
                    ))
                  } catch { return null }
                })()}
              </div>
            </div>
          )}

          {/* ── Inventaire materiel ── */}
          {(machine.hw_model || machine.hw_serial || machine.hw_cpu || machine.hw_disk_gb) && (
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Inventaire materiel</p>
              <div className="flex flex-wrap gap-4 text-[10px] font-mono">
                {machine.hw_model && <span className="text-slate-400">{machine.hw_model}</span>}
                {machine.hw_cpu && <span className="text-slate-500">{machine.hw_cpu}</span>}
                {machine.hw_ram_gb ? <span className="text-slate-500">{machine.hw_ram_gb} Go RAM</span> : null}
                {machine.hw_disk_gb ? <span className="text-slate-500">{machine.hw_disk_gb} Go {machine.hw_disk_type || 'disque'}</span> : null}
                {machine.hw_serial && <span className="text-slate-600">S/N : {machine.hw_serial}</span>}
              </div>
            </div>
          )}

          {/* ── BitLocker (admins uniquement) ── */}
          {isAdmin && machine.os === 'windows' && (
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">BitLocker</p>
              {machine.has_bitlocker ? (
                bitlocker ? (
                  <div className="space-y-1.5">
                    {bitlocker.pin && (
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] text-slate-600 w-24 shrink-0">PIN (6 chiffres)</span>
                        <span className="font-mono text-[12px] text-amber-400 tracking-[0.2em]">{bitlocker.pin}</span>
                        <button onClick={() => copy(bitlocker.pin!, 'PIN')} className="osiris-btn text-[10px] px-2 py-0.5">Copier</button>
                      </div>
                    )}
                    {bitlocker.key && (
                      <div className="flex items-center gap-2">
                        <span className="text-[9px] text-slate-600 w-24 shrink-0">Cle 48 chiffres</span>
                        <span className="font-mono text-[10px] text-slate-300 tracking-wider">{bitlocker.key}</span>
                        <button onClick={() => copy(bitlocker.key!, 'Cle')} className="osiris-btn text-[10px] px-2 py-0.5">Copier</button>
                      </div>
                    )}
                  </div>
                ) : (
                  <button onClick={onFetchBitlockerKey} className="osiris-btn text-[10px] px-2 py-1">Afficher les cles</button>
                )
              ) : (
                <span className="text-[10px] font-mono text-slate-700">Aucune cle enregistree</span>
              )}
            </div>
          )}

          {/* ── Mot de passe admin local : LAPS sous Windows, root sous Linux ── */}
          {isAdmin && (
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">
                {machine.os === 'windows'
                  ? 'Mot de passe admin local (LAPS)'
                  : 'Mot de passe root (secours console)'}
              </p>
              {machine.has_laps ? (
                <div className="space-y-1.5">
                  {lapsPassword ? (
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm text-green-400 tracking-wider">{lapsPassword}</span>
                      <button onClick={() => copy(lapsPassword, 'Mot de passe')} className="osiris-btn text-[10px] px-2 py-0.5">Copier</button>
                    </div>
                  ) : (
                    <button onClick={onFetchLapsPassword} className="osiris-btn text-[10px] px-2 py-1">Afficher le mot de passe</button>
                  )}
                  {machine.laps_rotated_at && (
                    <p className="text-[10px] font-mono text-slate-600">
                      Derniere rotation : {new Date(machine.laps_rotated_at).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </p>
                  )}
                </div>
              ) : (
                <span className="text-[10px] font-mono text-slate-700">
                  {machine.os === 'windows'
                    ? 'Aucun mot de passe LAPS enregistre'
                    : 'Aucun mot de passe root enregistre'}
                </span>
              )}
            </div>
          )}

          {/* ── Machine virtuelle (Proxmox) ── */}
          {vm && (
            <div>
              <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Machine virtuelle</p>
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={vm.onRefreshStatus} className="osiris-action-btn" title={vm.powerState ? `VM ${vm.powerState.status} · CPU ${vm.powerState.cpu}% · RAM ${vm.powerState.mem_mb} Mo` : 'Voir statut VM'}>
                  <span className={`inline-block w-2 h-2 rounded-full ${!vm.powerState ? 'bg-slate-600' : vm.powerState.status === 'running' ? 'bg-green-500' : 'bg-red-500'}`} />
                </button>
                <span className="text-[10px] font-mono text-slate-500">
                  {vm.powerState ? `${vm.powerState.status} · CPU ${vm.powerState.cpu}% · RAM ${vm.powerState.mem_mb} Mo` : 'Statut inconnu'}
                </span>
                {vm.powerState?.status === 'running' ? (<>
                  <button onClick={() => vm.onPower('shutdown')} disabled={vm.powerLoading} title="Arrêt propre" className="osiris-action-btn text-[10px]">⏻</button>
                  <button onClick={() => vm.onPower('reboot')} disabled={vm.powerLoading} title="Redémarrer" className="osiris-action-btn text-[10px]">↺</button>
                </>) : vm.powerState?.status === 'stopped' ? (
                  <button onClick={() => vm.onPower('start')} disabled={vm.powerLoading} title="Démarrer la VM" className="osiris-action-btn text-[10px]">▶</button>
                ) : null}
                {vm.consoleUrl && (
                  <a href={vm.consoleUrl} target="_blank" rel="noreferrer" className="osiris-action-btn" title="Console noVNC (ouvre Proxmox)">
                    <IcoTerminal />
                  </a>
                )}
              </div>

              {/* Snapshots */}
              <div className="mt-3 pt-3 border-t border-slate-800/40 space-y-2">
                <p className="text-[9px] uppercase tracking-widest text-slate-600 flex items-center gap-1.5"><IcoCamera cls="w-3 h-3" /> Snapshots</p>
                {vm.snapshotsLoading ? (
                  <p className="text-[10px] font-mono text-slate-600">Chargement…</p>
                ) : vm.snapshots.filter(s => s.name !== 'current').length === 0 ? (
                  <p className="text-[10px] font-mono text-slate-700">Aucun snapshot</p>
                ) : (
                  <div className="space-y-1">
                    {vm.snapshots.filter(s => s.name !== 'current').map(snap => (
                      <div key={snap.name} className="flex items-center gap-2 text-[10px] font-mono py-1 border-b border-slate-800/40 last:border-0 flex-wrap">
                        <span className="text-slate-400 font-semibold truncate" title={snap.name}>{snap.name}</span>
                        <span className="text-slate-600 flex-1 truncate">{snap.description || '—'}</span>
                        <button onClick={() => vm.onRollback(snap.name)} className="osiris-btn text-[9px] px-2 py-0.5 shrink-0">Restaurer</button>
                        <button onClick={() => vm.onDeleteSnapshot(snap.name)} className="osiris-action-btn osiris-action-btn--danger shrink-0"><IcoX cls="w-3 h-3" /></button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-2 pt-1 flex-wrap">
                  <input value={vm.newSnapName} onChange={e => vm.onNewSnapNameChange(e.target.value)} placeholder="Nom du snapshot" className="osiris-input text-[10px] w-36 shrink-0" maxLength={40} />
                  <input value={vm.newSnapDesc} onChange={e => vm.onNewSnapDescChange(e.target.value)} placeholder="Description (optionnel)" className="osiris-input text-[10px] flex-1" />
                  <button onClick={vm.onCreateSnapshot} disabled={vm.snapshotCreating || !vm.newSnapName.trim()} className="osiris-btn text-[10px] px-3 shrink-0">
                    {vm.snapshotCreating ? '…' : 'Créer'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ── Utilisateur affecte ── */}
          <div>
            <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Utilisateur affecte (optionnel)</p>
            <div className="flex gap-2">
              <input
                placeholder="Nom"
                defaultValue={machine.user_name ?? ''}
                onBlur={e => { if (e.target.value !== (machine.user_name ?? '')) onSaveUserName(e.target.value) }}
                className="osiris-input text-xs flex-1"
              />
              <input
                placeholder="Email"
                defaultValue={machine.user_email ?? ''}
                onBlur={e => { if (e.target.value !== (machine.user_email ?? '')) onSaveUserEmail(e.target.value) }}
                className="osiris-input text-xs flex-1"
              />
            </div>
          </div>

          {/* ── Notes ── */}
          <div>
            <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Notes</p>
            <NotesField initial={machine.notes ?? ''} onSave={onSaveNotes} />
          </div>
        </div>
      </div>
    </div>
  )
}

function NotesField({ initial, onSave }: { initial: string; onSave: (notes: string) => void }) {
  const valueRef = useRef(initial)
  return (
    <div className="flex gap-2">
      <textarea
        rows={2}
        placeholder="Notes libres sur cette machine..."
        defaultValue={initial}
        onChange={e => { valueRef.current = e.target.value }}
        className="osiris-input text-[10px] font-mono flex-1 resize-none"
      />
      <button onClick={() => onSave(valueRef.current)} className="osiris-btn text-[10px] px-3 self-start">Sauvegarder</button>
    </div>
  )
}
