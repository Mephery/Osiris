// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { QRCodeSVG } from 'qrcode.react'
import { authHeader } from './types'
import type { ApiKey } from './types'
import { IcoX } from './icons'
import { IntegrationsTab } from './IntegrationsTab'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

export function SettingsModal({ token, onClose }: { token: string; onClose: () => void }) {
  const [settingsTab, setSettingsTab] = useState<'password' | 'totp' | 'apikeys' | 'integrations'>('password')
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([])
  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNew, setPwNew]         = useState('')
  const [pwConfirm, setPwConfirm] = useState('')
  const [pwError, setPwError]     = useState<string | null>(null)
  const [pwSuccess, setPwSuccess] = useState(false)
  const [pwLoading, setPwLoading] = useState(false)
  const [totpSetup, setTotpSetup] = useState<{secret: string, uri: string} | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [totpEnabled, setTotpEnabled] = useState(false)
  const [totpDisablePassword, setTotpDisablePassword] = useState('')
  const [totpStep, setTotpStep] = useState<null | 'setup' | 'confirm_disable'>(null)

  const fetchTotpStatus = useCallback(() => {
    fetch(`${API_URL}/auth/totp/status`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setTotpEnabled(data.totp_enabled) })
      .catch(() => {})
  }, [token])

  const fetchApiKeys = useCallback(() => {
    fetch(`${API_URL}/auth/api-keys`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : [])
      .then(setApiKeys)
      .catch(() => {})
  }, [token])

  useEffect(() => { fetchTotpStatus(); fetchApiKeys() }, [token, fetchTotpStatus, fetchApiKeys])

  const startTotpSetup = () => {
    fetch(`${API_URL}/auth/totp/setup`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setTotpSetup({ secret: data.secret, uri: data.uri }); setTotpStep('setup'); setTotpCode('') })
      .catch(() => toast.error('Impossible de demarrer la configuration 2FA'))
  }

  const confirmTotpEnable = () => {
    if (!totpSetup) return
    fetch(`${API_URL}/auth/totp/enable`, {
      method: 'POST',
      headers: { ...authHeader(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ secret: totpSetup.secret, code: totpCode }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(() => { setTotpEnabled(true); setTotpStep(null); setTotpSetup(null); toast.success('Double authentification activee') })
      .catch(() => toast.error('Code incorrect ou expire'))
  }

  const disableTotp = () => {
    fetch(`${API_URL}/auth/totp/disable`, {
      method: 'POST',
      headers: { ...authHeader(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: totpDisablePassword }),
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(() => { setTotpEnabled(false); setTotpStep(null); setTotpDisablePassword(''); toast.success('Double authentification desactivee') })
      .catch(() => toast.error('Mot de passe incorrect'))
  }

  const createApiKey = () => {
    if (!newKeyName.trim()) return
    fetch(`${API_URL}/auth/api-keys`, {
      method: 'POST',
      headers: { ...authHeader(token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newKeyName.trim() }),
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setCreatedKey(data.key); setNewKeyName(''); fetchApiKeys(); toast.success('Cle creee') })
      .catch(() => toast.error('Erreur creation cle'))
  }

  const revokeApiKey = (id: number) => {
    fetch(`${API_URL}/auth/api-keys/${id}`, { method: 'DELETE', headers: authHeader(token) })
      .then(r => { if (r.ok) { fetchApiKeys(); toast.success('Cle revoquee') } else throw new Error() })
      .catch(() => toast.error('Erreur revocation'))
  }

  const handlePasswordChange = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setPwError(null)
    if (pwNew !== pwConfirm) { setPwError('Les deux nouveaux mots de passe ne correspondent pas.'); return }
    if (pwNew.length < 8) { setPwError('Le nouveau mot de passe doit faire au moins 8 caractères.'); return }
    setPwLoading(true)
    fetch(`${API_URL}/auth/me/password`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify({ current_password: pwCurrent, new_password: pwNew }),
    })
      .then(async (res) => {
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Erreur') }
        setPwSuccess(true)
        setPwLoading(false)
      })
      .catch((err) => { setPwError(err.message); setPwLoading(false) })
  }

  return (
    <div className="osiris-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="osiris-modal" style={{ maxWidth: '480px' }}>
        <div className="osiris-modal-header">
          <h2 className="text-xs font-bold uppercase tracking-widest text-white">Parametres du compte</h2>
          <button onClick={onClose} className="text-slate-600 hover:text-slate-300 cursor-pointer transition-colors p-1"><IcoX cls="w-4 h-4" /></button>
        </div>
        {/* Sous-onglets */}
        <div className="flex border-b border-slate-800">
          {([
            { id: 'password', label: 'Mot de passe' },
            { id: 'totp', label: '2FA' },
            { id: 'apikeys', label: 'Cles API' },
            { id: 'integrations', label: 'Integrations' },
          ] as const).map(t => (
            <button key={t.id} onClick={() => { setSettingsTab(t.id); if (t.id === 'apikeys') fetchApiKeys() }}
              className={`px-5 py-2.5 text-xs font-semibold tracking-wide border-b-2 transition-colors cursor-pointer ${settingsTab === t.id ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-600 hover:text-slate-400'}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* Onglet mot de passe */}
        {settingsTab === 'password' && (
          pwSuccess ? (
            <div className="p-6 space-y-5">
              <div className="border-l-2 border-emerald-700 pl-3 py-1">
                <p className="text-emerald-400 text-sm font-mono">Mot de passe mis a jour avec succes.</p>
              </div>
              <button onClick={onClose} className="osiris-btn w-full justify-center">Fermer</button>
            </div>
          ) : (
            <form onSubmit={handlePasswordChange} className="p-6 space-y-4">
              {pwError && <div className="border-l-2 border-red-700 pl-3 py-1"><p className="text-red-400 text-xs font-mono">{pwError}</p></div>}
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Mot de passe actuel</label>
                <input required type="password" placeholder="..." value={pwCurrent} onChange={e => setPwCurrent(e.target.value)} className="osiris-input" autoFocus />
              </div>
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Nouveau mot de passe</label>
                <input required type="password" placeholder="8 caracteres minimum" value={pwNew} onChange={e => setPwNew(e.target.value)} className="osiris-input" />
              </div>
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Confirmer</label>
                <input required type="password" placeholder="..." value={pwConfirm} onChange={e => setPwConfirm(e.target.value)} className="osiris-input" />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={onClose} className="osiris-btn-ghost">Annuler</button>
                <button type="submit" disabled={pwLoading} className="osiris-btn">{pwLoading ? 'Mise a jour...' : 'Changer le mot de passe'}</button>
              </div>
            </form>
          )
        )}

        {/* Onglet 2FA */}
        {/* Onglet cles API */}
        {settingsTab === 'apikeys' && (
          <div className="p-6 space-y-4">
            {/* Cle nouvellement creee - a copier maintenant */}
            {createdKey && (
              <div className="border border-amber-800/60 bg-amber-950/30 rounded p-3 space-y-2">
                <p className="text-amber-400 text-xs font-semibold">Copiez cette cle maintenant - elle ne sera plus affichee.</p>
                <div className="flex gap-2 items-center">
                  <code className="text-amber-300 text-[11px] font-mono break-all flex-1">{createdKey}</code>
                  <button onClick={() => { navigator.clipboard.writeText(createdKey); toast.success('Cle copiee') }} className="osiris-btn text-xs shrink-0">Copier</button>
                </div>
                <button onClick={() => setCreatedKey(null)} className="osiris-btn-ghost text-[10px]">J'ai copie ma cle</button>
              </div>
            )}

            {/* Liste des cles */}
            {apiKeys.length > 0 ? (
              <div className="space-y-1">
                {apiKeys.map((k) => (
                  <div key={k.id} className="flex items-center justify-between py-2 px-3 border border-slate-800/60 rounded">
                    <div>
                      <span className="text-white text-xs font-medium">{k.name}</span>
                      <span className="text-slate-700 text-[10px] font-mono ml-2">{k.prefix}...</span>
                      <p className="text-[10px] text-slate-700 mt-0.5">
                        Creee le {new Date(k.created_at).toLocaleDateString('fr-FR')}
                        {k.last_used_at ? ` - utilisee le ${new Date(k.last_used_at).toLocaleDateString('fr-FR')}` : ' - jamais utilisee'}
                      </p>
                    </div>
                    <button onClick={() => revokeApiKey(k.id)} className="osiris-action-btn osiris-action-btn--danger shrink-0" title="Revoquer"><IcoX /></button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-slate-700 text-xs">Aucune cle API pour l'instant.</p>
            )}

            {/* Creer une nouvelle cle */}
            <div className="pt-2 border-t border-slate-800/40 space-y-2">
              <p className="text-[9px] uppercase tracking-widest text-slate-600">Nouvelle cle</p>
              <div className="flex gap-2">
                <input placeholder="Nom (ex: ConnectWise, Grafana, Script backup)" value={newKeyName} onChange={e => setNewKeyName(e.target.value)} onKeyDown={e => e.key === 'Enter' && createApiKey()} className="osiris-input text-xs flex-1" autoFocus />
                <button onClick={createApiKey} disabled={!newKeyName.trim()} className="osiris-btn text-xs shrink-0">Generer</button>
              </div>
              <p className="text-[10px] text-slate-700">Utilisez la cle dans l'en-tete HTTP : <code className="text-slate-500">Authorization: Bearer osiris_sk_...</code></p>
            </div>
          </div>
        )}

        {settingsTab === 'integrations' && (
          <IntegrationsTab apiUrl={API_URL} />
        )}

        {settingsTab === 'totp' && (
          <div className="p-6 space-y-4">
            {totpEnabled ? (
              totpStep === 'confirm_disable' ? (
                <div className="space-y-3">
                  <p className="text-xs text-slate-400">Saisissez votre mot de passe pour desactiver le 2FA :</p>
                  <div className="flex gap-2">
                    <input type="password" placeholder="Mot de passe" value={totpDisablePassword} onChange={e => setTotpDisablePassword(e.target.value)} className="osiris-input text-xs flex-1" autoFocus />
                    <button onClick={disableTotp} className="osiris-btn text-xs">Confirmer</button>
                    <button onClick={() => setTotpStep(null)} className="osiris-btn-ghost text-xs">Annuler</button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center gap-3">
                    <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
                    <span className="text-green-400 text-sm">Double authentification active</span>
                  </div>
                  <p className="text-xs text-slate-600">Votre compte est protege par un code TOTP a chaque connexion.</p>
                  <button onClick={() => setTotpStep('confirm_disable')} className="osiris-btn-ghost text-xs text-red-400 border-red-900">Desactiver le 2FA</button>
                </div>
              )
            ) : totpStep === 'setup' && totpSetup ? (
              <div className="space-y-4">
                <p className="text-xs text-slate-400">Scannez ce QR code avec Google Authenticator, Authy ou une app compatible :</p>
                <div className="flex justify-center p-4 bg-slate-950 rounded border border-slate-800">
                  <QRCodeSVG value={totpSetup.uri} size={180} bgColor="#020817" fgColor="#e2e8f0" />
                </div>
                <p className="text-[10px] text-slate-700 font-mono break-all">Secret manuel : {totpSetup.secret}</p>
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Code de confirmation</label>
                  <div className="flex gap-2">
                    <input maxLength={6} placeholder="000000" value={totpCode} onChange={e => setTotpCode(e.target.value.replace(/\D/g, ''))} onKeyDown={e => e.key === 'Enter' && confirmTotpEnable()} className="osiris-input text-center text-lg tracking-widest font-mono flex-1" autoFocus />
                    <button onClick={confirmTotpEnable} className="osiris-btn">Activer</button>
                  </div>
                </div>
                <button onClick={() => { setTotpStep(null); setTotpSetup(null) }} className="osiris-btn-ghost text-xs">Annuler</button>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <span className="w-2 h-2 rounded-full bg-slate-700 inline-block" />
                  <span className="text-slate-400 text-sm">Double authentification inactive</span>
                </div>
                <p className="text-xs text-slate-600">Activez le 2FA pour proteger votre compte avec un code genere par une application d'authentification.</p>
                <button onClick={startTotpSetup} className="osiris-btn text-xs">Configurer le 2FA</button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
