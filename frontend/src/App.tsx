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
  profile_id?: number | null;
}

interface Profile {
  id: number;
  name: string;
  os: string;
  locale: string;
  keyboard: string;
  timezone: string;
  default_user: string;
  extra_packages: string;
  join_domain: boolean;
  domain: string;
}

interface OsImage {
  id: number;
  name: string;
  version: string;
  os: string;
  status: string;   // queued/downloading/extracting/ready/failed
  progress: number;
  nfs_path: string;
  error: string | null;
  created_at: string;
}

interface AuditLogEntry {
  id: number;
  timestamp: string;
  user_email: string;
  action: string;
  target_mac: string | null;
  details: Record<string, unknown> | null;
}

const ACTION_META: Record<string, { label: string; cls: string }> = {
  login:            { label: 'Connexion',            cls: 'text-slate-400 border-slate-700' },
  create_machine:   { label: 'Machine créée',         cls: 'text-emerald-400 border-emerald-800' },
  update_machine:   { label: 'Machine modifiée',      cls: 'text-blue-400 border-blue-800' },
  delete_machine:   { label: 'Machine supprimée',     cls: 'text-red-400 border-red-800' },
  create_user:      { label: 'Utilisateur créé',      cls: 'text-emerald-400 border-emerald-800' },
  delete_user:      { label: 'Utilisateur supprimé',  cls: 'text-red-400 border-red-800' },
  create_org:       { label: 'Organisation créée',    cls: 'text-emerald-400 border-emerald-800' },
  delete_org:       { label: 'Organisation supprimée',cls: 'text-red-400 border-red-800' },
  create_image:     { label: 'Image téléchargée',     cls: 'text-blue-400 border-blue-800' },
  delete_image:     { label: 'Image supprimée',       cls: 'text-red-400 border-red-800' },
}

const IMAGE_STATUS: Record<string, { label: string; bar: string; badge: string }> = {
  queued:      { label: 'En attente',     bar: 'bg-slate-500',   badge: 'text-slate-400 border-slate-700' },
  downloading: { label: 'Téléchargement', bar: 'bg-blue-500',    badge: 'text-blue-400 border-blue-800' },
  extracting:  { label: 'Extraction',     bar: 'bg-amber-500',   badge: 'text-amber-400 border-amber-800' },
  ready:       { label: 'Prête',          bar: 'bg-emerald-500', badge: 'text-emerald-400 border-emerald-800' },
  failed:      { label: 'Erreur',         bar: 'bg-red-500',     badge: 'text-red-400 border-red-800' },
}

function formatDetails(d: Record<string, unknown> | null): string {
  if (!d) return '—'
  return Object.entries(d).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

function formatMac(mac: string): string {
  return mac.match(/.{1,2}/g)?.join(':').toUpperCase() ?? mac
}

const EMPTY_FORM: Machine = { mac: '', client: '', os: 'windows', hostname: '', ou: '', organization_id: null, profile_id: null }

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

  // ── Profils ────────────────────────────────────────────────────────────────
  const [profiles, setProfiles] = useState<Profile[]>([])

  // ── Images OS ──────────────────────────────────────────────────────────────
  const [images, setImages] = useState<OsImage[]>([])
  const [newImage, setNewImage] = useState({ name: '', version: '', os: 'ubuntu', iso_url: '' })
  const [newProfile, setNewProfile] = useState<Partial<Profile>>({ os: 'ubuntu', name: '', locale: 'fr_FR.UTF-8', keyboard: 'fr', timezone: 'Europe/Paris', default_user: 'osiris', extra_packages: '', join_domain: true, domain: 'entreprise.local' })

  // ── Changement de mot de passe ─────────────────────────────────────────────
  const [showPasswordModal, setShowPasswordModal] = useState(false)
  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNew, setPwNew]         = useState('')
  const [pwConfirm, setPwConfirm] = useState('')
  const [pwError, setPwError]     = useState<string | null>(null)
  const [pwSuccess, setPwSuccess] = useState(false)
  const [pwLoading, setPwLoading] = useState(false)

  // ── Journal d'activité ──────────────────────────────────────────────────────
  const [showAuditLog, setShowAuditLog]   = useState(false)
  const [auditLogs, setAuditLogs]         = useState<AuditLogEntry[]>([])
  const [auditLoading, setAuditLoading]   = useState(false)

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

  const fetchImages = (token: string) => {
    fetch(`${API_URL}/images`, { headers: authHeader(token) })
      .then((res) => res.json())
      .then(setImages)
      .catch(() => {})
  }

  const fetchProfiles = (token: string) => {
    fetch(`${API_URL}/profiles`, { headers: authHeader(token) })
      .then((res) => res.json())
      .then(setProfiles)
      .catch(() => {})
  }

  const fetchAuditLogs = (token: string) => {
    setAuditLoading(true)
    fetch(`${API_URL}/audit-logs`, { headers: authHeader(token) })
      .then((res) => res.json())
      .then((data) => { setAuditLogs(data); setAuditLoading(false) })
      .catch(() => setAuditLoading(false))
  }

  useEffect(() => {
    if (!auth) return
    fetchAll(auth.token, selectedOrg)
    fetchOrgs(auth.token)
    fetchProfiles(auth.token)
    if (auth.role === 'admin') { fetchUsers(auth.token); fetchImages(auth.token) }
  }, [auth, selectedOrg])

  // Auto-refresh des images en cours de téléchargement/extraction
  useEffect(() => {
    if (!auth) return
    const inProgress = images.some(i => ['queued', 'downloading', 'extracting'].includes(i.status))
    if (!inProgress) return
    const interval = setInterval(() => fetchImages(auth.token), 2000)
    return () => clearInterval(interval)
  }, [auth, images])

  // ── WebSocket : mises à jour de statut en temps réel ───────────────────────
  useEffect(() => {
    if (!auth) return
    let ws: WebSocket
    let reconnectTimer: ReturnType<typeof setTimeout>

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${proto}//${window.location.host}/ws/machines`
      ws = new WebSocket(wsUrl)

      ws.onmessage = (event) => {
        const { mac, status, deployed_at } = JSON.parse(event.data)
        setMachines((prev) =>
          prev.map((m: Machine) => m.mac === mac ? { ...m, status, deployed_at: deployed_at ?? m.deployed_at } : m)
        )
      }

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000)
      }

      ws.onerror = () => {}
    }

    connect()
    return () => { clearTimeout(reconnectTimer); ws?.close() }
  }, [auth])

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

  const handleDeleteOrg = (id: number) => {
    fetch(`${API_URL}/organizations/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(() => fetchOrgs(auth.token))
      .catch(() => {})
  }

  const handleDeleteUser = (id: number) => {
    fetch(`${API_URL}/users/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(() => fetchUsers(auth.token))
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

  const handleCreateProfile = (e: React.FormEvent) => {
    e.preventDefault()
    fetch(`${API_URL}/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify(newProfile),
    })
      .then((res) => res.json())
      .then(() => {
        setNewProfile({ os: 'ubuntu', name: '', locale: 'fr_FR.UTF-8', keyboard: 'fr', timezone: 'Europe/Paris', default_user: 'osiris', extra_packages: '', join_domain: true, domain: 'entreprise.local' })
        fetchProfiles(auth.token)
      })
      .catch(() => {})
  }

  const handleCreateImage = (e: React.FormEvent) => {
    e.preventDefault()
    fetch(`${API_URL}/images`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth!.token) },
      body: JSON.stringify(newImage),
    })
      .then((res) => res.json())
      .then(() => { setNewImage({ name: '', version: '', os: 'ubuntu', iso_url: '' }); fetchImages(auth!.token) })
      .catch(() => {})
  }

  const handleDeleteImage = (id: number) => {
    fetch(`${API_URL}/images/${id}`, { method: 'DELETE', headers: authHeader(auth!.token) })
      .then(() => fetchImages(auth!.token))
      .catch(() => {})
  }

  const handleDeleteProfile = (id: number) => {
    fetch(`${API_URL}/profiles/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(() => fetchProfiles(auth.token))
      .catch(() => {})
  }

  const openPasswordModal = () => {
    setPwCurrent(''); setPwNew(''); setPwConfirm('')
    setPwError(null); setPwSuccess(false)
    setShowPasswordModal(true)
  }

  const handlePasswordChange = (e: React.FormEvent) => {
    e.preventDefault()
    setPwError(null)
    if (pwNew !== pwConfirm) { setPwError('Les deux nouveaux mots de passe ne correspondent pas.'); return }
    if (pwNew.length < 8) { setPwError('Le nouveau mot de passe doit faire au moins 8 caractères.'); return }
    setPwLoading(true)
    fetch(`${API_URL}/auth/me/password`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ current_password: pwCurrent, new_password: pwNew }),
    })
      .then(async (res) => {
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Erreur') }
        setPwSuccess(true)
        setPwLoading(false)
      })
      .catch((err) => { setPwError(err.message); setPwLoading(false) })
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
              <>
                <button onClick={() => setShowAdmin(!showAdmin)} className={`osiris-btn-ghost text-xs ${showAdmin ? 'text-blue-400' : ''}`}>
                  ⚙ Administration
                </button>
                <button onClick={() => { setShowAuditLog(!showAuditLog); if (!showAuditLog) fetchAuditLogs(auth.token) }}
                  className={`osiris-btn-ghost text-xs ${showAuditLog ? 'text-blue-400' : ''}`}>
                  ≡ Journal
                </button>
              </>
            )}
            <span className="text-xs font-mono text-slate-700 hidden sm:block">{auth.email}</span>
            <button onClick={openPasswordModal} className="osiris-btn-ghost text-xs">Mot de passe</button>
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
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-xs text-slate-600">{org.slug}</span>
                      <button onClick={() => handleDeleteOrg(org.id)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer">✕</button>
                    </div>
                  </li>
                ))}
                {orgs.length === 0 && <li className="text-slate-700 text-xs font-mono">Aucune organisation</li>}
              </ul>
              <form onSubmit={handleCreateOrg} className="space-y-2 pt-2">
                <input required placeholder="Nom de l'organisation" value={newOrgName} onChange={e => setNewOrgName(e.target.value)} className="osiris-input text-xs w-full" />
                <div className="flex gap-2">
                  <input required placeholder="slug (ex: acme-corp)" value={newOrgSlug} onChange={e => setNewOrgSlug(e.target.value)} className="osiris-input text-xs flex-1 min-w-0 font-mono" />
                  <button type="submit" className="osiris-btn text-xs px-3 flex-shrink-0">+</button>
                </div>
              </form>
            </div>

            {/* Utilisateurs */}
            <div className="osiris-table-wrap p-5 space-y-4">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Utilisateurs</h2>
              <ul className="space-y-1">
                {users.map(u => (
                  <li key={u.id} className="flex items-center justify-between text-sm py-1 border-b border-slate-800/50">
                    <span className="text-white">{u.email}</span>
                    <div className="flex items-center gap-3">
                      <span className={`osiris-os-badge ${u.role === 'admin' ? 'osiris-os-badge--windows' : 'osiris-os-badge--ubuntu'}`}>{u.role}</span>
                      {u.email !== auth.email && (
                        <button onClick={() => handleDeleteUser(u.id)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer">✕</button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
              <form onSubmit={handleCreateUser} className="space-y-2 pt-2">
                <input required type="email" placeholder="Email" value={newUserEmail} onChange={e => setNewUserEmail(e.target.value)} className="osiris-input text-xs w-full" />
                <input required type="password" placeholder="Mot de passe" value={newUserPass} onChange={e => setNewUserPass(e.target.value)} className="osiris-input text-xs w-full" />
                <div className="flex gap-2">
                  <select value={newUserRole} onChange={e => setNewUserRole(e.target.value)} className="osiris-input text-xs flex-1">
                    <option value="technician">Technicien</option>
                    <option value="admin">Admin</option>
                  </select>
                  <button type="submit" className="osiris-btn text-xs px-3 flex-shrink-0">+</button>
                </div>
              </form>
            </div>

            {/* Profils de déploiement — col-span-2 pour occuper toute la largeur du grid */}
            <div className="osiris-table-wrap p-5 space-y-4 md:col-span-2">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Profils de déploiement</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {profiles.map(p => (
                  <div key={p.id} className="flex items-center justify-between py-1.5 px-3 border border-slate-800/60 rounded">
                    <div>
                      <span className="text-white text-sm font-medium">{p.name}</span>
                      <span className={`ml-2 osiris-os-badge osiris-os-badge--${p.os}`}>{p.os}</span>
                      <p className="text-[10px] font-mono text-slate-600 mt-0.5">{p.locale} · {p.keyboard} · {p.timezone}</p>
                    </div>
                    <button onClick={() => handleDeleteProfile(p.id)} className="osiris-action-btn osiris-action-btn--danger ml-3 flex-shrink-0" title="Supprimer">✕</button>
                  </div>
                ))}
              </div>
              <form onSubmit={handleCreateProfile} className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-slate-800/50">
                <input required placeholder="Nom du profil" value={newProfile.name ?? ''} onChange={e => setNewProfile({ ...newProfile, name: e.target.value })} className="osiris-input text-xs col-span-2 sm:col-span-1" />
                <select value={newProfile.os} onChange={e => setNewProfile({ ...newProfile, os: e.target.value })} className="osiris-input text-xs">
                  <option value="ubuntu">Ubuntu</option>
                  <option value="windows">Windows</option>
                </select>
                <input placeholder="Locale" value={newProfile.locale ?? ''} onChange={e => setNewProfile({ ...newProfile, locale: e.target.value })} className="osiris-input text-xs font-mono" />
                <input placeholder="Clavier" value={newProfile.keyboard ?? ''} onChange={e => setNewProfile({ ...newProfile, keyboard: e.target.value })} className="osiris-input text-xs font-mono" />
                <input placeholder="Fuseau horaire" value={newProfile.timezone ?? ''} onChange={e => setNewProfile({ ...newProfile, timezone: e.target.value })} className="osiris-input text-xs font-mono" />
                {newProfile.os === 'ubuntu' ? (
                  <>
                    <input placeholder="Utilisateur local" value={newProfile.default_user ?? ''} onChange={e => setNewProfile({ ...newProfile, default_user: e.target.value })} className="osiris-input text-xs font-mono" />
                    <input placeholder="Paquets (htop,vim,...)" value={newProfile.extra_packages ?? ''} onChange={e => setNewProfile({ ...newProfile, extra_packages: e.target.value })} className="osiris-input text-xs font-mono col-span-2 sm:col-span-1" />
                  </>
                ) : (
                  <>
                    <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                      <input type="checkbox" checked={newProfile.join_domain ?? true} onChange={e => setNewProfile({ ...newProfile, join_domain: e.target.checked })} className="accent-blue-500" />
                      Joindre l'AD
                    </label>
                    <input placeholder="Domaine AD" value={newProfile.domain ?? ''} onChange={e => setNewProfile({ ...newProfile, domain: e.target.value })} className="osiris-input text-xs font-mono" />
                  </>
                )}
                <button type="submit" className="osiris-btn text-xs px-3 sm:col-start-3">+ Créer</button>
              </form>
            </div>
            {/* Images OS ── col-span-2 */}
            <div className="osiris-table-wrap p-5 space-y-4 md:col-span-2">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Images OS</h2>

              <div className="space-y-2">
                {images.length === 0 && <p className="text-slate-700 text-xs font-mono">Aucune image téléchargée</p>}
                {images.map(img => {
                  const s = IMAGE_STATUS[img.status] ?? IMAGE_STATUS.queued
                  const inProgress = ['downloading', 'extracting'].includes(img.status)
                  return (
                    <div key={img.id} className="py-2 px-3 border border-slate-800/60 rounded space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-white text-sm font-medium truncate">{img.name}</span>
                          <span className={`osiris-os-badge osiris-os-badge--${img.os} flex-shrink-0`}>{img.os}</span>
                          <span className={`inline-block border rounded px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider flex-shrink-0 ${s.badge}`}>
                            {s.label}{inProgress ? ` ${img.progress}%` : ''}
                          </span>
                        </div>
                        <button onClick={() => handleDeleteImage(img.id)} className="osiris-action-btn osiris-action-btn--danger flex-shrink-0" title="Supprimer">✕</button>
                      </div>
                      {inProgress && (
                        <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full transition-all duration-500 ${s.bar}`} style={{ width: `${img.progress}%` }} />
                        </div>
                      )}
                      <p className="text-[10px] font-mono text-slate-700">{img.nfs_path || '—'}</p>
                      {img.status === 'failed' && img.error && (
                        <p className="text-[10px] font-mono text-red-500 truncate" title={img.error}>{img.error}</p>
                      )}
                    </div>
                  )
                })}
              </div>

              <form onSubmit={handleCreateImage} className="space-y-2 pt-2 border-t border-slate-800/50">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <input required placeholder="Nom  (ex : Ubuntu 24.04 LTS)" value={newImage.name} onChange={e => setNewImage({ ...newImage, name: e.target.value })} className="osiris-input text-xs sm:col-span-2" />
                  <input required placeholder="Version  (ex : 24.04)" value={newImage.version} onChange={e => setNewImage({ ...newImage, version: e.target.value })} className="osiris-input text-xs font-mono" />
                  <select value={newImage.os} onChange={e => setNewImage({ ...newImage, os: e.target.value })} className="osiris-input text-xs">
                    <option value="ubuntu">Ubuntu</option>
                    <option value="windows">Windows</option>
                  </select>
                </div>
                <div className="flex gap-2">
                  <input required placeholder="URL ISO  (https://...)" value={newImage.iso_url} onChange={e => setNewImage({ ...newImage, iso_url: e.target.value })} className="osiris-input text-xs font-mono flex-1 min-w-0" />
                  <button type="submit" className="osiris-btn text-xs flex-shrink-0">↓ Télécharger</button>
                </div>
              </form>
            </div>

          </div>
        )}

        {/* ── Journal d'activité ───────────────────────────────────────────── */}
        {showAuditLog && auth.role === 'admin' && (
          <div className="osiris-table-wrap overflow-x-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/80">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Journal d'activité</h2>
              <button onClick={() => fetchAuditLogs(auth.token)}
                className="osiris-btn-ghost text-[10px]">
                {auditLoading ? 'Chargement…' : '↺ Rafraîchir'}
              </button>
            </div>
            {auditLoading ? (
              <div className="flex items-center gap-2.5 text-slate-600 font-mono text-xs p-5">
                <span className="inline-block w-1.5 h-1.5 bg-blue-600 rounded-full animate-ping" />
                Chargement…
              </div>
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

      {/* ── Modale : changement de mot de passe ──────────────────────────── */}
      {showPasswordModal && (
        <div className="osiris-overlay" onClick={(e) => { if (e.target === e.currentTarget) setShowPasswordModal(false) }}>
          <div className="osiris-modal">
            <div className="osiris-modal-header">
              <h2 className="text-xs font-bold uppercase tracking-widest text-white">Changer mon mot de passe</h2>
              <button onClick={() => setShowPasswordModal(false)} className="text-slate-700 hover:text-slate-300 text-2xl leading-none cursor-pointer transition-colors">×</button>
            </div>
            {pwSuccess ? (
              <div className="p-6 space-y-5">
                <div className="border-l-2 border-emerald-700 pl-3 py-1">
                  <p className="text-emerald-400 text-sm font-mono">Mot de passe mis à jour avec succès.</p>
                </div>
                <button onClick={() => setShowPasswordModal(false)} className="osiris-btn w-full justify-center">Fermer</button>
              </div>
            ) : (
              <form onSubmit={handlePasswordChange} className="p-6 space-y-4">
                {pwError && (
                  <div className="border-l-2 border-red-700 pl-3 py-1">
                    <p className="text-red-400 text-xs font-mono">{pwError}</p>
                  </div>
                )}
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Mot de passe actuel</label>
                  <input required type="password" placeholder="••••••••"
                    value={pwCurrent} onChange={(e) => setPwCurrent(e.target.value)}
                    className="osiris-input" autoFocus />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Nouveau mot de passe</label>
                  <input required type="password" placeholder="••••••••  (8 caractères minimum)"
                    value={pwNew} onChange={(e) => setPwNew(e.target.value)}
                    className="osiris-input" />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Confirmer le nouveau mot de passe</label>
                  <input required type="password" placeholder="••••••••"
                    value={pwConfirm} onChange={(e) => setPwConfirm(e.target.value)}
                    className="osiris-input" />
                </div>
                <div className="flex justify-end gap-3 pt-2">
                  <button type="button" onClick={() => setShowPasswordModal(false)} className="osiris-btn-ghost">Annuler</button>
                  <button type="submit" disabled={pwLoading} className="osiris-btn">
                    {pwLoading ? 'Mise à jour…' : 'Changer le mot de passe'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

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
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                  Profil de déploiement
                  <span className="ml-1 text-slate-700 normal-case font-normal">(optionnel — utilise le profil par défaut sinon)</span>
                </label>
                <select value={formData.profile_id ?? ''} onChange={(e) => setFormData({ ...formData, profile_id: e.target.value ? Number(e.target.value) : null })} className="osiris-input">
                  <option value="">— Par défaut —</option>
                  {profiles.filter(p => p.os === formData.os).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
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
