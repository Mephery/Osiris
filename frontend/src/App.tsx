import { useEffect, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

interface AuthState {
  token: string;
  email: string;
  role: string;
}

interface Organization {
  id: number;
  name: string;
  slug: string;
}

interface Machine {
  id?: number;
  mac: string;
  client: string;
  os: string;
  hostname: string;
  ou: string;
  status?: string;
  deployed_at?: string | null;
  organization_id?: number | null;
}

const EMPTY_FORM: Machine = { mac: '', client: '', os: 'windows', hostname: '', ou: '', organization_id: null }

// ── Helpers ────────────────────────────────────────────────────────────────────

function authHeader(token: string) {
  return { 'Authorization': `Bearer ${token}` }
}

// ── Composant Login ────────────────────────────────────────────────────────────

function LoginPage({ onLogin }: { onLogin: (auth: AuthState) => void }) {
  const [email, setEmail]       = useState('')
  const [password, setPassword] = useState('')
  const [error, setError]       = useState<string | null>(null)
  const [loading, setLoading]   = useState(false)

  const handleSubmit = (e: React.FormEvent) => {
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
      .then((data) => onLogin({ token: data.access_token, email: data.email, role: data.role }))
      .catch((err) => { setError(err.message); setLoading(false) })
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-3 mb-8">
          <span className="osiris-icon text-blue-500 text-2xl">⊙</span>
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

// ── Composant principal ────────────────────────────────────────────────────────

export default function App() {
  const [auth, setAuth] = useState<AuthState | null>(null)

  const [machines, setMachines]     = useState<Machine[]>([])
  const [orgs, setOrgs]             = useState<Organization[]>([])
  const [selectedOrg, setSelectedOrg] = useState<number | null>(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState<string | null>(null)

  // Modale formulaire (création ET édition)
  const [isModalOpen, setIsModalOpen]   = useState(false)
  const [editingMac, setEditingMac]     = useState<string | null>(null)
  const [formData, setFormData]         = useState<Machine>(EMPTY_FORM)
  const [submitError, setSubmitError]   = useState<string | null>(null)

  // Confirmation suppression
  const [deletingMac, setDeletingMac]   = useState<string | null>(null)

  // Mot de passe one-time
  const [oneTimePassword, setOneTimePassword] = useState<{ hostname: string; password: string } | null>(null)

  // ── Section admin : gestion des orgs et users ──────────────────────────────
  const [showAdmin, setShowAdmin]       = useState(false)
  const [newOrgName, setNewOrgName]     = useState('')
  const [newOrgSlug, setNewOrgSlug]     = useState('')
  const [users, setUsers]               = useState<{ id: number; email: string; role: string }[]>([])
  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserPass, setNewUserPass]   = useState('')
  const [newUserRole, setNewUserRole]   = useState('technician')

  // ── Chargement des données ──────────────────────────────────────────────────

  const fetchAll = (token: string, orgFilter: number | null = null) => {
    setLoading(true)
    const url = orgFilter ? `${API_URL}/machines?org_id=${orgFilter}` : `${API_URL}/machines`
    fetch(url, { headers: authHeader(token) })
      .then((res) => { if (!res.ok) throw new Error("Erreur API"); return res.json() })
      .then((data) => { setMachines(data); setLoading(false) })
      .catch((err) => { setError(err.message); setLoading(false) })
  }

  const fetchOrgs = (token: string) => {
    fetch(`${API_URL}/organizations`, { headers: authHeader(token) })
      .then((res) => res.json())
      .then(setOrgs)
      .catch(() => {})
  }

  const fetchUsers = (token: string) => {
    fetch(`${API_URL}/users`, { headers: authHeader(token) })
      .then((res) => res.json())
      .then(setUsers)
      .catch(() => {})
  }

  useEffect(() => {
    if (!auth) return
    fetchAll(auth.token, selectedOrg)
    fetchOrgs(auth.token)
    if (auth.role === 'admin') fetchUsers(auth.token)
  }, [auth, selectedOrg])

  if (!auth) return <LoginPage onLogin={setAuth} />

  // ── Modale helpers ──────────────────────────────────────────────────────────

  const openEdit = (machine: Machine) => {
    setEditingMac(machine.mac)
    setFormData({ ...machine })
    setSubmitError(null)
    setIsModalOpen(true)
  }

  const openCreate = () => {
    setEditingMac(null)
    setFormData({ ...EMPTY_FORM, organization_id: selectedOrg })
    setSubmitError(null)
    setIsModalOpen(true)
  }

  const closeModal = () => { setIsModalOpen(false); setEditingMac(null) }

  // ── Soumission formulaire machine ───────────────────────────────────────────

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitError(null)
    const isEdit = editingMac !== null
    const url    = isEdit ? `${API_URL}/machines/${editingMac}` : `${API_URL}/machines`
    const method = isEdit ? 'PATCH' : 'POST'
    fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify(formData),
    })
      .then(async (res) => {
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "Erreur") }
        return isEdit ? null : res.json()
      })
      .then((data) => {
        closeModal()
        if (data?.password) setOneTimePassword({ hostname: data.hostname, password: data.password })
        else fetchAll(auth.token, selectedOrg)
      })
      .catch((err) => setSubmitError(err.message))
  }

  // ── Suppression machine ─────────────────────────────────────────────────────

  const handleDelete = (mac: string) => {
    fetch(`${API_URL}/machines/${mac}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then((res) => { if (!res.ok && res.status !== 204) throw new Error('Erreur suppression') })
      .then(() => { setDeletingMac(null); fetchAll(auth.token, selectedOrg) })
      .catch((err) => alert(err.message))
  }

  // ── Admin : créer org ───────────────────────────────────────────────────────

  const handleCreateOrg = (e: React.FormEvent) => {
    e.preventDefault()
    fetch(`${API_URL}/organizations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ name: newOrgName, slug: newOrgSlug }),
    })
      .then((res) => res.json())
      .then(() => { setNewOrgName(''); setNewOrgSlug(''); fetchOrgs(auth.token) })
      .catch(() => {})
  }

  // ── Admin : créer utilisateur ───────────────────────────────────────────────

  const handleCreateUser = (e: React.FormEvent) => {
    e.preventDefault()
    fetch(`${API_URL}/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ email: newUserEmail, password: newUserPass, role: newUserRole }),
    })
      .then((res) => res.json())
      .then(() => { setNewUserEmail(''); setNewUserPass(''); fetchUsers(auth.token) })
      .catch(() => {})
  }

  const orgName = (id: number | null | undefined) => orgs.find(o => o.id === id)?.name ?? '—'

  // ── Rendu ───────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen text-slate-100 font-sans antialiased">

      {/* ── En-tête ────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-10 border-b border-slate-800/60 bg-[#070b14]/90 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2.5">
              <span className="osiris-icon text-blue-500">⊙</span>
              <span className="text-lg font-black tracking-[0.22em] text-white uppercase select-none">Osiris</span>
            </div>
            <div className="hidden sm:flex items-center gap-2 text-[11px] font-mono text-slate-600 border-l border-slate-800 pl-5">
              <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${error ? 'bg-red-500' : 'bg-emerald-500 animate-pulse'}`} />
              {error ? 'API hors ligne' : loading ? 'Connexion…' : 'Connecté'}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {auth.role === 'admin' && (
              <button onClick={() => setShowAdmin(!showAdmin)} className={`osiris-btn-ghost text-xs ${showAdmin ? 'text-blue-400' : ''}`}>
                ⚙ Administration
              </button>
            )}
            <span className="text-xs font-mono text-slate-700 hidden sm:block">{auth.email}</span>
            <button onClick={() => setAuth(null)} className="osiris-btn-ghost text-xs">Déconnexion</button>
            <button onClick={openCreate} className="osiris-btn">+ Enregistrer un PC</button>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-8 space-y-8">

        {/* ── Panel admin ──────────────────────────────────────────────────── */}
        {showAdmin && auth.role === 'admin' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

            {/* Organisations */}
            <div className="osiris-table-wrap p-5 space-y-4">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Organisations clients</h2>
              <ul className="space-y-1">
                {orgs.map(org => (
                  <li key={org.id} className="flex items-center justify-between text-sm py-1 border-b border-slate-800/50">
                    <span className="text-white font-medium">{org.name}</span>
                    <span className="font-mono text-xs text-slate-600">{org.slug}</span>
                  </li>
                ))}
                {orgs.length === 0 && <li className="text-slate-700 text-xs font-mono">Aucune organisation</li>}
              </ul>
              <form onSubmit={handleCreateOrg} className="flex gap-2 pt-2">
                <input required placeholder="Nom" value={newOrgName} onChange={e => setNewOrgName(e.target.value)} className="osiris-input text-xs flex-1" />
                <input required placeholder="slug" value={newOrgSlug} onChange={e => setNewOrgSlug(e.target.value)} className="osiris-input text-xs w-28 font-mono" />
                <button type="submit" className="osiris-btn text-xs px-3">+</button>
              </form>
            </div>

            {/* Utilisateurs */}
            <div className="osiris-table-wrap p-5 space-y-4">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Utilisateurs</h2>
              <ul className="space-y-1">
                {users.map(u => (
                  <li key={u.id} className="flex items-center justify-between text-sm py-1 border-b border-slate-800/50">
                    <span className="text-white">{u.email}</span>
                    <span className={`osiris-os-badge ${u.role === 'admin' ? 'osiris-os-badge--windows' : 'osiris-os-badge--ubuntu'}`}>{u.role}</span>
                  </li>
                ))}
              </ul>
              <form onSubmit={handleCreateUser} className="space-y-2 pt-2">
                <div className="flex gap-2">
                  <input required type="email" placeholder="Email" value={newUserEmail} onChange={e => setNewUserEmail(e.target.value)} className="osiris-input text-xs flex-1" />
                  <select value={newUserRole} onChange={e => setNewUserRole(e.target.value)} className="osiris-input text-xs w-32">
                    <option value="technician">Technicien</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div className="flex gap-2">
                  <input required type="password" placeholder="Mot de passe" value={newUserPass} onChange={e => setNewUserPass(e.target.value)} className="osiris-input text-xs flex-1" />
                  <button type="submit" className="osiris-btn text-xs px-3">+</button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* ── Filtre par organisation + compteur ───────────────────────────── */}
        <div className="flex items-center justify-between">
          <div className="flex items-baseline gap-3">
            <h1 className="text-xl font-bold tracking-tight text-white">Parc de déploiement</h1>
            {!loading && !error && (
              <span className="text-xs font-mono text-slate-600">
                {machines.length} machine{machines.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest text-slate-600 font-semibold">Client</span>
            <select
              value={selectedOrg ?? ''}
              onChange={(e) => setSelectedOrg(e.target.value ? Number(e.target.value) : null)}
              className="osiris-input text-xs w-44"
            >
              <option value="">Tous les clients</option>
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </div>
        </div>

        {/* ── Tableau des machines ─────────────────────────────────────────── */}
        {loading && (
          <div className="flex items-center gap-2.5 text-slate-600 font-mono text-xs py-6">
            <span className="inline-block w-1.5 h-1.5 bg-blue-600 rounded-full animate-ping" />
            Chargement…
          </div>
        )}
        {error && <div className="border-l-2 border-red-700 pl-4 py-2"><p className="text-red-400 text-sm font-mono">{error}</p></div>}

        {!loading && !error && (
          <div className="osiris-table-wrap overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800/80">
                  {["Nom d'hôte", "Adresse MAC", "Client / Org", "OS", "Statut", "OU / Actions"].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {machines.length === 0 ? (
                  <tr><td colSpan={6} className="px-4 py-16 text-center text-slate-700 font-mono text-xs">Aucune machine enregistrée</td></tr>
                ) : machines.map((machine) => (
                  <tr key={machine.id} className="osiris-row">
                    <td className="px-4 py-3 font-mono font-semibold text-white">{machine.hostname}</td>
                    <td className="px-4 py-3 font-mono text-xs tracking-wider text-slate-500">
                      {machine.mac.match(/.{1,2}/g)?.join(':').toUpperCase()}
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-slate-300">{machine.client}</span>
                      {machine.organization_id && (
                        <span className="block text-[10px] font-mono text-slate-700">{orgName(machine.organization_id)}</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`osiris-os-badge osiris-os-badge--${machine.os}`}>
                        {machine.os === 'windows' ? 'Windows' : machine.os === 'ubuntu' ? 'Ubuntu' : machine.os}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`osiris-status-badge osiris-status--${machine.status ?? 'pending'}`}>
                        {machine.status ?? 'pending'}
                      </span>
                      {machine.deployed_at && (
                        <span className="block text-[10px] font-mono text-slate-700 mt-0.5">
                          {new Date(machine.deployed_at).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-xs text-slate-600 truncate max-w-[140px]" title={machine.ou}>{machine.ou || '—'}</span>
                        <div className="flex items-center gap-1 ml-auto flex-shrink-0">
                          <button onClick={() => openEdit(machine)} className="osiris-action-btn" title="Modifier">✎</button>
                          {auth.role === 'admin' && (
                            <button onClick={() => setDeletingMac(machine.mac)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer">✕</button>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Modale : enregistrement / édition ─────────────────────────────── */}
      {isModalOpen && (
        <div className="osiris-overlay" onClick={(e) => { if (e.target === e.currentTarget) closeModal() }}>
          <div className="osiris-modal">
            <div className="osiris-modal-header">
              <h2 className="text-xs font-bold uppercase tracking-widest text-white">
                {editingMac ? 'Modifier la machine' : 'Nouvel enregistrement iPXE'}
              </h2>
              <button onClick={closeModal} className="text-slate-700 hover:text-slate-300 text-2xl leading-none cursor-pointer transition-colors">×</button>
            </div>
            {submitError && <div className="mx-6 mt-4 border-l-2 border-red-700 pl-3 py-1"><p className="text-red-400 text-xs font-mono">{submitError}</p></div>}
            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                  Adresse MAC {editingMac && <span className="text-slate-700 normal-case">(non modifiable)</span>}
                </label>
                <input required type="text" placeholder="00:11:22:AA:BB:CC"
                  value={formData.mac} onChange={(e) => setFormData({ ...formData, mac: e.target.value })}
                  disabled={!!editingMac} className={`osiris-input font-mono ${editingMac ? 'opacity-40 cursor-not-allowed' : ''}`} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Nom d'hôte</label>
                  <input required type="text" placeholder="PC-PROD-01"
                    value={formData.hostname} onChange={(e) => setFormData({ ...formData, hostname: e.target.value })}
                    className="osiris-input font-mono" />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">OS cible</label>
                  <select value={formData.os} onChange={(e) => setFormData({ ...formData, os: e.target.value, ou: '' })} className="osiris-input">
                    <option value="windows">Windows</option>
                    <option value="ubuntu">Ubuntu</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Client</label>
                  <input required type="text" placeholder="Acme Corp."
                    value={formData.client} onChange={(e) => setFormData({ ...formData, client: e.target.value })}
                    className="osiris-input" />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Organisation</label>
                  <select value={formData.organization_id ?? ''} onChange={(e) => setFormData({ ...formData, organization_id: e.target.value ? Number(e.target.value) : null })} className="osiris-input">
                    <option value="">— Sans organisation —</option>
                    {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </div>
              </div>
              {formData.os === 'windows' && (
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Chemin OU Active Directory</label>
                  <input required type="text" placeholder="OU=Workstations,DC=domain,DC=local"
                    value={formData.ou} onChange={(e) => setFormData({ ...formData, ou: e.target.value })}
                    className="osiris-input font-mono text-xs" />
                </div>
              )}
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={closeModal} className="osiris-btn-ghost">Annuler</button>
                <button type="submit" className="osiris-btn">{editingMac ? 'Enregistrer les modifications' : 'Enregistrer'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modale : confirmation suppression ─────────────────────────────── */}
      {deletingMac && (
        <div className="osiris-overlay">
          <div className="osiris-modal osiris-modal--danger">
            <div className="osiris-modal-header" style={{ borderBottomColor: 'rgba(185,28,28,0.25)' }}>
              <h2 className="text-xs font-bold uppercase tracking-widest text-red-400">Confirmer la suppression</h2>
            </div>
            <div className="p-6 space-y-5">
              <p className="text-sm text-slate-400">
                La machine <span className="font-mono text-white">{machines.find(m => m.mac === deletingMac)?.hostname ?? deletingMac}</span> sera définitivement supprimée.
              </p>
              <p className="text-xs text-slate-600">Cette action est <span className="text-red-400 font-semibold">irréversible</span>.</p>
              <div className="flex gap-3 justify-end">
                <button onClick={() => setDeletingMac(null)} className="osiris-btn-ghost">Annuler</button>
                <button onClick={() => handleDelete(deletingMac)} className="osiris-btn osiris-btn--danger">Supprimer</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Modale : mot de passe one-time ────────────────────────────────── */}
      {oneTimePassword && (
        <div className="osiris-overlay">
          <div className="osiris-modal osiris-modal--amber">
            <div className="osiris-modal-header" style={{ borderBottomColor: 'rgba(180,100,0,0.25)' }}>
              <div className="flex items-center gap-2.5">
                <span className="inline-block w-2 h-2 bg-amber-500 rounded-full animate-pulse flex-shrink-0" />
                <h2 className="text-xs font-bold uppercase tracking-widest text-amber-400">Mot de passe — noter maintenant</h2>
              </div>
            </div>
            <div className="p-6 space-y-5">
              <p className="text-sm text-slate-400">Machine : <span className="font-mono text-white">{oneTimePassword.hostname}</span></p>
              <p className="text-xs text-slate-600 leading-relaxed">
                Ce mot de passe ne sera <span className="text-amber-500 font-semibold">jamais réaffiché</span>. C'est le seul accès local à cette machine.
              </p>
              <div className="osiris-password-box">
                <p className="text-[10px] font-mono uppercase tracking-widest text-slate-700 mb-2">mot de passe</p>
                <p className="font-mono text-amber-300 text-base break-all select-all cursor-text leading-relaxed">{oneTimePassword.password}</p>
              </div>
              <button onClick={() => { setOneTimePassword(null); fetchAll(auth.token, selectedOrg) }}
                className="w-full py-2.5 bg-amber-500 hover:bg-amber-400 text-black font-bold text-xs rounded transition-colors cursor-pointer tracking-widest uppercase">
                J'ai noté ce mot de passe
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
