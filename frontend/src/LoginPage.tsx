// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useState } from 'react'
import type { AuthState } from './types'
import { IcoOsiris } from './icons'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

export function LoginPage({ onLogin, onTotpRequired }: { onLogin: (auth: AuthState) => void, onTotpRequired: (temp_token: string) => void }) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState<string | null>(null)
  const [loading, setLoading]   = useState(false)

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    fetch(`${API_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json()
          throw new Error(err.detail || 'Identifiants incorrects')
        }
        return res.json()
      })
      .then((data) => {
        if (data.totp_required) { onTotpRequired(data.temp_token); setLoading(false); return }
        onLogin({ token: data.access_token, email: data.email, role: data.role })
      })
      .catch((err) => { setError(err.message); setLoading(false) })
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-3 mb-8">
          <IcoOsiris cls="w-11 h-8 text-blue-500" />
          <span className="text-2xl font-black tracking-[0.22em] text-white uppercase">Osiris</span>
        </div>

        <div className="osiris-modal">
          <div className="osiris-modal-header">
            <h2 className="text-xs font-bold uppercase tracking-widest text-white">Connexion</h2>
          </div>
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            {error && (
              <div className="border-l-2 border-red-700 pl-3 py-1">
                <p className="text-red-400 text-xs font-mono">{error}</p>
              </div>
            )}
            <div className="space-y-1.5">
              <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Email</label>
              <input required type="email" placeholder="admin@osiris.local"
                value={email} onChange={(e) => setEmail(e.target.value)}
                className="osiris-input" autoFocus />
            </div>
            <div className="space-y-1.5">
              <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Mot de passe</label>
              <input required type="password" placeholder="••••••••"
                value={password} onChange={(e) => setPassword(e.target.value)}
                className="osiris-input" />
            </div>
            <button type="submit" disabled={loading} className="osiris-btn w-full justify-center mt-2">
              {loading ? 'Connexion…' : 'Se connecter'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
