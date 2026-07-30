// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import React, { useEffect, useRef, useState } from 'react'
import { Toaster, toast } from 'sonner'
import './App.css'
import type {
  AuthState, Organization, OrganizationPatch, Machine, Profile, Application,
  DeploymentEvent, Hypervisor, OsImage, SnapshotEntry, LiveEvent, VpnTunnel,
} from './types'
import { IMAGE_STATUS, EMPTY_FORM, authHeader } from './types'
import {
  IcoOsiris, IcoRefresh, IcoSearch, IcoPower, IcoPencil, IcoX, IcoChevRight, IcoGear,
} from './icons'
import { LoginPage } from './LoginPage'
import { DashboardTab } from './DashboardTab'
import { JournalTab } from './JournalTab'
import { CaptureTab } from './CaptureTab'
import { DriversTab } from './DriversTab'
import { InfrastructureTab } from './InfrastructureTab'
import { SettingsModal } from './SettingsModal'
import { ProfilesSection } from './ProfilesSection'
import { SkeletonRows } from './Skeleton'
import { MachineDetailPanel } from './MachineDetailPanel'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://10.0.0.1:8000'
// ── Composant principal ────────────────────────────────────────────────────────

const AUTH_KEY = 'osiris_auth'

function loadAuth(): AuthState | null {
  try {
    const raw = localStorage.getItem(AUTH_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function saveAuth(a: AuthState | null) {
  if (a) localStorage.setItem(AUTH_KEY, JSON.stringify(a))
  else localStorage.removeItem(AUTH_KEY)
}

/** Saisie du mot de passe BIOS d'une organisation.
 *  Validation EXPLICITE (bouton ou Entrée) et non au `onBlur` des autres champs :
 *  le champ se vide après envoi, donc sans bouton on ne sait pas si c'est parti. */
function BiosPasswordField({ isSet, onSave }: { isSet: boolean; onSave: (v: string) => void }) {
  const [value, setValue] = useState('')
  const submit = () => { if (value) { onSave(value); setValue('') } }
  return (
    <div className="flex gap-2 flex-1">
      <input
        type="password"
        autoComplete="new-password"
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submit() } }}
        placeholder={isSet ? 'Mot de passe BIOS (défini — saisir pour remplacer)' : 'Mot de passe BIOS (non défini)'}
        className="osiris-input text-[10px] font-mono flex-1 min-w-0"
      />
      <button
        type="button"
        onClick={submit}
        disabled={!value}
        title="Enregistrer le mot de passe BIOS"
        className="osiris-btn text-xs px-3 flex-shrink-0 disabled:opacity-30 disabled:cursor-not-allowed"
      >✓</button>
    </div>
  )
}

export default function App() {
  const [auth, setAuthState] = useState<AuthState | null>(loadAuth)
  const setAuth = (a: AuthState | null) => { saveAuth(a); setAuthState(a) }

  const [machines, setMachines]     = useState<Machine[]>([])
  // Toujours à jour, pour lire le hostname courant depuis le handler WebSocket (fermeture figée sur [auth]).
  const machinesRef = useRef<Machine[]>([])
  useEffect(() => { machinesRef.current = machines }, [machines])
  const [orgs, setOrgs]             = useState<Organization[]>([])
  const [selectedOrg, setSelectedOrg] = useState<number | null>(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState<string | null>(null)

  // Modale formulaire (création ET édition)
  const [isModalOpen, setIsModalOpen]   = useState(false)
  const [editingMac, setEditingMac]     = useState<string | null>(null)
  const [formData, setFormData]         = useState<Machine>(EMPTY_FORM)
  // Fiche telle qu'elle était à l'ouverture de la modale (cf. openEdit).
  const [formSnapshot, setFormSnapshot] = useState<Machine>(EMPTY_FORM)
  const [submitError, setSubmitError]   = useState<string | null>(null)
  const [driverPacks, setDriverPacks]   = useState<any[]>([])

  // Confirmation suppression
  const [deletingMac, setDeletingMac]         = useState<string | null>(null)
  const [deleteDestroyVm, setDeleteDestroyVm] = useState(false)
  const [vmPowerState, setVmPowerState]       = useState<Record<string, { status: string; cpu: number; mem_mb: number } | null>>({})
  const [vmPowerLoading, setVmPowerLoading]   = useState<Record<string, boolean>>({})
  const [snapshots, setSnapshots]             = useState<SnapshotEntry[]>([])
  const [snapshotsLoading, setSnapshotsLoading] = useState(false)
  const [snapshotCreating, setSnapshotCreating] = useState(false)
  const [newSnapName, setNewSnapName]         = useState('')
  const [newSnapDesc, setNewSnapDesc]         = useState('')

  // Redéploiement
  const [redeployingMac, setRedeployingMac] = useState<string | null>(null)

  // Mot de passe one-time
  const [oneTimePassword, setOneTimePassword] = useState<{ hostname: string; password: string } | null>(null)

  // ── Navigation par onglets ─────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<'machines' | 'admin' | 'drivers' | 'journal' | 'capture' | 'dashboard' | 'infrastructure'>('machines')

  // Sous-onglets de la section Administration (une seule section affichée à la fois → page moins longue + chargement paresseux)
  type AdminSubTab = 'orgs' | 'users' | 'apps' | 'profiles' | 'images' | 'domains' | 'vpn'
  const ADMIN_SUBTABS: { id: AdminSubTab; label: string }[] = [
    { id: 'orgs',     label: 'Organisations' },
    { id: 'users',    label: 'Utilisateurs' },
    { id: 'apps',     label: 'Applications' },
    { id: 'profiles', label: 'Profils' },
    { id: 'images',   label: 'Images OS' },
    { id: 'domains',  label: 'Domaines AD' },
    { id: 'vpn',      label: 'Tunnels VPN' },
  ]
  const [adminSubTab, setAdminSubTab] = useState<AdminSubTab>('orgs')

  // ── Section admin : gestion des orgs et users ──────────────────────────────
  // Signal de rafraîchissement pour l'onglet Capture (incrémenté quand une capture se termine, cf. WebSocket)
  const [captureRefresh, setCaptureRefresh] = useState(0)
  // Flux d'activité temps réel du dashboard (alimenté par le WebSocket ci-dessous), les 30 derniers événements.
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([])
  const [csvImporting, setCsvImporting] = useState(false)
  const [showCsvHint, setShowCsvHint]   = useState(false)
  const [csvHintDismiss, setCsvHintDismiss] = useState(false)
  const csvFileRef = useRef<HTMLInputElement>(null)
  const [newOrgName, setNewOrgName]     = useState('')
  const [newOrgSlug, setNewOrgSlug]     = useState('')
  const [users, setUsers]               = useState<{ id: number; email: string; role: string }[]>([])
  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserPass, setNewUserPass]   = useState('')
  const [newUserRole, setNewUserRole]   = useState('technician')
  const [newAppName, setNewAppName]           = useState('')
  const [newAppWingetId, setNewAppWingetId]   = useState('')
  const [newAppAptPackage, setNewAppAptPackage] = useState('')
  const [newAppCategory, setNewAppCategory]   = useState('tools')
  const [newAppIcon, setNewAppIcon]           = useState('📦')
  // Application dont le script de post-installation Linux est déplié, s'il y en a une
  const [editingAppScript, setEditingAppScript] = useState<number | null>(null)

  // ── Profils (liste partagée ; le state d'édition vit dans ProfilesSection) ──
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [apps, setApps] = useState<Application[]>([])

  // ── Images OS ──────────────────────────────────────────────────────────────
  const [images, setImages] = useState<OsImage[]>([])
  const [newImage, setNewImage] = useState({ name: '', version: '', os: 'ubuntu', iso_url: '', wim_name: '' })

  // ── Infrastructure (Hyperviseurs) ──────────────────────────────────────────
  // hypervisors reste ici car l'onglet Machines l'utilise aussi (statut/console VM).
  const [hypervisors, setHypervisors]   = useState<Hypervisor[]>([])

  // ── Sélection en lot ──────────────────────────────────────────────────────
  const [selectedMacs, setSelectedMacs] = useState<Set<string>>(new Set())

  // ── Logs déploiement + historique ─────────────────────────────────────────
  const [deployLogs, setDeployLogs]         = useState<Record<string, string[]>>({})
  // Panneau latéral de détails machine : mac de la machine actuellement affichée, ou null si fermé.
  const [detailMac, setDetailMac]           = useState<string | null>(null)
  const [machineHistory, setMachineHistory] = useState<Record<string, DeploymentEvent[]>>({})
  const [bitlockerData, setBitlockerData] = useState<Record<string, { key: string | null, pin: string | null }>>({})
  const [lapsData, setLapsData] = useState<Record<string, string>>({})

  const fetchHistory = (mac: string) => {
    if (!auth) return
    fetch(`${API_URL}/machines/${mac}/history`, { headers: authHeader(auth.token) })
      .then(r => r.ok ? r.json() : [])
      .then(data => setMachineHistory(prev => ({ ...prev, [mac]: data })))
      .catch(() => {})
  }

  const fetchBitlockerKey = (mac: string) => {
    if (!auth) return
    fetch(`${API_URL}/machines/${mac}/bitlocker-key`, { headers: authHeader(auth.token) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setBitlockerData(prev => ({ ...prev, [mac]: { key: data.key, pin: data.pin } })))
      .catch(() => toast.error('Impossible de recuperer les donnees BitLocker'))
  }

  const fetchLapsPassword = (mac: string) => {
    if (!auth) return
    fetch(`${API_URL}/machines/${mac}/laps-password`, { headers: authHeader(auth.token) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setLapsData(prev => ({ ...prev, [mac]: data.password })))
      .catch(() => toast.error('Impossible de recuperer le mot de passe LAPS'))
  }

  const redeployNow = (mac: string) => {
    if (!auth) return
    fetch(`${API_URL}/machines/${mac}/redeploy-now`, { method: 'POST', headers: authHeader(auth.token) })
      .then(r => { if (r.ok) { fetchAll(auth.token); toast.success('Machine repassee en pending + WoL envoye') } else throw new Error() })
      .catch(() => toast.error('Erreur redeploy-now'))
  }

  const saveNotes = (mac: string, notes: string) => {
    if (!auth) return
    fetch(`${API_URL}/machines/${mac}`, {
      method: 'PATCH',
      headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes }),
    })
      .then(r => { if (!r.ok) throw new Error() })
      .then(() => {
        setMachines(prev => prev.map(m => m.mac === mac ? { ...m, notes } : m))
        toast.success('Notes sauvegardees')
      })
      .catch(() => toast.error('Erreur lors de la sauvegarde'))
  }

  // ── Recherche + filtres ────────────────────────────────────────────────────
  const [search, setSearch]             = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [osFilter, setOsFilter]         = useState('')
  const [smokeFilter, setSmokeFilter]   = useState(false)
  const [sortKey, setSortKey]           = useState<'hostname' | 'mac' | 'client' | 'os' | 'status' | null>(null)
  const [sortDir, setSortDir]           = useState<'asc' | 'desc'>('asc')

  // Clic sur un en-tête de colonne : trie dessus, ou inverse le sens si déjà actif.
  const toggleSort = (key: 'hostname' | 'mac' | 'client' | 'os' | 'status') => {
    if (sortKey === key) { setSortDir(d => d === 'asc' ? 'desc' : 'asc') }
    else { setSortKey(key); setSortDir('asc') }
  }

  const resetFilters = () => { setSearch(''); setStatusFilter(''); setOsFilter(''); setSmokeFilter(false) }
  const hasActiveFilter = !!(search || statusFilter || osFilter || smokeFilter)

  // ── Modale paramètres du compte (mot de passe, 2FA, clés API) ──────────────
  const [showSettingsModal, setShowSettingsModal] = useState(false)

  // Domaines AD par organisation
  const EMPTY_DOMAIN_CONFIG = { organization_id: 0, name: '', domain: '', join_user: '', join_password: '', default_ou: '', wifi_ssid: '', wifi_password: '' }
  const [domainConfigs, setDomainConfigs] = useState<any[]>([])
  const [newDomainConfig, setNewDomainConfig] = useState(EMPTY_DOMAIN_CONFIG)
  // id de la config AD en cours d'édition (null = mode création)
  const [editingDcId, setEditingDcId] = useState<number | null>(null)

  const startEditDomainConfig = (dc: any) => {
    setEditingDcId(dc.id)
    // les mots de passe ne sont jamais renvoyés par l'API → champs laissés vides = « inchangé »
    setNewDomainConfig({
      organization_id: dc.organization_id, name: dc.name ?? '', domain: dc.domain ?? '',
      join_user: dc.join_user ?? '', join_password: '', default_ou: dc.default_ou ?? '',
      wifi_ssid: dc.wifi_ssid ?? '', wifi_password: '',
    })
  }

  const cancelEditDomainConfig = () => { setEditingDcId(null); setNewDomainConfig(EMPTY_DOMAIN_CONFIG) }

  const submitDomainConfig = () => {
    if (!auth) return
    if (!newDomainConfig.organization_id || !newDomainConfig.name || !newDomainConfig.domain) { toast.error('Organisation, nom et domaine requis'); return }
    if (editingDcId !== null) {
      // PATCH : on n'envoie les mots de passe que s'ils ont été saisis (vide = conserver l'existant, sinon on les effacerait)
      const body: any = {
        name: newDomainConfig.name, domain: newDomainConfig.domain, join_user: newDomainConfig.join_user,
        default_ou: newDomainConfig.default_ou, wifi_ssid: newDomainConfig.wifi_ssid,
      }
      if (newDomainConfig.join_password) body.join_password = newDomainConfig.join_password
      if (newDomainConfig.wifi_password) body.wifi_password = newDomainConfig.wifi_password
      fetch(`${API_URL}/domain-configs/${editingDcId}`, { method: 'PATCH', headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(r => { if (r.ok) { fetchDomainConfigs(auth.token); cancelEditDomainConfig(); toast.success('Configuration AD mise à jour') } else throw new Error() })
        .catch(() => toast.error('Erreur'))
    } else {
      fetch(`${API_URL}/domain-configs`, { method: 'POST', headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' }, body: JSON.stringify(newDomainConfig) })
        .then(r => { if (r.ok) { fetchDomainConfigs(auth.token); setNewDomainConfig(EMPTY_DOMAIN_CONFIG); toast.success('Configuration AD ajoutée') } else throw new Error() })
        .catch(() => toast.error('Erreur'))
    }
  }

  // Tunnels VPN clients (routage site-à-site)
  const [vpnTunnels, setVpnTunnels] = useState<VpnTunnel[]>([])
  const [newVpnTunnel, setNewVpnTunnel] = useState({ organization_id: 0, name: '', ovpn_config: '', remote_dns: '', route_cidr: '', vpn_username: '', vpn_password: '', requires_totp: false, enabled: true })
  const [applyingTunnelId, setApplyingTunnelId] = useState<number | null>(null)

  // Login 2FA
  const [pendingTotp, setPendingTotp] = useState<{temp_token: string} | null>(null)
  const [totpLoginCode, setTotpLoginCode] = useState('')

  // ── Chargement des données ──────────────────────────────────────────────────

  const fetchAll = (token: string, orgFilter: number | null = null) => {
    setLoading(true)
    setError(null)  // repart propre : sinon une erreur précédente (ex. « Session expirée » sur token périmé) reste affichée après une reconnexion réussie
    const url = orgFilter ? `${API_URL}/machines?org_id=${orgFilter}` : `${API_URL}/machines`
    fetch(url, { headers: authHeader(token) })
      .then((res) => { if (res.status === 401) { setAuth(null); throw new Error("Session expirée") } if (!res.ok) throw new Error("Erreur API"); return res.json() })
      .then((data) => { setMachines(data); setLoading(false) })
      .catch((err) => { setError(err.message); setLoading(false) })
  }

  const fetchOrgs = (token: string) => {
    fetch(`${API_URL}/organizations`, { headers: authHeader(token) })
      .then((res) => { if (res.status === 401) setAuth(null); return res.ok ? res.json() : [] })
      .then((data) => setOrgs(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  const fetchUsers = (token: string) => {
    fetch(`${API_URL}/users`, { headers: authHeader(token) })
      .then((res) => { if (res.status === 401) setAuth(null); return res.ok ? res.json() : [] })
      .then((data) => setUsers(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  const fetchImages = (token: string) => {
    fetch(`${API_URL}/images`, { headers: authHeader(token) })
      .then((res) => { if (res.status === 401) setAuth(null); return res.ok ? res.json() : [] })
      .then((data) => setImages(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  const fetchProfiles = (token: string) => {
    fetch(`${API_URL}/profiles`, { headers: authHeader(token) })
      .then((res) => { if (res.status === 401) setAuth(null); return res.ok ? res.json() : [] })
      .then((data) => setProfiles(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  const fetchDriverPacks = (token: string) => {
    fetch(`${API_URL}/drivers`, { headers: authHeader(token) })
      .then((res) => res.ok ? res.json() : [])
      .then((data) => setDriverPacks(Array.isArray(data) ? data.filter((p: any) => p.status === 'ready') : []))
      .catch(() => {})
  }

  const fetchApps = (token: string) => {
    fetch(`${API_URL}/apps`, { headers: authHeader(token) })
      .then((res) => res.ok ? res.json() : [])
      .then((data) => setApps(Array.isArray(data) ? data : []))
      .catch(() => {})
  }


  const fetchDomainConfigs = (token: string, orgId?: number) => {
    const url = orgId ? `${API_URL}/domain-configs?org_id=${orgId}` : `${API_URL}/domain-configs`
    fetch(url, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : [])
      .then(setDomainConfigs)
      .catch(() => {})
  }

  const fetchVpnTunnels = (token: string, orgId?: number) => {
    const url = orgId ? `${API_URL}/vpn-tunnels?org_id=${orgId}` : `${API_URL}/vpn-tunnels`
    fetch(url, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : [])
      .then(setVpnTunnels)
      .catch(() => {})
  }

  const submitTotpLogin = () => {
    if (!pendingTotp) return
    fetch(`${API_URL}/auth/totp/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ temp_token: pendingTotp.temp_token, code: totpLoginCode }),
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => {
        const token = data.access_token
        const payload = JSON.parse(atob(token.split('.')[1]))
        setAuth({ token, role: payload.role, email: payload.email })
        setPendingTotp(null)
        setTotpLoginCode('')
      })
      .catch(() => toast.error('Code incorrect'))
  }

  const handleCsvImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !auth) return
    setCsvImporting(true)
    file.text().then(text =>
      fetch(`${API_URL}/machines/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'text/csv', ...authHeader(auth.token) },
        body: text,
      })
        .then(r => r.ok ? r.json() : Promise.reject('Erreur'))
        .then(res => {
          fetchAll(auth.token, selectedOrg)
          const msg = `${res.created} machine(s) importée(s)${res.skipped ? `, ${res.skipped} ignorée(s)` : ''}${res.errors?.length ? `, ${res.errors.length} erreur(s)` : ''}`
          res.errors?.length ? toast.error(msg) : toast.success(msg)
        })
        .catch(() => toast.error('Erreur lors de l\'import'))
        .finally(() => { setCsvImporting(false); e.target.value = '' })
    )
  }

  const handlePatchOrg = (id: number, patch: OrganizationPatch, label: string) => {
    if (!auth) return
    fetch(`${API_URL}/organizations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify(patch),
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(() => { fetchOrgs(auth.token); toast.success(`${label} enregistré`) })
      .catch(() => toast.error(`Erreur enregistrement ${label.toLowerCase()}`))
  }


  useEffect(() => {
    if (!auth) return
    fetchAll(auth.token, selectedOrg)
    fetchOrgs(auth.token)
    fetchProfiles(auth.token)
    if (auth.role === 'admin') { fetchUsers(auth.token); fetchImages(auth.token); fetchApps(auth.token); fetchDriverPacks(auth.token) }
  }, [auth, selectedOrg])

  useEffect(() => {
    if (!auth) return
    if (auth.role !== 'admin') return
    // Chargement paresseux : on ne récupère les données d'une section que quand son sous-onglet est ouvert
    if (activeTab === 'admin') {
      if (adminSubTab === 'domains') fetchDomainConfigs(auth.token)
      else if (adminSubTab === 'vpn') fetchVpnTunnels(auth.token)
    }
    else if (activeTab === 'infrastructure') fetchHypervisors(auth.token)
  }, [activeTab, adminSubTab])

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
        const msg = JSON.parse(event.data)
        const { mac } = msg
        if (msg.log_line !== undefined) {
          setDeployLogs((prev) => ({
            ...prev,
            [mac]: [...(prev[mac] ?? []), msg.log_line],
          }))
        } else if (msg.dism_progress !== undefined) {
          setMachines((prev) =>
            prev.map((m: Machine) => m.mac === mac ? { ...m, dism_progress: msg.dism_progress } : m)
          )
        } else if (msg.type === 'capture_done') {
          if (msg.success) {
            toast.success(`Capture terminée — ${msg.mac}`)
          } else {
            toast.error(`Échec de la capture — ${msg.mac}`)
          }
          setCaptureRefresh(n => n + 1)
          const hostname = machinesRef.current.find(m => m.mac === mac)?.hostname ?? mac
          setLiveEvents(prev => [{ id: `${Date.now()}-${mac}`, timestamp: Date.now(), mac, hostname, kind: 'capture' as const, success: msg.success }, ...prev].slice(0, 30))
        } else {
          const { status, deployed_at } = msg
          if (status === 'pending') setDeployLogs((prev) => { const n = { ...prev }; delete n[mac]; return n })
          setMachines((prev) =>
            prev.map((m: Machine) => m.mac === mac ? { ...m, status, deployed_at: deployed_at ?? m.deployed_at, dism_progress: status === 'deployed' ? 100 : m.dism_progress } : m)
          )
          const hostname = machinesRef.current.find(m => m.mac === mac)?.hostname ?? mac
          setLiveEvents(prev => [{ id: `${Date.now()}-${mac}`, timestamp: Date.now(), mac, hostname, kind: 'status' as const, status }, ...prev].slice(0, 30))
        }
      }

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000)
      }

      ws.onerror = () => {}
    }

    connect()
    return () => { clearTimeout(reconnectTimer); ws?.close() }
  }, [auth])

  if (pendingTotp) return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4">
        <h1 className="text-white text-lg font-bold text-center">Double authentification</h1>
        <p className="text-slate-400 text-xs text-center">Saisissez le code a 6 chiffres de votre application d'authentification</p>
        <input autoFocus maxLength={6} placeholder="000000" value={totpLoginCode}
          onChange={e => setTotpLoginCode(e.target.value.replace(/\D/g, ''))}
          onKeyDown={e => e.key === 'Enter' && submitTotpLogin()}
          className="osiris-input text-center text-xl tracking-widest font-mono w-full" />
        <button onClick={submitTotpLogin} className="osiris-btn w-full">Verifier</button>
        <button onClick={() => { setPendingTotp(null); setTotpLoginCode('') }} className="osiris-btn-ghost w-full text-xs">Retour</button>
      </div>
    </div>
  )
  if (!auth) return <LoginPage onLogin={setAuth} onTotpRequired={token => setPendingTotp({ temp_token: token })} />

  // ── Modale helpers ──────────────────────────────────────────────────────────

  const openEdit = (machine: Machine) => {
    setEditingMac(machine.mac)
    setFormData({ ...machine })
    // Photo de la fiche telle qu'ouverte. À l'enregistrement on ne renvoie que
    // les champs qui en diffèrent : sans ça, un PATCH réécrivait TOUS les champs
    // avec les valeurs chargées à l'ouverture, écrasant en silence ce qui avait
    // changé entre-temps (le 2026-07-16, un driver_pack_id corrigé côté serveur
    // est ainsi revenu à l'ancienne valeur).
    setFormSnapshot({ ...machine })
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

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setSubmitError(null)
    const isEdit = editingMac !== null
    const url    = isEdit ? `${API_URL}/machines/${editingMac}` : `${API_URL}/machines`
    const method = isEdit ? 'PATCH' : 'POST'

    // En édition, on n'envoie QUE les champs réellement modifiés. Renvoyer le
    // formulaire entier réécrivait des champs auxquels on n'avait pas touché,
    // avec les valeurs lues à l'ouverture de la modale — donc périmées dès que
    // le serveur ou quelqu'un d'autre les avait changées entre-temps.
    const payload = isEdit
      ? Object.fromEntries(
          (Object.keys(formData) as (keyof Machine)[])
            .filter((k) => formData[k] !== formSnapshot[k])
            .map((k) => [k, formData[k]]),
        )
      : formData

    if (isEdit && Object.keys(payload).length === 0) {
      closeModal()
      return
    }

    fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify(payload),
    })
      .then(async (res) => {
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "Erreur") }
        return isEdit ? null : res.json()
      })
      .then((data) => {
        closeModal()
        if (data?.password) setOneTimePassword({ hostname: data.hostname, password: data.password })
        else { fetchAll(auth.token, selectedOrg); if (isEdit) toast.success('Machine mise à jour') }
      })
      .catch((err) => setSubmitError(err.message))
  }

  // ── Suppression machine ─────────────────────────────────────────────────────

  const handleDelete = (mac: string) => {
    const url = `${API_URL}/machines/${mac}${deleteDestroyVm ? '?destroy_proxmox=true' : ''}`
    fetch(url, { method: 'DELETE', headers: authHeader(auth.token) })
      .then((res) => { if (!res.ok && res.status !== 204) throw new Error('Erreur suppression') })
      .then(() => { setDeletingMac(null); setDeleteDestroyVm(false); fetchAll(auth.token, selectedOrg) })
      .catch((err) => toast.error(err.message))
  }

  const handleVmPower = (mac: string, action: string) => {
    setVmPowerLoading(prev => ({ ...prev, [mac]: true }))
    fetch(`${API_URL}/machines/${mac}/vm-power`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ action }),
    }).then(r => { if (!r.ok) throw new Error(); toast.success(`VM : ${action} envoyé`) })
      .catch(() => toast.error('Erreur commande VM'))
      .finally(() => {
        setVmPowerLoading(prev => ({ ...prev, [mac]: false }))
        // Refresh statut après 3s
        setTimeout(() => fetchVmStatus(mac), 3000)
      })
  }

  const fetchVmStatus = (mac: string) => {
    fetch(`${API_URL}/machines/${mac}/vm-status`, { headers: authHeader(auth.token) })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setVmPowerState(prev => ({ ...prev, [mac]: data })) })
      .catch(() => {})
  }

  const fetchSnapshots = (mac: string) => {
    setSnapshotsLoading(true)
    fetch(`${API_URL}/machines/${mac}/snapshots`, { headers: authHeader(auth.token) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then((data: SnapshotEntry[]) => setSnapshots(data))
      .catch(() => toast.error('Impossible de charger les snapshots'))
      .finally(() => setSnapshotsLoading(false))
  }

  // Ouvre le panneau latéral de détails pour une machine (logs, historique, BitLocker/LAPS, VM+snapshots).
  const openDetail = (mac: string) => {
    setDetailMac(mac)
    fetchHistory(mac)
    const m = machines.find(x => x.mac === mac)
    if (m?.proxmox_vm_id) {
      fetchVmStatus(mac)
      fetchSnapshots(mac)
    }
  }

  const handleCreateSnapshot = (mac: string) => {
    if (!newSnapName.trim()) return
    setSnapshotCreating(true)
    fetch(`${API_URL}/machines/${mac}/snapshots`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ name: newSnapName.trim(), description: newSnapDesc.trim() }),
    }).then(r => { if (!r.ok) throw new Error(); toast.success('Snapshot créé'); setNewSnapName(''); setNewSnapDesc(''); fetchSnapshots(mac) })
      .catch(() => toast.error('Erreur création snapshot'))
      .finally(() => setSnapshotCreating(false))
  }

  const handleRollback = (mac: string, name: string) => {
    toast(`Restaurer le snapshot "${name}" ?`, {
      description: 'La VM sera arrêtée puis restaurée à cet état.',
      action: {
        label: 'Restaurer',
        onClick: () => {
          fetch(`${API_URL}/machines/${mac}/snapshots/${encodeURIComponent(name)}/rollback`, {
            method: 'POST', headers: authHeader(auth.token),
          }).then(r => { if (!r.ok) throw new Error(); toast.success('Rollback en cours…'); setTimeout(() => fetchVmStatus(mac), 5000) })
            .catch(() => toast.error('Erreur rollback'))
        },
      },
    })
  }

  const handleDeleteSnapshot = (mac: string, name: string) => {
    fetch(`${API_URL}/machines/${mac}/snapshots/${encodeURIComponent(name)}`, {
      method: 'DELETE', headers: authHeader(auth.token),
    }).then(r => { if (!r.ok) throw new Error(); toast.success('Snapshot supprimé'); fetchSnapshots(mac) })
      .catch(() => toast.error('Erreur suppression snapshot'))
  }

  // ── Redéploiement machine ───────────────────────────────────────────────────

  const handleRedeploy = (mac: string, hostname: string) => {
    toast(`Redéployer "${hostname}" ?`, {
      description: "L'OS sera réinstallé au prochain démarrage réseau.",
      action: {
        label: 'Confirmer',
        onClick: () => {
          setRedeployingMac(mac)
          fetch(`${API_URL}/machines/${mac}/status?status=pending`, { method: 'POST', headers: authHeader(auth.token) })
            .then((res) => { if (!res.ok) throw new Error('Erreur') })
            .then(() => toast.success(`${hostname} — en attente de déploiement`))
            .catch((err) => toast.error(err.message))
            .finally(() => setRedeployingMac(null))
        }
      },
      cancel: { label: 'Annuler', onClick: () => {} },
      duration: 8000,
    })
  }

  const handleWol = (mac: string, hostname: string) => {
    fetch(`${API_URL}/machines/${mac}/wol`, { method: 'POST', headers: authHeader(auth.token) })
      .then((res) => { if (!res.ok) throw new Error('Erreur WOL') })
      .then(() => toast.success(`Magic packet envoyé à "${hostname}"`))
      .catch((err) => toast.error(err.message))
  }

  // ── Admin : créer org ───────────────────────────────────────────────────────

  const handleCreateOrg = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    fetch(`${API_URL}/organizations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ name: newOrgName, slug: newOrgSlug }),
    })
      .then((res) => res.json())
      .then(() => { setNewOrgName(''); setNewOrgSlug(''); fetchOrgs(auth.token); toast.success('Organisation créée') })
      .catch(() => toast.error('Erreur création organisation'))
  }

  const handleDeleteOrg = (id: number) => {
    fetch(`${API_URL}/organizations/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(() => { fetchOrgs(auth.token); toast.success('Organisation supprimée') })
      .catch(() => toast.error('Erreur suppression organisation'))
  }

  const handleDeleteUser = (id: number) => {
    fetch(`${API_URL}/users/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(() => { fetchUsers(auth.token); toast.success('Utilisateur supprimé') })
      .catch(() => toast.error('Erreur suppression utilisateur'))
  }

  // ── Admin : créer utilisateur ───────────────────────────────────────────────

  const handleCreateUser = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    fetch(`${API_URL}/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ email: newUserEmail, password: newUserPass, role: newUserRole }),
    })
      .then((res) => { if (!res.ok) throw new Error('Erreur création'); return res.json() })
      .then(() => { setNewUserEmail(''); setNewUserPass(''); fetchUsers(auth.token); toast.success('Utilisateur créé') })
      .catch((err) => toast.error(err.message))
  }

  // ── Admin : catalogue d'applications ────────────────────────────────────────

  const handleCreateApp = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    fetch(`${API_URL}/apps`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({
        name: newAppName, winget_id: newAppWingetId, apt_package: newAppAptPackage,
        category: newAppCategory, icon: newAppIcon,
      }),
    })
      .then((res) => { if (!res.ok) throw new Error('Erreur création'); return res.json() })
      .then(() => {
        setNewAppName(''); setNewAppWingetId(''); setNewAppAptPackage(''); setNewAppIcon('📦')
        fetchApps(auth.token); toast.success('Application ajoutée')
      })
      .catch((err) => toast.error(err.message))
  }

  const handlePatchApp = (id: number, patch: Partial<Application>) => {
    fetch(`${API_URL}/apps/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify(patch),
    })
      .then((res) => { if (!res.ok) throw new Error('Erreur enregistrement'); return res.json() })
      .then(() => { fetchApps(auth.token); toast.success('Application mise à jour') })
      .catch((err) => toast.error(err.message))
  }

  const handleDeleteApp = (id: number) => {
    fetch(`${API_URL}/apps/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(() => { fetchApps(auth.token); toast.success('Application supprimée') })
      .catch(() => toast.error('Erreur suppression application'))
  }

  const handleCreateImage = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    fetch(`${API_URL}/images`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth!.token) },
      body: JSON.stringify(newImage),
    })
      .then((res) => { if (!res.ok) throw new Error('Erreur création'); return res.json() })
      .then(() => { setNewImage({ name: '', version: '', os: 'ubuntu', iso_url: '', wim_name: '' }); fetchImages(auth!.token); toast.success('Image ajoutée — téléchargement en cours') })
      .catch((err) => toast.error(err.message))
  }

  const handleDeleteImage = (id: number) => {
    fetch(`${API_URL}/images/${id}`, { method: 'DELETE', headers: authHeader(auth!.token) })
      .then(() => { fetchImages(auth!.token); toast.success('Image supprimée') })
      .catch(() => toast.error('Erreur suppression image'))
  }

  // ── Sélection en lot ──────────────────────────────────────────────────────
  const toggleSelect = (mac: string) =>
    setSelectedMacs(prev => { const s = new Set(prev); s.has(mac) ? s.delete(mac) : s.add(mac); return s })

  const toggleSelectAll = () =>
    setSelectedMacs(selectedMacs.size === filteredMachines.length && filteredMachines.length > 0
      ? new Set()
      : new Set(filteredMachines.map(m => m.mac)))

  const handleBatchRedeploy = () => {
    if (selectedMacs.size === 0) return
    fetch(`${API_URL}/machines/batch-status`, {
      method: 'POST',
      headers: { ...authHeader(auth!.token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ macs: Array.from(selectedMacs), status: 'pending' }),
    }).then(() => setSelectedMacs(new Set())).catch(() => {})
  }

  const handleBatchWol = () => {
    if (selectedMacs.size === 0) return
    for (const mac of selectedMacs) {
      fetch(`${API_URL}/machines/${mac}/wol`, { method: 'POST', headers: authHeader(auth!.token) }).catch(() => {})
    }
    setSelectedMacs(new Set())
  }

  const fetchHypervisors = (token: string) => {
    fetch(`${API_URL}/hypervisors`, { headers: authHeader(token) })
      .then(r => { if (r.status === 401) setAuth(null); return r.ok ? r.json() : [] })
      .then((data) => setHypervisors(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  const orgName     = (id: number | null | undefined) => orgs.find(o => o.id === id)?.name ?? '—'
  const profileName = (id: number | null | undefined) => profiles.find(p => p.id === id)?.name ?? null

  const filteredMachines = machines.filter(m => {
    const q = search.toLowerCase()
    const matchSearch = !q || m.hostname.toLowerCase().includes(q) || m.client.toLowerCase().includes(q) || m.mac.includes(q) || (m.user_name ?? '').toLowerCase().includes(q)
    const matchStatus = !statusFilter || m.status === statusFilter
    const matchOs     = !osFilter     || m.os === osFilter
    const matchSmoke  = !smokeFilter  || m.smoke_status === 'warnings'
    return matchSearch && matchStatus && matchOs && matchSmoke
  })

  // Tri d'affichage (ne touche ni aux compteurs ni à la sélection, qui restent sur filteredMachines).
  const sortedMachines = sortKey
    ? [...filteredMachines].sort((a, b) => {
        const va = (a[sortKey] ?? '').toString().toLowerCase()
        const vb = (b[sortKey] ?? '').toString().toLowerCase()
        const cmp = va.localeCompare(vb, undefined, { numeric: true })
        return sortDir === 'asc' ? cmp : -cmp
      })
    : filteredMachines

  const statCounts = {
    deployed:  machines.filter(m => m.status === 'deployed').length,
    deploying: machines.filter(m => m.status === 'deploying').length,
    failed:    machines.filter(m => m.status === 'failed').length,
    pending:   machines.filter(m => m.status === 'pending').length,
    smokeWarn: machines.filter(m => m.smoke_status === 'warnings').length,
  }

  // ── Rendu ───────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen text-slate-100 font-sans antialiased">
      <Toaster position="top-right" theme="dark" richColors closeButton duration={4000} />

      {/* ── En-tête ────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-10 bg-[#070b14]/95 backdrop-blur-sm border-b border-slate-800/60">
        {/* ── Barre supérieure ─────────────────────────────────────────── */}
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="osiris-logo-shine flex items-center gap-2.5">
              <IcoOsiris cls="w-5 h-5 text-blue-500" />
              <span className="text-lg font-black tracking-[0.22em] text-white uppercase select-none">Osiris</span>
            </div>
            <div className="hidden sm:flex items-center gap-2 text-[11px] font-mono text-slate-600 border-l border-slate-800 pl-5">
              <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${error ? 'bg-red-500' : 'bg-emerald-500 animate-pulse osiris-live-dot'}`} />
              {error ? 'API hors ligne' : loading ? 'Connexion…' : 'Connecté'}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono text-slate-700 hidden sm:block">{auth.email}</span>
            <button onClick={() => setShowSettingsModal(true)} className="osiris-action-btn" title="Parametres du compte"><IcoGear /></button>
            <button onClick={() => setAuth(null)} className="osiris-btn-ghost text-xs">Deconnexion</button>
          </div>
        </div>
        {/* ── Onglets ──────────────────────────────────────────────────── */}
        <div className="max-w-7xl mx-auto px-6 flex items-center gap-0 border-t border-slate-800/40 overflow-x-auto">
          {([
            { id: 'machines'       as const, label: 'Machines',        adminOnly: false },
            { id: 'dashboard'      as const, label: 'Tableau de bord',  adminOnly: false },
            { id: 'admin'          as const, label: 'Administration',   adminOnly: true  },
            { id: 'infrastructure' as const, label: 'Infrastructure',   adminOnly: true  },
            { id: 'drivers'        as const, label: 'Drivers',          adminOnly: true  },
            { id: 'journal'        as const, label: 'Journal',          adminOnly: true  },
            { id: 'capture'        as const, label: 'Capture',          adminOnly: true  },
          ]).filter(t => !t.adminOnly || auth.role === 'admin').map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`flex-shrink-0 whitespace-nowrap px-5 py-2.5 text-xs font-semibold tracking-wide border-b-2 transition-colors cursor-pointer ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-slate-600 hover:text-slate-300 hover:border-slate-600'
              }`}>
              {tab.label}
            </button>
          ))}
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-8 space-y-8">

        {/* ── Onglet Administration ────────────────────────────────────────── */}
        {activeTab === 'admin' && auth.role === 'admin' && (
          <div className="space-y-6">

            {/* Barre de sous-onglets Administration */}
            <div className="flex items-center gap-1 flex-wrap border-b border-slate-800/60 overflow-x-auto">
              {ADMIN_SUBTABS.map(st => (
                <button key={st.id} onClick={() => setAdminSubTab(st.id)}
                  className={`flex-shrink-0 whitespace-nowrap px-4 py-2 text-xs font-semibold tracking-wide border-b-2 -mb-px transition-colors cursor-pointer ${
                    adminSubTab === st.id ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-600 hover:text-slate-300 hover:border-slate-600'
                  }`}>
                  {st.label}
                </button>
              ))}
            </div>

            {/* Organisations */}
            {adminSubTab === 'orgs' && (
            <div className="osiris-table-wrap p-5 space-y-4">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Organisations clients</h2>
              <ul className="space-y-2">
                {orgs.map(org => (
                  <li key={org.id} className="border-b border-slate-800/50 pb-2 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-white font-medium text-sm">{org.name}</span>
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-xs text-slate-600">{org.slug}</span>
                        <button onClick={() => handleDeleteOrg(org.id)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <input
                        placeholder="Webhook URL (Teams, Slack, Discord…)"
                        defaultValue={org.webhook_url}
                        onBlur={e => { if (e.target.value !== org.webhook_url) handlePatchOrg(org.id, { webhook_url: e.target.value }, 'Webhook') }}
                        className="osiris-input text-[10px] font-mono flex-1"
                      />
                    </div>
                    <div className="flex gap-2">
                      <input
                        placeholder="Collecteur Zabbix (ex: 10.231.248.130) — vide = pas de supervision"
                        defaultValue={org.zabbix_server}
                        onBlur={e => { if (e.target.value !== org.zabbix_server) handlePatchOrg(org.id, { zabbix_server: e.target.value }, 'Collecteur Zabbix') }}
                        className="osiris-input text-[10px] font-mono flex-1"
                      />
                    </div>
                    <div className="flex gap-2">
                      <input
                        placeholder="Préfixe MAC imposé (ex: 02aabbcc) — vide = MAC inchangée"
                        defaultValue={org.mac_prefix}
                        onBlur={e => { if (e.target.value !== org.mac_prefix) handlePatchOrg(org.id, { mac_prefix: e.target.value }, 'Préfixe MAC') }}
                        className="osiris-input text-[10px] font-mono flex-1"
                      />
                      {/* Champ en ecriture seule : l'API ne renvoie jamais le mot de passe.
                          Ne rien saisir ne change rien, la valeur en base est conservee. */}
                      <BiosPasswordField
                        isSet={org.has_bios_password}
                        onSave={v => handlePatchOrg(org.id, { bios_password: v }, 'Mot de passe BIOS')}
                      />
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
            )}

            {/* Utilisateurs */}
            {adminSubTab === 'users' && (
            <div className="osiris-table-wrap p-5 space-y-4">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Utilisateurs</h2>
              <ul className="space-y-1">
                {users.map(u => (
                  <li key={u.id} className="flex items-center justify-between text-sm py-1 border-b border-slate-800/50">
                    <span className="text-white">{u.email}</span>
                    <div className="flex items-center gap-3">
                      <span className={`osiris-os-badge ${u.role === 'admin' ? 'osiris-os-badge--windows' : 'osiris-os-badge--ubuntu'}`}>{u.role}</span>
                      {u.email !== auth.email && (
                        <button onClick={() => handleDeleteUser(u.id)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
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
            )}

            {/* Catalogue d'applications (winget / apt) */}
            {adminSubTab === 'apps' && (
            <div className="osiris-table-wrap p-5 space-y-4">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Applications</h2>
              <ul className="space-y-1 max-h-64 overflow-y-auto">
                {apps.map(a => (
                  <li key={a.id} className="text-sm py-1 border-b border-slate-800/50 space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-2 min-w-0">
                        <span className="flex-shrink-0">{a.icon}</span>
                        <span className="text-white truncate">{a.name}</span>
                        <span className="text-[10px] text-slate-600 font-mono flex-shrink-0">{a.category}</span>
                      </span>
                      <div className="flex items-center gap-3 flex-shrink-0">
                        <span className="font-mono text-[10px] text-slate-600 truncate max-w-[140px]">{a.winget_id || a.apt_package}</span>
                        {a.apt_package && (
                          <button
                            onClick={() => setEditingAppScript(editingAppScript === a.id ? null : a.id)}
                            className="osiris-action-btn"
                            title="Script de post-installation Linux">
                            {a.linux_post_install ? '🐧✓' : '🐧'}
                          </button>
                        )}
                        <button onClick={() => handleDeleteApp(a.id)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
                      </div>
                    </div>
                    {editingAppScript === a.id && (
                      <div className="space-y-1 pb-2">
                        <p className="text-[10px] text-slate-600 leading-relaxed">
                          Script bash exécuté en root juste après <span className="font-mono">apt-get install {a.apt_package}</span>,
                          au premier démarrage. Sert à configurer le paquet (fichier de conf, activation de service…).
                        </p>
                        <textarea
                          rows={5}
                          placeholder={"# ex :\nsed -i 's/^#Port/Port/' /etc/exemple.conf\nsystemctl restart exemple"}
                          defaultValue={a.linux_post_install ?? ''}
                          onBlur={e => { if (e.target.value !== (a.linux_post_install ?? '')) handlePatchApp(a.id, { linux_post_install: e.target.value }) }}
                          className="osiris-input text-[10px] font-mono w-full" />
                      </div>
                    )}
                  </li>
                ))}
                {apps.length === 0 && <li className="text-slate-700 text-xs font-mono">Aucune application</li>}
              </ul>
              <form onSubmit={handleCreateApp} className="space-y-2 pt-2">
                <div className="flex gap-2">
                  <input required placeholder="Nom (ex: Google Chrome)" value={newAppName} onChange={e => setNewAppName(e.target.value)} className="osiris-input text-xs flex-1 min-w-0" />
                  <input placeholder="Icône (emoji)" value={newAppIcon} onChange={e => setNewAppIcon(e.target.value)} className="osiris-input text-xs w-20 flex-shrink-0 text-center" />
                </div>
                <input placeholder="ID winget (ex: Google.Chrome)" value={newAppWingetId} onChange={e => setNewAppWingetId(e.target.value)} className="osiris-input text-xs w-full font-mono" />
                <input placeholder="Paquet apt (ex: chromium)" value={newAppAptPackage} onChange={e => setNewAppAptPackage(e.target.value)} className="osiris-input text-xs w-full font-mono" />
                <div className="flex gap-2">
                  <select value={newAppCategory} onChange={e => setNewAppCategory(e.target.value)} className="osiris-input text-xs flex-1">
                    <option value="tools">Outils</option>
                    <option value="office">Bureautique</option>
                    <option value="browser">Navigateur</option>
                    <option value="security">Sécurité</option>
                    <option value="dev">Développement</option>
                    <option value="media">Multimédia</option>
                  </select>
                  <button type="submit" className="osiris-btn text-xs px-3 flex-shrink-0">+</button>
                </div>
              </form>
            </div>
            )}

            {/* Profils de déploiement (liste + création + modales) */}
            {adminSubTab === 'profiles' && (
            <ProfilesSection
              token={auth.token}
              profiles={profiles}
              apps={apps}
              onProfilesChanged={() => fetchProfiles(auth.token)}
            />
            )}

            {/* Images OS */}
            {adminSubTab === 'images' && (
            <div className="osiris-table-wrap p-5 space-y-4">
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
                        <button onClick={() => handleDeleteImage(img.id)} className="osiris-action-btn osiris-action-btn--danger flex-shrink-0" title="Supprimer"><IcoX /></button>
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
                    <option value="debian">Debian</option>
                    <option value="windows">Windows</option>
                  </select>
                </div>
                {newImage.os === 'windows' && (
                  <input placeholder="Nom du .wim sur le partage (ex : server2022.wim) — optionnel, vide = install.wim" value={newImage.wim_name} onChange={e => setNewImage({ ...newImage, wim_name: e.target.value })} className="osiris-input text-xs font-mono w-full" />
                )}
                <div className="flex gap-2">
                  <input required placeholder="URL ISO  (https://...)" value={newImage.iso_url} onChange={e => setNewImage({ ...newImage, iso_url: e.target.value })} className="osiris-input text-xs font-mono flex-1 min-w-0" />
                  <button type="submit" className="osiris-btn text-xs flex-shrink-0">↓ Télécharger</button>
                </div>
              </form>
            </div>
            )}

          </div>
        )}

        {/* ── Onglet Tableau de bord ───────────────────────────────────────── */}
        {activeTab === 'dashboard' && (
          <DashboardTab token={auth.token} liveEvents={liveEvents} />
        )}

        {/* ── Onglet Infrastructure ────────────────────────────────────────── */}
        {activeTab === 'infrastructure' && auth.role === 'admin' && (
          <InfrastructureTab
            token={auth.token}
            hypervisors={hypervisors}
            profiles={profiles}
            selectedOrg={selectedOrg}
            onRefreshHypervisors={() => fetchHypervisors(auth.token)}
            onVmCreated={() => fetchAll(auth.token, selectedOrg)}
          />
        )}

        {/* ── Onglet Journal ───────────────────────────────────────────────── */}
        {activeTab === 'journal' && auth.role === 'admin' && (
          <JournalTab token={auth.token} onUnauthorized={() => setAuth(null)} />
        )}

        {/* ── Domaines AD (dans onglet Admin, section separee) ─────────────── */}
        {activeTab === 'admin' && auth.role === 'admin' && adminSubTab === 'domains' && (
          <div className="osiris-table-wrap p-5 space-y-3">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Domaines AD par organisation</h2>
            <p className="text-[10px] text-slate-600">Configurez les credentials AD au niveau de l'organisation. Les profils peuvent utiliser ces configs au lieu de saisir le domaine manuellement.</p>
            {domainConfigs.length > 0 && (
              <div className="space-y-1">
                {domainConfigs.map((dc: any) => (
                  <div key={dc.id} className={`flex items-center justify-between py-1.5 px-3 border rounded text-xs ${editingDcId === dc.id ? 'border-blue-700/70 bg-blue-950/20' : 'border-slate-800/60'}`}>
                    <div>
                      <span className="text-white font-medium">{dc.name}</span>
                      <span className="text-slate-500 ml-3 font-mono">{dc.domain}</span>
                      {dc.join_user && <span className="text-slate-600 ml-2">({dc.join_user})</span>}
                      {dc.default_ou && <span className="text-slate-700 ml-2 font-mono text-[9px]">{dc.default_ou}</span>}
                      {dc.wifi_ssid && <span className="text-slate-700 ml-2 font-mono text-[9px]">WiFi {dc.wifi_ssid}</span>}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => startEditDomainConfig(dc)} className="osiris-action-btn" title="Modifier"><IcoPencil /></button>
                      <button onClick={() => fetch(`${API_URL}/domain-configs/${dc.id}`, { method: 'DELETE', headers: authHeader(auth.token) }).then(r => { if (r.ok) { fetchDomainConfigs(auth.token); if (editingDcId === dc.id) cancelEditDomainConfig() } })} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {editingDcId !== null && (
              <p className="text-[10px] text-blue-400 font-mono">Édition de « {newDomainConfig.name} » — laissez les mots de passe vides pour les conserver.</p>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-slate-800/40">
              <select value={newDomainConfig.organization_id} onChange={e => setNewDomainConfig({...newDomainConfig, organization_id: parseInt(e.target.value)})} disabled={editingDcId !== null} className="osiris-input text-xs disabled:opacity-50">
                <option value={0}>-- Organisation --</option>
                {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
              <input placeholder="Nom (ex: Siege principal)" value={newDomainConfig.name} onChange={e => setNewDomainConfig({...newDomainConfig, name: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="Domaine (ex: corp.local)" value={newDomainConfig.domain} onChange={e => setNewDomainConfig({...newDomainConfig, domain: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="Compte jonction AD" value={newDomainConfig.join_user} onChange={e => setNewDomainConfig({...newDomainConfig, join_user: e.target.value})} className="osiris-input text-xs font-mono" />
              <input type="password" placeholder={editingDcId !== null ? 'Mot de passe jonction (inchangé)' : 'Mot de passe jonction'} value={newDomainConfig.join_password} onChange={e => setNewDomainConfig({...newDomainConfig, join_password: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="OU par defaut (optionnel)" value={newDomainConfig.default_ou} onChange={e => setNewDomainConfig({...newDomainConfig, default_ou: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="SSID WiFi (optionnel)" value={newDomainConfig.wifi_ssid} onChange={e => setNewDomainConfig({...newDomainConfig, wifi_ssid: e.target.value})} className="osiris-input text-xs font-mono" />
              <input type="password" placeholder={editingDcId !== null ? 'Mot de passe WiFi (inchangé)' : 'Mot de passe WiFi'} value={newDomainConfig.wifi_password} onChange={e => setNewDomainConfig({...newDomainConfig, wifi_password: e.target.value})} className="osiris-input text-xs font-mono" />
              <div className={`flex gap-2 col-span-2 ${editingDcId !== null ? 'sm:col-span-3' : 'sm:col-span-1'}`}>
                <button onClick={submitDomainConfig} className="osiris-btn text-xs flex-1">{editingDcId !== null ? 'Enregistrer' : 'Ajouter'}</button>
                {editingDcId !== null && (
                  <button onClick={cancelEditDomainConfig} className="osiris-btn-ghost text-xs">Annuler</button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Tunnels VPN clients (dans onglet Admin, section separee) ──────── */}
        {activeTab === 'admin' && auth.role === 'admin' && adminSubTab === 'vpn' && (
          <div className="osiris-table-wrap p-5 space-y-3">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Tunnels VPN clients</h2>
            <p className="text-[10px] text-slate-600">Un tunnel OpenVPN permanent par client. OSIRIS route automatiquement les machines déployées vers le bon domaine AD (DNS split-horizon + route classless), sans bascule manuelle.</p>
            {vpnTunnels.length > 0 && (
              <div className="space-y-1">
                {vpnTunnels.map((t) => {
                  const orgName = orgs.find(o => o.id === t.organization_id)?.name ?? `Org #${t.organization_id}`
                  const statusColor = t.status === 'active' ? 'text-emerald-400' : t.status === 'failed' ? 'text-red-400' : 'text-slate-500'
                  return (
                    <div key={t.id} className="flex items-center justify-between py-1.5 px-3 border border-slate-800/60 rounded text-xs">
                      <div>
                        <span className="text-white font-medium">{t.name}</span>
                        <span className="text-slate-500 ml-3">{orgName}</span>
                        {t.route_cidr && <span className="text-slate-600 ml-2 font-mono text-[9px]">{t.route_cidr}</span>}
                        {t.remote_dns && <span className="text-slate-700 ml-2 font-mono text-[9px]">DNS {t.remote_dns}</span>}
                        {t.requires_totp && <span className="ml-2 text-[9px] text-amber-400">TOTP requis</span>}
                        <span className={`ml-3 font-mono text-[9px] ${statusColor}`}>{t.status}</span>
                        {!t.enabled && <span className="ml-2 text-[9px] text-slate-700">(désactivé)</span>}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button
                          disabled={applyingTunnelId === t.id}
                          onClick={() => {
                            let totp_code: string | null = null
                            if (t.requires_totp) {
                              totp_code = window.prompt(`Code TOTP actuel pour "${t.name}" (jamais stocké, utilisé une seule fois) :`)
                              if (!totp_code) return
                            }
                            setApplyingTunnelId(t.id)
                            fetch(`${API_URL}/vpn-tunnels/${t.id}/apply`, {
                              method: 'POST',
                              headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' },
                              body: JSON.stringify({ totp_code }),
                            })
                              .then(async r => { if (!r.ok) throw new Error((await r.json()).detail || 'Erreur'); return r.json() })
                              .then(() => { fetchVpnTunnels(auth.token); toast.success('Tunnel appliqué') })
                              .catch((e) => toast.error(e.message || 'Échec de l\'application du tunnel'))
                              .finally(() => setApplyingTunnelId(null))
                          }}
                          className="osiris-btn text-[10px] px-2 py-1"
                        >{applyingTunnelId === t.id ? '...' : 'Appliquer'}</button>
                        <button onClick={() => fetch(`${API_URL}/vpn-tunnels/${t.id}`, { method: 'DELETE', headers: authHeader(auth.token) }).then(async r => { if (r.ok) { fetchVpnTunnels(auth.token); toast.success('Tunnel supprimé') } else { toast.error((await r.json()).detail || 'Erreur') } })} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-slate-800/40">
              <select value={newVpnTunnel.organization_id} onChange={e => setNewVpnTunnel({...newVpnTunnel, organization_id: parseInt(e.target.value)})} className="osiris-input text-xs">
                <option value={0}>-- Organisation --</option>
                {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
              <input placeholder="Nom (ex: Tunnel Midi2i)" value={newVpnTunnel.name} onChange={e => setNewVpnTunnel({...newVpnTunnel, name: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="DNS interne client (ex: 192.0.2.53)" value={newVpnTunnel.remote_dns} onChange={e => setNewVpnTunnel({...newVpnTunnel, remote_dns: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="Réseau client (ex: 10.8.0.0/16)" value={newVpnTunnel.route_cidr} onChange={e => setNewVpnTunnel({...newVpnTunnel, route_cidr: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="Utilisateur auth-user-pass" value={newVpnTunnel.vpn_username} onChange={e => setNewVpnTunnel({...newVpnTunnel, vpn_username: e.target.value})} className="osiris-input text-xs font-mono" />
              <input type="password" placeholder="Mot de passe auth-user-pass" value={newVpnTunnel.vpn_password} onChange={e => setNewVpnTunnel({...newVpnTunnel, vpn_password: e.target.value})} className="osiris-input text-xs font-mono" />
              <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={newVpnTunnel.requires_totp} onChange={e => setNewVpnTunnel({...newVpnTunnel, requires_totp: e.target.checked})} />
                Code TOTP requis à chaque application (jamais stocké)
              </label>
              <textarea placeholder="Contenu du fichier .ovpn (avec certificats inline)" value={newVpnTunnel.ovpn_config} onChange={e => setNewVpnTunnel({...newVpnTunnel, ovpn_config: e.target.value})} rows={4} className="osiris-input text-xs font-mono col-span-2 sm:col-span-3" />
              <button onClick={() => {
                if (!newVpnTunnel.organization_id || !newVpnTunnel.name || !newVpnTunnel.ovpn_config) { toast.error('Organisation, nom et fichier .ovpn requis'); return }
                fetch(`${API_URL}/vpn-tunnels`, { method: 'POST', headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' }, body: JSON.stringify(newVpnTunnel) })
                  .then(async r => { if (r.ok) { fetchVpnTunnels(auth.token); setNewVpnTunnel({ organization_id: 0, name: '', ovpn_config: '', remote_dns: '', route_cidr: '', vpn_username: '', vpn_password: '', requires_totp: false, enabled: true }); toast.success('Tunnel VPN ajouté') } else { toast.error((await r.json()).detail || 'Erreur') } })
                  .catch(() => toast.error('Erreur'))
              }} className="osiris-btn text-xs col-span-2 sm:col-span-1">Ajouter</button>
            </div>
          </div>
        )}

        {/* ── Onglet Capture ───────────────────────────────────────────────── */}
        {activeTab === 'capture' && auth.role === 'admin' && (
          <CaptureTab token={auth.token} machines={machines} refreshSignal={captureRefresh} />
        )}

        {/* ── Onglet Drivers ───────────────────────────────────────────────── */}
        {activeTab === 'drivers' && auth.role === 'admin' && (
          <DriversTab token={auth.token} />
        )}

        {/* ── Onglet Machines ──────────────────────────────────────────────── */}
        {activeTab === 'machines' && <>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-baseline gap-3">
              <h1 className="text-xl font-bold tracking-tight text-white">Parc de déploiement</h1>
              {!loading && !error && (
                <span className="text-xs font-mono text-slate-600">
                  {filteredMachines.length !== machines.length
                    ? `${filteredMachines.length} / ${machines.length}`
                    : machines.length} machine{machines.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="relative">
                <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-600 pointer-events-none"><IcoSearch cls="w-3 h-3" /></span>
                <input type="text" placeholder="Rechercher…" value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="osiris-input text-xs pl-7 w-44" />
              </div>
              <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="osiris-input text-xs w-36">
                <option value="">Tous les statuts</option>
                <option value="pending">En attente</option>
                <option value="deploying">En cours</option>
                <option value="deployed">Déployés</option>
                <option value="failed">Échec</option>
              </select>
              <select value={osFilter} onChange={e => setOsFilter(e.target.value)} className="osiris-input text-xs w-32">
                <option value="">Tous les OS</option>
                <option value="windows">Windows</option>
                <option value="ubuntu">Ubuntu</option>
                <option value="debian">Debian</option>
              </select>
              {machines.some(m => m.smoke_status === 'warnings') && (
                <button
                  onClick={() => setSmokeFilter(f => !f)}
                  className={`osiris-btn text-xs ${smokeFilter ? 'border-amber-600 text-amber-400' : 'text-slate-500'}`}
                  title="Afficher uniquement les machines avec des alertes smoke"
                >
                  Alertes smoke{smokeFilter ? ` (${filteredMachines.length})` : ` (${machines.filter(m => m.smoke_status === 'warnings').length})`}
                </button>
              )}
              {hasActiveFilter && (
                <button onClick={resetFilters} className="osiris-btn-ghost text-xs text-slate-500">
                  Réinitialiser
                </button>
              )}
              <span className="text-[10px] uppercase tracking-widest text-slate-600 font-semibold">Client</span>
              <select value={selectedOrg ?? ''} onChange={(e) => setSelectedOrg(e.target.value ? Number(e.target.value) : null)} className="osiris-input text-xs w-44">
                <option value="">Tous les clients</option>
                {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
              <button
                className={`osiris-btn text-xs ${csvImporting ? 'opacity-50' : ''}`}
                disabled={csvImporting}
                onClick={() => {
                  if (localStorage.getItem('osiris_csv_hint_ok')) {
                    csvFileRef.current?.click()
                  } else {
                    setShowCsvHint(true)
                  }
                }}
              >
                {csvImporting ? 'Import...' : 'Importer CSV'}
              </button>
              <input ref={csvFileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={handleCsvImport} disabled={csvImporting} />
              <a href={`${API_URL}/machines/export`} download="osiris-machines.csv" className="osiris-btn text-xs">Exporter CSV</a>
              <button onClick={openCreate} className="osiris-btn text-xs">+ Enregistrer un PC</button>
            </div>
          </div>
          {!loading && !error && machines.length > 0 && (
            <div className="flex items-center gap-4">
              {statCounts.deployed  > 0 && <button onClick={() => setStatusFilter(s => s === 'deployed'  ? '' : 'deployed')}  className={`inline-flex items-center gap-1.5 text-[10px] font-mono transition-colors ${statusFilter === 'deployed'  ? 'text-emerald-400' : 'text-emerald-700 hover:text-emerald-500'}`}><span className="w-1.5 h-1.5 rounded-full bg-emerald-600 inline-block" />{statCounts.deployed}  déployé{statCounts.deployed  !== 1 ? 's' : ''}</button>}
              {statCounts.deploying > 0 && <button onClick={() => setStatusFilter(s => s === 'deploying' ? '' : 'deploying')} className={`inline-flex items-center gap-1.5 text-[10px] font-mono transition-colors ${statusFilter === 'deploying' ? 'text-blue-400'    : 'text-blue-700    hover:text-blue-500'}`}  ><span className="w-1.5 h-1.5 rounded-full bg-blue-500  inline-block animate-pulse" />{statCounts.deploying} en cours</button>}
              {statCounts.failed    > 0 && <button onClick={() => setStatusFilter(s => s === 'failed'    ? '' : 'failed')}    className={`inline-flex items-center gap-1.5 text-[10px] font-mono transition-colors ${statusFilter === 'failed'    ? 'text-red-400'     : 'text-red-800     hover:text-red-500'}`}    ><span className="w-1.5 h-1.5 rounded-full bg-red-500   inline-block" />{statCounts.failed}    échec{statCounts.failed    !== 1 ? 's' : ''}</button>}
              {statCounts.pending   > 0 && <button onClick={() => setStatusFilter(s => s === 'pending'   ? '' : 'pending')}   className={`inline-flex items-center gap-1.5 text-[10px] font-mono transition-colors ${statusFilter === 'pending'   ? 'text-slate-300'   : 'text-slate-700   hover:text-slate-400'}`}  ><span className="w-1.5 h-1.5 rounded-full bg-slate-500 inline-block" />{statCounts.pending}   en attente</button>}
              {statCounts.smokeWarn > 0 && <button onClick={() => setSmokeFilter(f => !f)} className={`inline-flex items-center gap-1.5 text-[10px] font-mono transition-colors ${smokeFilter ? 'text-amber-400' : 'text-amber-800 hover:text-amber-500'}`}><span className="w-1.5 h-1.5 rounded-full bg-amber-500 inline-block" />{statCounts.smokeWarn} alerte{statCounts.smokeWarn !== 1 ? 's' : ''} smoke</button>}
            </div>
          )}
        </div>

        {/* ── Tableau des machines ─────────────────────────────────────────── */}
        {loading && (
          <div className="osiris-table-wrap">
            <SkeletonRows count={8} cols={6} />
          </div>
        )}
        {error && <div className="border-l-2 border-red-700 pl-4 py-2"><p className="text-red-400 text-sm font-mono">{error}</p></div>}

        {selectedMacs.size > 0 && (
          <div className="flex items-center gap-3 px-4 py-2.5 bg-blue-950/40 border border-blue-800/40 rounded text-xs">
            <span className="text-blue-300 font-semibold">{selectedMacs.size} machine{selectedMacs.size > 1 ? 's' : ''} sélectionnée{selectedMacs.size > 1 ? 's' : ''}</span>
            <button onClick={handleBatchRedeploy} className="osiris-btn text-xs">Redéployer</button>
            <button onClick={handleBatchWol} className="osiris-btn text-xs">WoL</button>
            <button onClick={() => setSelectedMacs(new Set())} className="osiris-btn-ghost text-xs ml-auto">Désélectionner</button>
          </div>
        )}

        {!loading && !error && (
          <div className="osiris-table-wrap osiris-table-scroll overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800/80">
                  <th className="osiris-table-sticky-th px-4 py-3 w-8">
                    <input type="checkbox"
                      checked={selectedMacs.size === filteredMachines.length && filteredMachines.length > 0}
                      ref={el => { if (el) el.indeterminate = selectedMacs.size > 0 && selectedMacs.size < filteredMachines.length }}
                      onChange={toggleSelectAll}
                      className="accent-blue-500 cursor-pointer" />
                  </th>
                  {([
                    { label: "Nom d'hôte",   key: 'hostname' as const },
                    { label: "Adresse MAC",  key: 'mac'      as const },
                    { label: "Client / Org", key: 'client'   as const },
                    { label: "OS",           key: 'os'       as const },
                    { label: "Statut",       key: 'status'   as const },
                    { label: "OU / Actions", key: null },
                  ]).map(col => (
                    <th key={col.label} className="osiris-table-sticky-th text-left px-4 py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600 whitespace-nowrap">
                      {col.key ? (
                        <button
                          onClick={() => toggleSort(col.key!)}
                          className={`inline-flex items-center gap-1 uppercase tracking-widest transition-colors cursor-pointer hover:text-slate-300 ${sortKey === col.key ? 'text-slate-300' : ''}`}
                          title={`Trier par ${col.label}`}
                        >
                          {col.label}
                          <span className="text-[8px] w-2 inline-block">{sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : ''}</span>
                        </button>
                      ) : col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredMachines.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-16 text-center text-slate-700 font-mono text-xs">
                    {machines.length === 0 ? 'Aucune machine enregistrée' : 'Aucun résultat pour cette recherche'}
                  </td></tr>
                ) : sortedMachines.map((machine, i) => (
                  <React.Fragment key={machine.id}>
                  <tr className={`osiris-row osiris-row-in transition-colors ${selectedMacs.has(machine.mac) ? 'bg-blue-950/20' : ''}`} style={{ animationDelay: `${Math.min(i, 18) * 40}ms` }}>
                    <td className="px-4 py-3 w-8">
                      <input type="checkbox" checked={selectedMacs.has(machine.mac)} onChange={() => toggleSelect(machine.mac)} className="accent-blue-500 cursor-pointer" />
                    </td>
                    <td className="px-4 py-3 font-mono font-semibold text-white">
                      {machine.hostname}
                      {profileName(machine.profile_id) && (
                        <span className="block text-[10px] font-mono text-slate-700 mt-0.5 font-normal">{profileName(machine.profile_id)}</span>
                      )}
                    </td>
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
                        {machine.os === 'windows' ? 'Windows' : machine.os === 'ubuntu' ? 'Ubuntu' : machine.os === 'debian' ? 'Debian' : machine.os}
                      </span>
                      {machine.proxmox_vm_id ? (
                        <span className="ml-1 inline-block border border-purple-700/60 text-purple-400 rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider" title={`VMID ${machine.proxmox_vm_id} · ${machine.proxmox_node}`}>VM</span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`osiris-status-badge osiris-status--${machine.status ?? 'pending'}`}>
                        {machine.status ?? 'pending'}
                      </span>
                      {machine.status === 'deploying' && (
                        <div className="mt-1.5 w-28 h-1 bg-slate-800 rounded-full overflow-hidden">
                          {(machine.dism_progress ?? 0) > 0 ? (
                            <div
                              className="h-full bg-blue-500 rounded-full transition-all duration-500"
                              style={{ width: `${machine.dism_progress}%` }}
                            />
                          ) : (
                            <div className="h-full bg-blue-500 rounded-full animate-pulse w-full opacity-40" />
                          )}
                        </div>
                      )}
                      {machine.status === 'deploying' && (machine.dism_progress ?? 0) > 0 && (
                        <span className="block text-[10px] font-mono text-blue-600 mt-0.5">{machine.dism_progress}%</span>
                      )}
                      {machine.deployed_at && machine.status === 'deployed' && (
                        <span className="block text-[10px] font-mono text-slate-700 mt-0.5">
                          {new Date(machine.deployed_at).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })}
                        </span>
                      )}
                      {machine.smoke_status === 'ok' && (
                        <span className="inline-block mt-1 text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded border border-emerald-800 text-emerald-500">Tests OK</span>
                      )}
                      {machine.smoke_status === 'warnings' && (
                        <span className="inline-block mt-1 text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded border border-amber-700 text-amber-400 cursor-pointer"
                          title="Cliquer pour voir les details"
                          onClick={() => openDetail(machine.mac)}>
                          {(() => { try { const t = JSON.parse(machine.smoke_results ?? '[]'); const n = t.filter((x: any) => !x.ok).length; return `${n} alerte${n > 1 ? 's' : ''}` } catch { return 'Alertes' } })()}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-xs text-slate-600 truncate max-w-[100px]" title={machine.ou}>{machine.ou || '—'}</span>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          <button
                            onClick={() => openDetail(machine.mac)}
                            className="osiris-action-btn"
                            title="Détails (logs, historique, LAPS/BitLocker, VM...)"
                          ><IcoChevRight /></button>
                          <button
                            onClick={() => handleWol(machine.mac, machine.hostname)}
                            className="osiris-action-btn"
                            title="Wake-on-LAN"
                          ><IcoPower /></button>
                          {(machine.status === 'deployed' || machine.status === 'failed') && (
                            <button
                              onClick={() => handleRedeploy(machine.mac, machine.hostname)}
                              disabled={redeployingMac === machine.mac}
                              className="osiris-action-btn"
                              title="Redeployer (sans WoL)"
                            >
                              {redeployingMac === machine.mac ? '…' : <IcoRefresh />}
                            </button>
                          )}
                          {(machine.status === 'deployed' || machine.status === 'failed') && (
                            <button
                              onClick={() => redeployNow(machine.mac)}
                              className="osiris-action-btn"
                              title="Redeployer maintenant (pending + WoL en une action)"
                            ><IcoRefresh cls="w-3 h-3 inline" /><IcoPower cls="w-3 h-3 inline" /></button>
                          )}
                          <button onClick={() => openEdit(machine)} className="osiris-action-btn" title="Modifier"><IcoPencil /></button>
                          {auth.role === 'admin' && (
                            <button onClick={() => { setDeletingMac(machine.mac); setDeleteDestroyVm(false) }} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        </>}
      </div>

      {/* ── Panneau latéral : détails machine ─────────────────────────────── */}
      {detailMac && (() => {
        const machine = machines.find(m => m.mac === detailMac)
        if (!machine) return null
        const hv = machine.hypervisor_id ? hypervisors.find(h => h.id === machine.hypervisor_id) : undefined
        const consoleUrl = hv && machine.proxmox_vm_id ? `${hv.url}/?console=kvm&novnc=1&vmid=${machine.proxmox_vm_id}&node=${machine.proxmox_node}` : ''
        return (
          <MachineDetailPanel
            key={detailMac}
            machine={machine}
            isAdmin={auth.role === 'admin'}
            profileName={profileName(machine.profile_id)}
            deployLog={deployLogs[machine.mac] ?? []}
            history={machineHistory[machine.mac] ?? []}
            bitlocker={bitlockerData[machine.mac]}
            onFetchBitlockerKey={() => fetchBitlockerKey(machine.mac)}
            lapsPassword={lapsData[machine.mac]}
            onFetchLapsPassword={() => fetchLapsPassword(machine.mac)}
            onSaveUserName={(name) => fetch(`${API_URL}/machines/${machine.mac}`, { method: 'PATCH', headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' }, body: JSON.stringify({ user_name: name }) }).then(r => { if (r.ok) fetchAll(auth.token) })}
            onSaveUserEmail={(email) => fetch(`${API_URL}/machines/${machine.mac}`, { method: 'PATCH', headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' }, body: JSON.stringify({ user_email: email }) }).then(r => { if (r.ok) fetchAll(auth.token) })}
            onSaveNotes={(notes) => saveNotes(machine.mac, notes)}
            onClose={() => setDetailMac(null)}
            vm={machine.proxmox_vm_id ? {
              consoleUrl,
              powerState: vmPowerState[machine.mac] ?? null,
              powerLoading: !!vmPowerLoading[machine.mac],
              onRefreshStatus: () => fetchVmStatus(machine.mac),
              onPower: (action: string) => handleVmPower(machine.mac, action),
              snapshots,
              snapshotsLoading,
              snapshotCreating,
              newSnapName,
              newSnapDesc,
              onNewSnapNameChange: setNewSnapName,
              onNewSnapDescChange: setNewSnapDesc,
              onCreateSnapshot: () => handleCreateSnapshot(machine.mac),
              onDeleteSnapshot: (name: string) => handleDeleteSnapshot(machine.mac, name),
              onRollback: (name: string) => handleRollback(machine.mac, name),
            } : undefined}
          />
        )
      })()}

      {/* ── Modale : changement de mot de passe ──────────────────────────── */}
      {showSettingsModal && (
        <SettingsModal token={auth.token} onClose={() => setShowSettingsModal(false)} />
      )}

      {/* ── Modale : aide import CSV ─────────────────────────────────────── */}
      {showCsvHint && (
        <div className="osiris-overlay" onClick={e => { if (e.target === e.currentTarget) setShowCsvHint(false) }}>
          <div className="osiris-modal w-full max-w-lg">
            <div className="osiris-modal-header">
              <span className="text-sm font-semibold">Import CSV - format attendu</span>
              <button onClick={() => setShowCsvHint(false)} className="osiris-action-btn"><IcoX /></button>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-xs text-slate-400">Le fichier CSV doit avoir une ligne d'en-tete avec les colonnes suivantes :</p>
              <pre className="text-[11px] bg-slate-950 border border-slate-800 rounded px-4 py-3 text-emerald-400 font-mono overflow-x-auto leading-relaxed">{`mac,hostname,client,os,profile_name
aa:bb:cc:dd:ee:ff,PC-DUPONT,Acme Corp,windows,Windows -- par defaut
11:22:33:44:55:66,SRV-LINUX,Acme Corp,ubuntu,Ubuntu -- par defaut
aa:bb:cc:11:22:33,PC-MARTIN,Autre Client,debian,`}</pre>
              <ul className="text-xs text-slate-500 space-y-1">
                <li><span className="font-mono text-slate-300">mac</span> - adresse MAC (avec ou sans separateurs : ou -)</li>
                <li><span className="font-mono text-slate-300">hostname</span> - nom de la machine</li>
                <li><span className="font-mono text-slate-300">client</span> - nom du client / site</li>
                <li><span className="font-mono text-slate-300">os</span> - <span className="font-mono">ubuntu</span>, <span className="font-mono">windows</span> ou <span className="font-mono">debian</span></li>
                <li><span className="font-mono text-slate-300">profile_name</span> - nom exact d'un profil existant (optionnel, laisser vide si aucun)</li>
              </ul>
              <p className="text-xs text-slate-600">Les machines deja enregistrees (meme MAC) sont ignorees silencieusement.</p>
              <label className="flex items-center gap-2 text-xs text-slate-500 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={csvHintDismiss}
                  onChange={e => setCsvHintDismiss(e.target.checked)}
                  className="accent-blue-500"
                />
                J'ai compris, ne plus afficher ce message
              </label>
            </div>
            <div className="px-5 pb-5 flex justify-end gap-2">
              <button onClick={() => setShowCsvHint(false)} className="osiris-btn-ghost text-xs">Annuler</button>
              <button
                onClick={() => {
                  if (csvHintDismiss) localStorage.setItem('osiris_csv_hint_ok', '1')
                  setShowCsvHint(false)
                  setTimeout(() => csvFileRef.current?.click(), 50)
                }}
                className="osiris-btn text-xs"
              >
                Choisir un fichier
              </button>
            </div>
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
              <button onClick={closeModal} className="text-slate-600 hover:text-slate-300 cursor-pointer transition-colors p-1"><IcoX cls="w-4 h-4" /></button>
            </div>
            {submitError && <div className="mx-6 mt-4 border-l-2 border-red-700 pl-3 py-1"><p className="text-red-400 text-xs font-mono">{submitError}</p></div>}
            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                  Adresse MAC du PC {editingMac && <span className="text-slate-700 normal-case">(non modifiable)</span>}
                </label>
                <input required type="text" placeholder="00:11:22:AA:BB:CC"
                  value={formData.mac} onChange={(e) => setFormData({ ...formData, mac: e.target.value })}
                  disabled={!!editingMac} className={`osiris-input font-mono ${editingMac ? 'opacity-40 cursor-not-allowed' : ''}`} />
                <p className="text-[10px] text-slate-600 leading-relaxed">
                  Identité permanente du poste. Si tu déploies via un adaptateur USB, mets ici la
                  MAC de la <strong>machine</strong>, pas celle de l'adaptateur.
                </p>
              </div>
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                  Adresse MAC de l'adaptateur <span className="text-slate-700 normal-case">(facultatif)</span>
                </label>
                <input type="text" placeholder="00:E0:4C:68:06:36"
                  value={formData.deploy_mac ?? ''} onChange={(e) => setFormData({ ...formData, deploy_mac: e.target.value })}
                  className="osiris-input font-mono" />
                <p className="text-[10px] text-slate-600 leading-relaxed">
                  À renseigner uniquement si tu déploies avec un dongle USB-Ethernet. OSIRIS
                  l'<strong>oublie automatiquement</strong> en fin de déploiement : le dongle
                  redevient utilisable sur une autre machine. Vider le champ le libère tout de suite.
                </p>
              </div>
              <div className="space-y-1.5">
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                  Numéro de série <span className="text-slate-700 normal-case">(recommandé)</span>
                </label>
                <input type="text" placeholder="5CD1234ABC"
                  value={formData.hw_serial ?? ''} onChange={(e) => setFormData({ ...formData, hw_serial: e.target.value })}
                  className="osiris-input font-mono" />
                <p className="text-[10px] text-slate-600 leading-relaxed">
                  Identité stable de la machine (étiquette / BIOS). Indispensable pour les portables
                  sans port RJ45 : avec un adaptateur USB, la MAC vue au démarrage réseau n'est pas
                  celle de la machine. WinPE s'identifie en priorité par ce numéro.
                </p>
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
                    <option value="debian">Debian</option>
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
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Client <span className="text-slate-700 normal-case font-normal">(optionnel)</span></label>
                  <input type="text" placeholder="Acme Corp."
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
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">Chemin OU Active Directory <span className="text-slate-700 normal-case font-normal">(optionnel — uniquement si jonction AD)</span></label>
                  <input type="text" placeholder="OU=Workstations,DC=humans,DC=local (vide = conteneur par defaut)"
                    value={formData.ou} onChange={(e) => setFormData({ ...formData, ou: e.target.value })}
                    className="osiris-input font-mono text-xs" />
                </div>
              )}
              {formData.os === 'windows' && (
                <div className="space-y-1.5">
                  <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                    Pack de drivers
                    <span className="ml-1 text-slate-700 normal-case font-normal">(optionnel — injection ciblée du bon modèle)</span>
                  </label>
                  <select value={formData.driver_pack_id ?? ''} onChange={(e) => setFormData({ ...formData, driver_pack_id: e.target.value ? Number(e.target.value) : null })} className="osiris-input text-xs">
                    <option value="">— Tous les drivers téléchargés (plus lent) —</option>
                    {driverPacks.map((p: any) => <option key={p.id} value={p.id}>{p.vendor.toUpperCase()} · {p.model} [{p.os_code}]</option>)}
                  </select>
                  {driverPacks.length === 0 && <p className="text-[10px] text-slate-600">Aucun pack téléchargé — va dans l'onglet Drivers pour en télécharger un.</p>}
                </div>
              )}
              <div className="space-y-1.5 pt-1">
                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input type="checkbox" checked={formData.supervised ?? true}
                    onChange={e => setFormData({ ...formData, supervised: e.target.checked })}
                    className="accent-blue-500" />
                  Superviser cette machine (agent Zabbix)
                </label>
                <p className="text-[10px] text-slate-600 leading-relaxed">
                  {(() => {
                    const org = orgs.find(o => o.id === formData.organization_id)
                    if (!org) return "L'agent n'est installé que si l'organisation de la machine déclare un collecteur Zabbix — celle-ci n'en a pas encore."
                    return org.zabbix_server
                      ? `Agent en mode actif vers ${org.zabbix_server} (TCP 10051).`
                      : `${org.name} n'a pas de collecteur Zabbix : à renseigner dans Administration › Organisations.`
                  })()}
                </p>
              </div>
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
              {machines.find(m => m.mac === deletingMac)?.proxmox_vm_id ? (
                <label className="flex items-center gap-2 text-xs text-red-400 cursor-pointer">
                  <input type="checkbox" checked={deleteDestroyVm} onChange={e => setDeleteDestroyVm(e.target.checked)} className="accent-red-500" />
                  Supprimer aussi la VM dans Proxmox (VMID {machines.find(m => m.mac === deletingMac)?.proxmox_vm_id})
                </label>
              ) : null}
              <div className="flex gap-3 justify-end">
                <button onClick={() => { setDeletingMac(null); setDeleteDestroyVm(false) }} className="osiris-btn-ghost">Annuler</button>
                <button onClick={() => handleDelete(deletingMac!)} className="osiris-btn osiris-btn--danger">Supprimer</button>
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
