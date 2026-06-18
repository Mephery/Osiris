import { useEffect, useState } from 'react'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'
const API_KEY = import.meta.env.VITE_API_KEY ?? ''
const AUTH_HEADER = { 'X-API-Key': API_KEY }

interface Machine {
  id?: number;
  mac: string;
  client: string;
  os: string;
  hostname: string;
  ou: string;
  status?: string;
  deployed_at?: string | null;
}

const EMPTY_FORM: Machine = { mac: '', client: '', os: 'windows', hostname: '', ou: '' }

export default function App() {
  const [machines, setMachines] = useState<Machine[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Modale formulaire (création ET édition)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingMac, setEditingMac] = useState<string | null>(null) // null = création
  const [formData, setFormData] = useState<Machine>(EMPTY_FORM)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Confirmation de suppression
  const [deletingMac, setDeletingMac] = useState<string | null>(null)

  // Mot de passe one-time
  const [oneTimePassword, setOneTimePassword] = useState<{ hostname: string; password: string } | null>(null)

  const fetchMachines = () => {
    setLoading(true)
    fetch(`${API_URL}/machines`, { headers: AUTH_HEADER })
      .then((res) => {
        if (!res.ok) throw new Error("Erreur de communication avec l'API")
        return res.json()
      })
      .then((data) => { setMachines(data); setLoading(false) })
      .catch((err) => { setError(err.message); setLoading(false) })
  }

  useEffect(() => { fetchMachines() }, [])

  // ── Ouvrir la modale en mode édition ────────────────────────────────────────
  const openEdit = (machine: Machine) => {
    setEditingMac(machine.mac)
    setFormData({ ...machine })
    setSubmitError(null)
    setIsModalOpen(true)
  }

  const openCreate = () => {
    setEditingMac(null)
    setFormData(EMPTY_FORM)
    setSubmitError(null)
    setIsModalOpen(true)
  }

  const closeModal = () => {
    setIsModalOpen(false)
    setEditingMac(null)
  }

  // ── Soumission du formulaire (création ou édition) ───────────────────────────
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitError(null)

    const isEdit = editingMac !== null
    const url    = isEdit ? `${API_URL}/machines/${editingMac}` : `${API_URL}/machines`
    const method = isEdit ? 'PATCH' : 'POST'

    fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', ...AUTH_HEADER },
      body: JSON.stringify(formData),
    })
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json()
          throw new Error(err.detail || "Erreur lors de l'enregistrement")
        }
        return isEdit ? null : res.json()
      })
      .then((data) => {
        closeModal()
        if (data?.password) {
          setOneTimePassword({ hostname: data.hostname, password: data.password })
        } else {
          fetchMachines()
        }
      })
      .catch((err) => setSubmitError(err.message))
  }

  // ── Suppression ───────────────────────────────────────────────────────────────
  const handleDelete = (mac: string) => {
    fetch(`${API_URL}/machines/${mac}`, { method: 'DELETE', headers: AUTH_HEADER })
      .then((res) => {
        if (!res.ok && res.status !== 204) throw new Error('Erreur lors de la suppression')
        setDeletingMac(null)
        fetchMachines()
      })
      .catch((err) => alert(err.message))
  }

  const handlePasswordAcknowledged = () => {
    setOneTimePassword(null)
    fetchMachines()
  }

  return (
    <div className="min-h-screen text-slate-100 font-sans antialiased">

      {/* ── En-tête ──────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-10 border-b border-slate-800/60 bg-[#070b14]/90 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2.5">
              <span className="osiris-icon text-blue-500">⊙</span>
              <span className="text-lg font-black tracking-[0.22em] text-white uppercase select-none">Osiris</span>
            </div>
            <div className="hidden sm:flex items-center gap-2 text-[11px] font-mono text-slate-600 border-l border-slate-800 pl-5">
              <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                error ? 'bg-red-500' : 'bg-emerald-500 animate-pulse'
              }`} />
              {error ? 'API hors ligne' : loading ? 'Connexion…' : 'Connecté'}
            </div>
          </div>
          <button onClick={openCreate} className="osiris-btn">+ Enregistrer un PC</button>
        </div>
      </header>

      {/* ── Contenu principal ─────────────────────────────────────────────────── */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-baseline gap-3 mb-6">
          <h1 className="text-xl font-bold tracking-tight text-white">Parc de déploiement</h1>
          {!loading && !error && (
            <span className="text-xs font-mono text-slate-600">
              {machines.length} machine{machines.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        {loading && (
          <div className="flex items-center gap-2.5 text-slate-600 font-mono text-xs py-6">
            <span className="inline-block w-1.5 h-1.5 bg-blue-600 rounded-full animate-ping" />
            Chargement…
          </div>
        )}
        {error && (
          <div className="border-l-2 border-red-700 pl-4 py-2">
            <p className="text-red-400 text-sm font-mono">{error}</p>
          </div>
        )}

        {!loading && !error && (
          <div className="osiris-table-wrap overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800/80">
                  {["Nom d'hôte", "Adresse MAC", "Client", "OS", "Statut", "OU / Actions"].map((h) => (
                    <th key={h} className="text-left px-4 py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {machines.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-16 text-center text-slate-700 font-mono text-xs">
                      Aucune machine enregistrée
                    </td>
                  </tr>
                ) : machines.map((machine) => (
                  <tr key={machine.id} className="osiris-row">
                    <td className="px-4 py-3 font-mono font-semibold text-white">{machine.hostname}</td>
                    <td className="px-4 py-3 font-mono text-xs tracking-wider text-slate-500">
                      {machine.mac.match(/.{1,2}/g)?.join(':').toUpperCase()}
                    </td>
                    <td className="px-4 py-3 text-slate-300">{machine.client}</td>
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
                          {new Date(machine.deployed_at).toLocaleDateString('fr-FR', {
                            day: '2-digit', month: '2-digit', year: '2-digit',
                            hour: '2-digit', minute: '2-digit'
                          })}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-xs text-slate-600 truncate max-w-[140px]" title={machine.ou}>
                          {machine.ou || '—'}
                        </span>
                        <div className="flex items-center gap-1 ml-auto flex-shrink-0">
                          <button
                            onClick={() => openEdit(machine)}
                            className="osiris-action-btn"
                            title="Modifier"
                          >
                            ✎
                          </button>
                          <button
                            onClick={() => setDeletingMac(machine.mac)}
                            className="osiris-action-btn osiris-action-btn--danger"
                            title="Supprimer"
                          >
                            ✕
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {/* ── Modale : enregistrement / édition ────────────────────────────────── */}
      {isModalOpen && (
        <div className="osiris-overlay" onClick={(e) => { if (e.target === e.currentTarget) closeModal() }}>
          <div className="osiris-modal">
            <div className="osiris-modal-header">
              <h2 className="text-xs font-bold uppercase tracking-widest text-white">
                {editingMac ? 'Modifier la machine' : 'Nouvel enregistrement iPXE'}
              </h2>
              <button onClick={closeModal} className="text-slate-700 hover:text-slate-300 text-2xl leading-none cursor-pointer transition-colors">×</button>
            </div>

            {submitError && (
              <div className="mx-6 mt-4 border-l-2 border-red-700 pl-3 py-1">
                <p className="text-red-400 text-xs font-mono">{submitError}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              {/* MAC — lecture seule en édition */}
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                  Adresse MAC {editingMac && <span className="text-slate-700 normal-case">(non modifiable)</span>}
                </label>
                <input
                  required type="text" placeholder="00:11:22:AA:BB:CC"
                  value={formData.mac}
                  onChange={(e) => setFormData({ ...formData, mac: e.target.value })}
                  disabled={!!editingMac}
                  className={`osiris-input font-mono ${editingMac ? 'opacity-40 cursor-not-allowed' : ''}`}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Nom d'hôte</label>
                  <input required type="text" placeholder="PC-PROD-01"
                    value={formData.hostname}
                    onChange={(e) => setFormData({ ...formData, hostname: e.target.value })}
                    className="osiris-input font-mono" />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">OS cible</label>
                  <select value={formData.os}
                    onChange={(e) => setFormData({ ...formData, os: e.target.value, ou: '' })}
                    className="osiris-input">
                    <option value="windows">Windows</option>
                    <option value="ubuntu">Ubuntu</option>
                  </select>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Client / Entreprise</label>
                <input required type="text" placeholder="Acme Corp."
                  value={formData.client}
                  onChange={(e) => setFormData({ ...formData, client: e.target.value })}
                  className="osiris-input" />
              </div>

              {formData.os === 'windows' && (
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Chemin OU Active Directory</label>
                  <input required type="text" placeholder="OU=Workstations,DC=domain,DC=local"
                    value={formData.ou}
                    onChange={(e) => setFormData({ ...formData, ou: e.target.value })}
                    className="osiris-input font-mono text-xs" />
                </div>
              )}

              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={closeModal} className="osiris-btn-ghost">Annuler</button>
                <button type="submit" className="osiris-btn">
                  {editingMac ? 'Enregistrer les modifications' : 'Enregistrer'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Modale : confirmation de suppression ──────────────────────────────── */}
      {deletingMac && (
        <div className="osiris-overlay">
          <div className="osiris-modal osiris-modal--danger">
            <div className="osiris-modal-header" style={{ borderBottomColor: 'rgba(185, 28, 28, 0.25)' }}>
              <h2 className="text-xs font-bold uppercase tracking-widest text-red-400">Confirmer la suppression</h2>
            </div>
            <div className="p-6 space-y-5">
              <p className="text-sm text-slate-400">
                La machine <span className="font-mono text-white">
                  {machines.find(m => m.mac === deletingMac)?.hostname ?? deletingMac}
                </span> sera définitivement supprimée de la base de données.
              </p>
              <p className="text-xs text-slate-600">
                Cette action est <span className="text-red-400 font-semibold">irréversible</span>.
                La machine ne pourra plus booter via Osiris.
              </p>
              <div className="flex gap-3 justify-end">
                <button onClick={() => setDeletingMac(null)} className="osiris-btn-ghost">Annuler</button>
                <button
                  onClick={() => handleDelete(deletingMac)}
                  className="osiris-btn osiris-btn--danger"
                >
                  Supprimer
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Modale : mot de passe one-time ────────────────────────────────────── */}
      {oneTimePassword && (
        <div className="osiris-overlay">
          <div className="osiris-modal osiris-modal--amber">
            <div className="osiris-modal-header" style={{ borderBottomColor: 'rgba(180, 100, 0, 0.25)' }}>
              <div className="flex items-center gap-2.5">
                <span className="inline-block w-2 h-2 bg-amber-500 rounded-full animate-pulse flex-shrink-0" />
                <h2 className="text-xs font-bold uppercase tracking-widest text-amber-400">Mot de passe — noter maintenant</h2>
              </div>
            </div>
            <div className="p-6 space-y-5">
              <p className="text-sm text-slate-400">
                Machine&nbsp;: <span className="font-mono text-white">{oneTimePassword.hostname}</span>
              </p>
              <p className="text-xs text-slate-600 leading-relaxed">
                Ce mot de passe ne sera <span className="text-amber-500 font-semibold">jamais réaffiché</span>.
                Copiez-le avant de continuer — c'est le seul accès local à cette machine.
              </p>
              <div className="osiris-password-box">
                <p className="text-[10px] font-mono uppercase tracking-widest text-slate-700 mb-2">mot de passe</p>
                <p className="font-mono text-amber-300 text-base break-all select-all cursor-text leading-relaxed">
                  {oneTimePassword.password}
                </p>
              </div>
              <button onClick={handlePasswordAcknowledged}
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
