// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useState } from 'react'
import { toast } from 'sonner'
import type { Profile, Application, WimFile } from './types'
import { authHeader } from './types'
import { IcoX, IcoPencil } from './icons'
import { APP_LOGOS } from './appIconMap'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

const EMPTY_PROFILE: Partial<Profile> = { os: 'ubuntu', name: '', locale: 'fr_FR.UTF-8', keyboard: 'fr', timezone: 'Europe/Paris', default_user: 'osiris', extra_packages: '', join_domain: true, domain: 'entreprise.local', domain_join_user: '', domain_join_password: '', win_image: '', win_index: 6, enable_bitlocker: true, bitlocker_pin: false, network_drives: '[]', printers: '[]', post_script: '', tv_suffix: '', app_ids: '', laps_rotation_days: 0, machine_type: 'workstation', ssh_authorized_keys: '' }

interface ProfilesSectionProps {
  token: string
  profiles: Profile[]
  apps: Application[]
  onProfilesChanged: () => void
}

// Avertissement affiché quand une golden image est choisie : OSIRIS réinstalle quand même via winget
// les apps cochées ci-dessous (aucune vérification de ce qui est déjà dans l'image), donc ça peut faire
// perdre le bénéfice de vitesse de la golden image si les mêmes apps y sont déjà. Choix explicite de
// l'admin (bouton), jamais d'effacement automatique/silencieux de sa sélection.
function GoldenImageWarning({ winImage, hasSelectedApps, onClearApps }: { winImage: string; hasSelectedApps: boolean; onClearApps: () => void }) {
  if (!winImage.trim()) return null
  return (
    <div className="rounded border border-amber-800/50 bg-amber-950/20 px-3 py-2 flex items-center gap-3 flex-wrap">
      <p className="text-[10px] text-amber-400 flex-1 min-w-[220px]">
        Golden image sélectionnée ({winImage}) — vérifie que les apps cochées ci-dessous n'y sont pas déjà incluses : elles seront réinstallées via winget quand même.
      </p>
      {hasSelectedApps && (
        <button type="button" onClick={onClearApps} className="osiris-btn-ghost text-[10px] text-amber-400 border border-amber-800/60 rounded px-2 py-1 flex-shrink-0">
          Vider la sélection d'apps
        </button>
      )}
    </div>
  )
}

// Grille de cartes pour le sélecteur d'applications, réutilisée pour la création et l'édition de profil.
function AppGrid({ apps, selected, onToggle }: { apps: Application[]; selected: Set<string>; onToggle: (id: number) => void }) {
  return (
    <div className="grid grid-cols-4 sm:grid-cols-5 gap-2">
      {apps.map(a => {
        const on = selected.has(String(a.id))
        const Logo = APP_LOGOS[a.name]
        return (
          <button key={a.id} type="button" onClick={() => onToggle(a.id)} title={a.name}
            className={`osiris-app-card ${on ? 'osiris-app-card--selected' : ''}`}>
            {Logo ? <Logo cls="w-6 h-6" /> : <span className="osiris-app-card-icon">{a.icon}</span>}
            <span className="osiris-app-card-name">{a.name}</span>
          </button>
        )
      })}
    </div>
  )
}

export function ProfilesSection({ token, profiles, apps, onProfilesChanged }: ProfilesSectionProps) {
  const [newProfile, setNewProfile] = useState<Partial<Profile>>(EMPTY_PROFILE)
  const [editingProfile, setEditingProfile] = useState<Profile | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Profile | null>(null)
  const [wims, setWims] = useState<WimFile[]>([])
  const [showWimPicker, setShowWimPicker] = useState<'new' | 'edit' | null>(null)

  const fetchWims = () => {
    fetch(`${API_URL}/wims`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : [])
      .then(data => setWims(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  const handleCreateProfile = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    fetch(`${API_URL}/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify(newProfile),
    })
      .then((res) => { if (!res.ok) throw new Error('Erreur création'); return res.json() })
      .then(() => {
        setNewProfile(EMPTY_PROFILE)
        onProfilesChanged()
        toast.success('Profil créé')
      })
      .catch((err) => toast.error(err.message))
  }

  const handleDeleteProfile = (id: number) => {
    fetch(`${API_URL}/profiles/${id}`, { method: 'DELETE', headers: authHeader(token) })
      .then(r => { if (r.ok) { onProfilesChanged(); toast.success('Profil supprimé') } })
      .catch(() => toast.error('Erreur suppression profil'))
  }

  const handleCloneProfile = (id: number) => {
    fetch(`${API_URL}/profiles/${id}/clone`, { method: 'POST', headers: authHeader(token) })
      .then(r => { if (r.ok) { onProfilesChanged(); toast.success('Profil duplique') } else throw new Error() })
      .catch(() => toast.error('Erreur duplication profil'))
  }

  const handlePatchProfile = (id: number, patch: Partial<Profile>) => {
    fetch(`${API_URL}/profiles/${id}`, {
      method: 'PATCH',
      headers: { ...authHeader(token), 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
      .then(r => { if (r.ok) { onProfilesChanged(); toast.success('Profil mis à jour') } })
      .catch(() => toast.error('Erreur mise à jour profil'))
  }

  return (
    <>
      {/* Profils de déploiement — col-span-2 pour occuper toute la largeur du grid */}
      <div className="osiris-table-wrap p-5 space-y-4 md:col-span-2">
        <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Profils de déploiement</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {profiles.map(p => (
            <div key={p.id} className="flex items-center justify-between py-1.5 px-3 border border-slate-800/60 rounded">
              <div className="min-w-0">
                <span className="text-white text-sm font-medium">{p.name}</span>
                <span className={`ml-2 osiris-os-badge osiris-os-badge--${p.os}`}>{p.os}</span>
                {p.machine_type === 'server' && <span className="ml-1 inline-block border border-amber-700/60 text-amber-500 rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider">serveur</span>}
                <p className="text-[10px] font-mono text-slate-600 mt-0.5">{p.locale} · {p.keyboard} · {p.timezone}</p>
                {p.os === 'windows' && <p className="text-[10px] font-mono text-slate-500">WIM index: <strong className="text-slate-300">{p.win_index}</strong>{p.domain ? ` · ${p.domain}` : ''}</p>}
              </div>
              <div className="flex gap-1 ml-3 flex-shrink-0">
                <button onClick={() => setEditingProfile(p)} className="osiris-action-btn" title="Editer"><IcoPencil /></button>
                <button onClick={() => handleCloneProfile(p.id)} className="osiris-action-btn" title="Dupliquer">⎘</button>
                <button onClick={() => setConfirmDelete(p)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
              </div>
            </div>
          ))}
        </div>
        <form onSubmit={handleCreateProfile} className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-slate-800/50">
          <input required placeholder="Nom du profil" value={newProfile.name ?? ''} onChange={e => setNewProfile({ ...newProfile, name: e.target.value })} className="osiris-input text-xs col-span-2 sm:col-span-1" />
          <select value={newProfile.os} onChange={e => setNewProfile({ ...newProfile, os: e.target.value })} className="osiris-input text-xs">
            <option value="ubuntu">Ubuntu</option>
            <option value="debian">Debian</option>
            <option value="windows">Windows</option>
          </select>
          <input placeholder="Locale" value={newProfile.locale ?? ''} onChange={e => setNewProfile({ ...newProfile, locale: e.target.value })} className="osiris-input text-xs font-mono" />
          <input placeholder="Clavier" value={newProfile.keyboard ?? ''} onChange={e => setNewProfile({ ...newProfile, keyboard: e.target.value })} className="osiris-input text-xs font-mono" />
          <input placeholder="Fuseau horaire" value={newProfile.timezone ?? ''} onChange={e => setNewProfile({ ...newProfile, timezone: e.target.value })} className="osiris-input text-xs font-mono" />
          {(newProfile.os === 'ubuntu' || newProfile.os === 'debian') && (
            <>
              <select value={newProfile.machine_type ?? 'workstation'} onChange={e => setNewProfile({ ...newProfile, machine_type: e.target.value })} className="osiris-input text-xs">
                <option value="workstation">Poste de travail</option>
                <option value="server">Serveur</option>
              </select>
              <input placeholder="Utilisateur local" value={newProfile.default_user ?? ''} onChange={e => setNewProfile({ ...newProfile, default_user: e.target.value })} className="osiris-input text-xs font-mono" />
              <input placeholder="Paquets supplémentaires (htop,vim,...)" value={newProfile.extra_packages ?? ''} onChange={e => setNewProfile({ ...newProfile, extra_packages: e.target.value })} className="osiris-input text-xs font-mono col-span-2 sm:col-span-1" />
              <div className="col-span-2 sm:col-span-3 space-y-1">
                <p className="text-[9px] uppercase tracking-widest text-slate-600">Cles SSH autorisees (une par ligne)</p>
                <textarea rows={3} placeholder="ssh-ed25519 AAAA... user@host" value={newProfile.ssh_authorized_keys ?? ''} onChange={e => setNewProfile({ ...newProfile, ssh_authorized_keys: e.target.value })} className="osiris-input text-[10px] font-mono w-full resize-y" />
                <p className="text-[9px] text-slate-600">Le compte local est créé au premier démarrage s'il n'existe pas, et ces clés lui ouvrent le SSH. Sans clé, une VM clonée reste inaccessible.</p>
              </div>
              <div className="col-span-2 sm:col-span-3 space-y-1">
                <p className="text-[9px] uppercase tracking-widest text-slate-600">Gabarit des VM créées avec ce profil</p>
                <div className="grid grid-cols-4 gap-2">
                  <input type="number" min={1} max={64} title="vCPU" placeholder="vCPU"
                    value={newProfile.vm_vcpus ?? 2}
                    onChange={e => setNewProfile({ ...newProfile, vm_vcpus: Number(e.target.value) })}
                    className="osiris-input text-xs" />
                  <input type="number" min={512} step={512} title="RAM (Mo)" placeholder="RAM Mo"
                    value={newProfile.vm_ram_mb ?? 2048}
                    onChange={e => setNewProfile({ ...newProfile, vm_ram_mb: Number(e.target.value) })}
                    className="osiris-input text-xs" />
                  <input type="number" min={8} title="Disque système (Go)" placeholder="Disque Go"
                    value={newProfile.vm_disk_gb ?? 20}
                    onChange={e => setNewProfile({ ...newProfile, vm_disk_gb: Number(e.target.value) })}
                    className="osiris-input text-xs" />
                  <input type="number" min={0} title="Disque de données /data (Go) — 0 = aucun" placeholder="/data Go"
                    value={newProfile.vm_data_disk_gb ?? 0}
                    onChange={e => setNewProfile({ ...newProfile, vm_data_disk_gb: Number(e.target.value) })}
                    className="osiris-input text-xs" />
                </div>
                <p className="text-[9px] text-slate-600">vCPU · RAM (Mo) · disque système (Go) · disque /data (Go, 0 = aucun). Valeurs proposées par défaut à la création d'une VM.</p>
              </div>
              <label className="col-span-2 sm:col-span-3 flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                <input type="checkbox" checked={newProfile.set_root_password ?? false}
                  onChange={e => setNewProfile({ ...newProfile, set_root_password: e.target.checked })}
                  className="accent-blue-500" />
                Mot de passe root de secours (généré, chiffré, visible dans la fiche machine)
              </label>
            </>
          )}
          {newProfile.os === 'windows' && (
            <>
              <div className="col-span-2 sm:col-span-1 space-y-1">
                <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                  <input type="checkbox" checked={newProfile.enable_bitlocker ?? true} onChange={e => setNewProfile({ ...newProfile, enable_bitlocker: e.target.checked })} className="accent-blue-500" />
                  Activer BitLocker (cle de recuperation dans OSIRIS)
                </label>
                {newProfile.enable_bitlocker && (
                  <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer pl-5">
                    <input type="checkbox" checked={newProfile.bitlocker_pin ?? false} onChange={e => setNewProfile({ ...newProfile, bitlocker_pin: e.target.checked })} className="accent-amber-500" />
                    PIN a 6 chiffres (TPM+PIN - redemarrage manuel requis)
                  </label>
                )}
                <div className="flex items-center gap-2 pt-1">
                  <label className="text-xs text-slate-400 shrink-0">Rotation LAPS</label>
                  <select value={newProfile.laps_rotation_days ?? 0} onChange={e => setNewProfile({ ...newProfile, laps_rotation_days: parseInt(e.target.value) })} className="osiris-input text-xs flex-1">
                    <option value={0}>Desactivee</option>
                    <option value={30}>Tous les 30 jours</option>
                    <option value={60}>Tous les 60 jours</option>
                    <option value={90}>Tous les 90 jours</option>
                    <option value={180}>Tous les 180 jours</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-1 col-span-2 sm:col-span-1">
                <input placeholder="Golden image (vide = install.wim auto)" title="Laissez vide pour utiliser install.wim de l'ISO" value={newProfile.win_image ?? ''} onChange={e => setNewProfile({ ...newProfile, win_image: e.target.value })} className="osiris-input text-xs font-mono flex-1 min-w-0" />
                <button type="button" title="Parcourir les WIM disponibles" onClick={() => { fetchWims(); setShowWimPicker('new') }} className="osiris-btn text-xs px-2 flex-shrink-0">📂</button>
              </div>
              <input type="number" min={1} max={20} placeholder="Index WIM (6=Pro)" title="Index de l'édition dans install.wim (1=Home, 6=Pro)" value={newProfile.win_index ?? 6} onChange={e => setNewProfile({ ...newProfile, win_index: parseInt(e.target.value) || 6 })} className="osiris-input text-xs font-mono" />
            </>
          )}
          <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer col-span-2 sm:col-span-1">
            <input type="checkbox" checked={newProfile.join_domain ?? true} onChange={e => setNewProfile({ ...newProfile, join_domain: e.target.checked })} className="accent-blue-500" />
            Joindre l'AD
          </label>
          {newProfile.join_domain && (
            <>
              <input placeholder="Domaine AD" value={newProfile.domain ?? ''} onChange={e => setNewProfile({ ...newProfile, domain: e.target.value })} className="osiris-input text-xs font-mono" />
              <input placeholder="Compte jonction AD (ex: svc-joinpc)" value={newProfile.domain_join_user ?? ''} onChange={e => setNewProfile({ ...newProfile, domain_join_user: e.target.value })} className="osiris-input text-xs font-mono" />
              <input type="password" placeholder="Mot de passe jonction AD" value={newProfile.domain_join_password ?? ''} onChange={e => setNewProfile({ ...newProfile, domain_join_password: e.target.value })} className="osiris-input text-xs font-mono col-span-2 sm:col-span-1" />
            </>
          )}
          {newProfile.os === 'windows' && (() => {
            const drives: {letter:string,path:string}[] = (() => { try { return JSON.parse(newProfile.network_drives || '[]') } catch { return [] } })()
            const printers: string[] = (() => { try { return JSON.parse(newProfile.printers || '[]') } catch { return [] } })()
            return (
              <div className="col-span-2 sm:col-span-3 space-y-2 pt-1 border-t border-slate-800/40">
                <p className="text-[9px] uppercase tracking-widest text-slate-600">Lecteurs reseau</p>
                {drives.map((d, i) => (
                  <div key={i} className="flex gap-1">
                    <input maxLength={1} placeholder="Z" value={d.letter} onChange={e => { const a=[...drives]; a[i]={...a[i],letter:e.target.value.toUpperCase()}; setNewProfile({...newProfile,network_drives:JSON.stringify(a)}) }} className="osiris-input text-xs font-mono w-12 text-center" />
                    <input placeholder="\\\\serveur\\partage" value={d.path} onChange={e => { const a=[...drives]; a[i]={...a[i],path:e.target.value}; setNewProfile({...newProfile,network_drives:JSON.stringify(a)}) }} className="osiris-input text-xs font-mono flex-1" />
                    <button type="button" onClick={() => { const a=drives.filter((_,j)=>j!==i); setNewProfile({...newProfile,network_drives:JSON.stringify(a)}) }} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                  </div>
                ))}
                <button type="button" onClick={() => setNewProfile({...newProfile,network_drives:JSON.stringify([...drives,{letter:'',path:''}])})} className="osiris-btn-ghost text-xs">+ Ajouter un lecteur</button>
                <p className="text-[9px] uppercase tracking-widest text-slate-600 pt-1">Imprimantes reseau</p>
                {printers.map((pr, i) => (
                  <div key={i} className="flex gap-1">
                    <input placeholder="\\\\serveur\\imprimante" value={pr} onChange={e => { const a=[...printers]; a[i]=e.target.value; setNewProfile({...newProfile,printers:JSON.stringify(a)}) }} className="osiris-input text-xs font-mono flex-1" />
                    <button type="button" onClick={() => { const a=printers.filter((_,j)=>j!==i); setNewProfile({...newProfile,printers:JSON.stringify(a)}) }} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                  </div>
                ))}
                <button type="button" onClick={() => setNewProfile({...newProfile,printers:JSON.stringify([...printers,''])})} className="osiris-btn-ghost text-xs">+ Ajouter une imprimante</button>
              </div>
            )
          })()}
          <div className="col-span-2 sm:col-span-3 space-y-1 pt-1 border-t border-slate-800/40">
            <p className="text-[9px] uppercase tracking-widest text-slate-600">Script post-install ({newProfile.os === 'windows' ? 'PowerShell' : 'Bash'})</p>
            <textarea rows={3} placeholder={newProfile.os === 'windows' ? '# PowerShell — ex: Set-ItemProperty -Path ... ' : '# Bash — ex: apt-get install -y ...'} value={newProfile.post_script ?? ''} onChange={e => setNewProfile({...newProfile, post_script: e.target.value})} className="osiris-input text-[10px] font-mono w-full resize-y col-span-2 sm:col-span-3" />
          </div>
          {/* Sélecteur d'applications */}
          {(() => {
            const os = newProfile.os ?? 'ubuntu'
            const eligible = apps.filter(a => os === "windows" ? (a.winget_id || a.installer_file) : a.apt_package)

            if (eligible.length === 0) return null
            const selected = new Set((newProfile.app_ids ?? '').split(',').filter(Boolean))
            const toggle = (id: number) => {
              const s = new Set(selected)
              if (s.has(String(id))) s.delete(String(id)); else s.add(String(id))
              setNewProfile({ ...newProfile, app_ids: Array.from(s).join(',') })
            }
            return (
              <div className="col-span-2 sm:col-span-3 pt-1 space-y-2">
                <p className="text-[10px] uppercase tracking-widest text-slate-600 mb-1.5">Applications à installer</p>
                {os === 'windows' && (
                  <GoldenImageWarning
                    winImage={newProfile.win_image ?? ''}
                    hasSelectedApps={selected.size > 0}
                    onClearApps={() => setNewProfile({ ...newProfile, app_ids: '' })}
                  />
                )}
                <AppGrid apps={eligible} selected={selected} onToggle={toggle} />
              </div>
            )
          })()}
          <button type="submit" className="osiris-btn text-xs px-3 sm:col-start-3">+ Créer</button>
        </form>
      </div>

      {/* ── Modale : navigateur WIM (z-index au-dessus de la modale d'édition) ── */}
      {showWimPicker && (
        <div className="osiris-overlay" style={{ zIndex: 60 }} onClick={e => { if (e.target === e.currentTarget) setShowWimPicker(null) }}>
          <div className="osiris-modal w-full max-w-md">
            <div className="osiris-modal-header">
              <span className="text-sm font-semibold">Fichiers WIM disponibles</span>
              <button onClick={() => setShowWimPicker(null)} className="osiris-action-btn"><IcoX /></button>
            </div>
            <div className="p-4 space-y-1 max-h-80 overflow-y-auto">
              {wims.length === 0 && <p className="text-xs text-slate-600 font-mono">Aucun fichier WIM trouvé dans {"/srv/data/windows/"}</p>}
              {wims.map(w => (
                <button key={w.name} type="button"
                  onClick={() => {
                    if (showWimPicker === 'new') setNewProfile(p => ({ ...p, win_image: w.is_golden ? w.name : '' }))
                    else if (editingProfile) setEditingProfile({ ...editingProfile, win_image: w.is_golden ? w.name : '' })
                    setShowWimPicker(null)
                  }}
                  className="w-full flex items-center justify-between px-3 py-2 rounded text-xs hover:bg-slate-800 transition-colors text-left"
                >
                  <div className="flex items-center gap-2">
                    <span>{w.is_golden ? '🪙' : '💿'}</span>
                    <span className="font-mono text-white">{w.name}</span>
                    {!w.is_golden && <span className="text-[9px] text-slate-600 uppercase">image de base</span>}
                  </div>
                  <span className="text-slate-500 shrink-0">{w.size_mb.toLocaleString('fr-FR')} Mo</span>
                </button>
              ))}
            </div>
            <div className="px-4 pb-4">
              <p className="text-[10px] text-slate-700 font-mono">Cliquer sur un fichier pour le sélectionner. 🪙 = golden image · 💿 = image Windows de base</p>
            </div>
          </div>
        </div>
      )}

      {/* ── Modale : édition profil ───────────────────────────────────────── */}
      {editingProfile && (
        <div className="osiris-overlay" onClick={e => { if (e.target === e.currentTarget) setEditingProfile(null) }}>
          <div className="osiris-modal">
            <div className="osiris-modal-header">
              <span className="font-semibold text-white">Éditer — {editingProfile.name}</span>
              <button onClick={() => setEditingProfile(null)} className="text-slate-600 hover:text-slate-300 cursor-pointer transition-colors p-1"><IcoX cls="w-4 h-4" /></button>
            </div>
            <div className="p-5 space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <label className="text-xs text-slate-400 self-center col-span-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" checked={editingProfile.join_domain ?? true} onChange={e => setEditingProfile({ ...editingProfile, join_domain: e.target.checked })} className="accent-blue-500" />
                    <span>Joindre l'AD</span>
                  </label>
                </label>
                {editingProfile.join_domain && (<>
                  <label className="text-xs text-slate-400 self-center">Domaine AD</label>
                  <input className="osiris-input text-xs font-mono" defaultValue={editingProfile.domain} onChange={e => setEditingProfile({ ...editingProfile, domain: e.target.value })} />
                  <label className="text-xs text-slate-400 self-center">Compte jonction</label>
                  <input className="osiris-input text-xs font-mono" defaultValue={editingProfile.domain_join_user} onChange={e => setEditingProfile({ ...editingProfile, domain_join_user: e.target.value })} />
                  <label className="text-xs text-slate-400 self-center">Mot de passe jonction</label>
                  <input type="password" className="osiris-input text-xs font-mono" placeholder="(inchangé si vide)" onChange={e => setEditingProfile({ ...editingProfile, domain_join_password: e.target.value })} />
                </>)}
                {editingProfile.os === 'windows' && (<>
                  <div className="col-span-2 space-y-1">
                    <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                      <input type="checkbox" checked={editingProfile.enable_bitlocker ?? true} onChange={e => setEditingProfile({ ...editingProfile, enable_bitlocker: e.target.checked })} className="accent-blue-500" />
                      Activer BitLocker (cle de recuperation dans OSIRIS)
                    </label>
                    {editingProfile.enable_bitlocker && (
                      <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer pl-5">
                        <input type="checkbox" checked={editingProfile.bitlocker_pin ?? false} onChange={e => setEditingProfile({ ...editingProfile, bitlocker_pin: e.target.checked })} className="accent-amber-500" />
                        PIN a 6 chiffres (TPM+PIN - redemarrage manuel requis)
                      </label>
                    )}
                    <div className="flex items-center gap-2 pt-1">
                      <label className="text-xs text-slate-400 shrink-0">Rotation LAPS</label>
                      <select value={editingProfile.laps_rotation_days ?? 0} onChange={e => setEditingProfile({ ...editingProfile, laps_rotation_days: parseInt(e.target.value) })} className="osiris-input text-xs flex-1">
                        <option value={0}>Desactivee</option>
                        <option value={30}>Tous les 30 jours</option>
                        <option value={60}>Tous les 60 jours</option>
                        <option value={90}>Tous les 90 jours</option>
                        <option value={180}>Tous les 180 jours</option>
                      </select>
                    </div>
                  </div>
                  <label className="text-xs text-slate-400 self-center">Index WIM</label>
                  <input type="number" min={1} max={20} className="osiris-input text-xs font-mono" defaultValue={editingProfile.win_index} onChange={e => setEditingProfile({ ...editingProfile, win_index: parseInt(e.target.value) || 1 })} />
                  <label className="text-xs text-slate-400 self-center">Golden image</label>
                  <div className="flex gap-1">
                    <input className="osiris-input text-xs font-mono flex-1 min-w-0" placeholder="vide = install.wim auto" defaultValue={editingProfile.win_image} onChange={e => setEditingProfile({ ...editingProfile, win_image: e.target.value })} />
                    <button type="button" title="Parcourir les WIM disponibles" onClick={() => { fetchWims(); setShowWimPicker('edit') }} className="osiris-btn text-xs px-2 flex-shrink-0">📂</button>
                  </div>
                </>)}
                {(editingProfile.os === 'ubuntu' || editingProfile.os === 'debian') && (<>
                  <label className="text-xs text-slate-400 self-center">Type de machine</label>
                  <select value={editingProfile.machine_type ?? 'workstation'} onChange={e => setEditingProfile({ ...editingProfile, machine_type: e.target.value })} className="osiris-input text-xs">
                    <option value="workstation">Poste de travail</option>
                    <option value="server">Serveur</option>
                  </select>
                </>)}
              </div>
              {(editingProfile.os === 'ubuntu' || editingProfile.os === 'debian') && (
                <div className="pt-2 border-t border-slate-800/40 space-y-1">
                  <p className="text-[9px] uppercase tracking-widest text-slate-600">Cles SSH autorisees (une par ligne)</p>
                  <textarea rows={3} placeholder="ssh-ed25519 AAAA... user@host" defaultValue={editingProfile.ssh_authorized_keys} onChange={e => setEditingProfile({ ...editingProfile, ssh_authorized_keys: e.target.value })} className="osiris-input text-[10px] font-mono w-full resize-y" />
                  <p className="text-[9px] text-slate-600">Le compte local est créé au premier démarrage s'il n'existe pas, et ces clés lui ouvrent le SSH. Sans clé, une VM clonée reste inaccessible.</p>
                  <p className="text-[9px] uppercase tracking-widest text-slate-600 pt-2">Gabarit des VM créées avec ce profil</p>
                  <div className="grid grid-cols-4 gap-2">
                    <input type="number" min={1} max={64} title="vCPU"
                      value={editingProfile.vm_vcpus ?? 2}
                      onChange={e => setEditingProfile({ ...editingProfile, vm_vcpus: Number(e.target.value) })}
                      className="osiris-input text-xs" />
                    <input type="number" min={512} step={512} title="RAM (Mo)"
                      value={editingProfile.vm_ram_mb ?? 2048}
                      onChange={e => setEditingProfile({ ...editingProfile, vm_ram_mb: Number(e.target.value) })}
                      className="osiris-input text-xs" />
                    <input type="number" min={8} title="Disque système (Go)"
                      value={editingProfile.vm_disk_gb ?? 20}
                      onChange={e => setEditingProfile({ ...editingProfile, vm_disk_gb: Number(e.target.value) })}
                      className="osiris-input text-xs" />
                    <input type="number" min={0} title="Disque de données /data (Go) — 0 = aucun"
                      value={editingProfile.vm_data_disk_gb ?? 0}
                      onChange={e => setEditingProfile({ ...editingProfile, vm_data_disk_gb: Number(e.target.value) })}
                      className="osiris-input text-xs" />
                  </div>
                  <p className="text-[9px] text-slate-600">vCPU · RAM (Mo) · disque système (Go) · disque /data (Go, 0 = aucun).</p>
                  <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer pt-1">
                    <input type="checkbox" checked={editingProfile.set_root_password ?? false}
                      onChange={e => setEditingProfile({ ...editingProfile, set_root_password: e.target.checked })}
                      className="accent-blue-500" />
                    Mot de passe root de secours (généré, chiffré, visible dans la fiche machine)
                  </label>
                </div>
              )}
              {editingProfile.os === 'windows' && (() => {
                const drives: {letter:string,path:string}[] = (() => { try { return JSON.parse(editingProfile.network_drives || '[]') } catch { return [] } })()
                const printers: string[] = (() => { try { return JSON.parse(editingProfile.printers || '[]') } catch { return [] } })()
                return (
                  <div className="space-y-2 pt-2 border-t border-slate-800/40">
                    <p className="text-[9px] uppercase tracking-widest text-slate-600">Lecteurs reseau</p>
                    {drives.map((d, i) => (
                      <div key={i} className="flex gap-1">
                        <input maxLength={1} placeholder="Z" value={d.letter} onChange={e => { const a=[...drives]; a[i]={...a[i],letter:e.target.value.toUpperCase()}; setEditingProfile({...editingProfile,network_drives:JSON.stringify(a)}) }} className="osiris-input text-xs font-mono w-12 text-center" />
                        <input placeholder="\\\\serveur\\partage" value={d.path} onChange={e => { const a=[...drives]; a[i]={...a[i],path:e.target.value}; setEditingProfile({...editingProfile,network_drives:JSON.stringify(a)}) }} className="osiris-input text-xs font-mono flex-1" />
                        <button type="button" onClick={() => { const a=drives.filter((_,j)=>j!==i); setEditingProfile({...editingProfile,network_drives:JSON.stringify(a)}) }} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                      </div>
                    ))}
                    <button type="button" onClick={() => setEditingProfile({...editingProfile,network_drives:JSON.stringify([...drives,{letter:'',path:''}])})} className="osiris-btn-ghost text-xs">+ Ajouter un lecteur</button>
                    <p className="text-[9px] uppercase tracking-widest text-slate-600 pt-1">Imprimantes reseau</p>
                    {printers.map((pr, i) => (
                      <div key={i} className="flex gap-1">
                        <input placeholder="\\\\serveur\\imprimante" value={pr} onChange={e => { const a=[...printers]; a[i]=e.target.value; setEditingProfile({...editingProfile,printers:JSON.stringify(a)}) }} className="osiris-input text-xs font-mono flex-1" />
                        <button type="button" onClick={() => { const a=printers.filter((_,j)=>j!==i); setEditingProfile({...editingProfile,printers:JSON.stringify(a)}) }} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                      </div>
                    ))}
                    <button type="button" onClick={() => setEditingProfile({...editingProfile,printers:JSON.stringify([...printers,''])})} className="osiris-btn-ghost text-xs">+ Ajouter une imprimante</button>
                  </div>
                )
              })()}
              <div className="pt-2 border-t border-slate-800/40 space-y-1">
                <p className="text-[9px] uppercase tracking-widest text-slate-600">Script post-install ({editingProfile.os === 'windows' ? 'PowerShell' : 'Bash'})</p>
                <textarea rows={3} placeholder={editingProfile.os === 'windows' ? '# PowerShell' : '# Bash'} defaultValue={editingProfile.post_script} onChange={e => setEditingProfile({...editingProfile, post_script: e.target.value})} className="osiris-input text-[10px] font-mono w-full resize-y" />
              </div>
              {/* Sélecteur d'applications */}
              {(() => {
                const eligible = apps.filter(a => editingProfile.os === "windows" ? (a.winget_id || a.installer_file) : a.apt_package)
                if (eligible.length === 0) return null
                const selected = new Set((editingProfile.app_ids ?? '').split(',').filter(Boolean))
                const toggle = (id: number) => {
                  const s = new Set(selected)
                  if (s.has(String(id))) s.delete(String(id)); else s.add(String(id))
                  setEditingProfile({ ...editingProfile, app_ids: Array.from(s).join(',') })
                }
                return (
                  <div className="space-y-2">
                    <p className="text-[10px] uppercase tracking-widest text-slate-600 mb-1.5">Applications à installer</p>
                    {editingProfile.os === 'windows' && (
                      <GoldenImageWarning
                        winImage={editingProfile.win_image ?? ''}
                        hasSelectedApps={selected.size > 0}
                        onClearApps={() => setEditingProfile({ ...editingProfile, app_ids: '' })}
                      />
                    )}
                    <AppGrid apps={eligible} selected={selected} onToggle={toggle} />
                  </div>
                )
              })()}
              <div className="flex gap-2 justify-end pt-2">
                <button onClick={() => setEditingProfile(null)} className="osiris-btn-ghost text-xs">Annuler</button>
                <button onClick={() => { handlePatchProfile(editingProfile.id!, editingProfile); setEditingProfile(null) }} className="osiris-btn text-xs">Enregistrer</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Modale : confirmation suppression profil (z-index au-dessus de l'édition) ── */}
      {confirmDelete && (
        <div className="osiris-overlay" style={{ zIndex: 60 }} onClick={e => { if (e.target === e.currentTarget) setConfirmDelete(null) }}>
          <div className="osiris-modal osiris-modal--danger">
            <div className="osiris-modal-header" style={{ borderBottomColor: 'rgba(185,28,28,0.25)' }}>
              <h2 className="text-xs font-bold uppercase tracking-widest text-red-400">Confirmer la suppression</h2>
            </div>
            <div className="p-6 space-y-5">
              <p className="text-sm text-slate-400">
                Le profil <span className="font-mono text-white">{confirmDelete.name}</span> sera définitivement supprimé.
              </p>
              <p className="text-xs text-slate-600">Cette action est <span className="text-red-400 font-semibold">irréversible</span>.</p>
              <div className="flex gap-3 justify-end">
                <button onClick={() => setConfirmDelete(null)} className="osiris-btn-ghost">Annuler</button>
                <button onClick={() => { handleDeleteProfile(confirmDelete.id); setConfirmDelete(null) }} className="osiris-btn osiris-btn--danger">Supprimer</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
