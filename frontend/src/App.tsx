// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import React, { useEffect, useRef, useState } from 'react'
import { Toaster, toast } from 'sonner'
import { QRCodeSVG } from 'qrcode.react'
import './App.css'
import type {
  AuthState, Organization, WimFile, Machine, DriverPack, Profile, Application,
  DeploymentEvent, Hypervisor, ProxmoxTemplate, ProxmoxNode, OsImage, SnapshotEntry, AuditLogEntry,
} from './types'
import { ACTION_META, IMAGE_STATUS, formatDetails, formatMac, EMPTY_FORM, authHeader } from './types'
import {
  IcoOsiris, IcoDownload, IcoRefresh, IcoSearch, IcoPower, IcoPencil, IcoX, IcoCheck,
  IcoChevDown, IcoChevUp, IcoChevRight, IcoGear, IcoTerminal, IcoCamera,
} from './icons'
import { LoginPage } from './LoginPage'
import { IntegrationsTab } from './IntegrationsTab'

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

export default function App() {
  const [auth, setAuthState] = useState<AuthState | null>(loadAuth)
  const setAuth = (a: AuthState | null) => { saveAuth(a); setAuthState(a) }

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
  const [deletingMac, setDeletingMac]         = useState<string | null>(null)
  const [deleteDestroyVm, setDeleteDestroyVm] = useState(false)
  const [vmPowerState, setVmPowerState]       = useState<Record<string, { status: string; cpu: number; mem_mb: number } | null>>({})
  const [vmPowerLoading, setVmPowerLoading]   = useState<Record<string, boolean>>({})
  const [snapshotsMac, setSnapshotsMac]       = useState<string | null>(null)
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

  // ── Section admin : gestion des orgs et users ──────────────────────────────
  const [captureJobs, setCaptureJobs]   = useState<{mac:string;wim_name:string;status:string;registered_at:string;finished_at?:string}[]>([])
  const [captureMac, setCaptureMac]     = useState('')
  const [captureWim, setCaptureWim]     = useState('')
  const [captureStep, setCaptureStep]   = useState(1)
  const [wims, setWims]                 = useState<WimFile[]>([])
  const [showWimPicker, setShowWimPicker] = useState<'new' | 'edit' | null>(null)
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

  // ── Profils ────────────────────────────────────────────────────────────────
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [editingProfile, setEditingProfile] = useState<Profile | null>(null)
  const [apps, setApps] = useState<Application[]>([])

  // ── Images OS ──────────────────────────────────────────────────────────────
  const [images, setImages] = useState<OsImage[]>([])
  const [newImage, setNewImage] = useState({ name: '', version: '', os: 'ubuntu', iso_url: '' })
  const [newProfile, setNewProfile] = useState<Partial<Profile>>({ os: 'ubuntu', name: '', locale: 'fr_FR.UTF-8', keyboard: 'fr', timezone: 'Europe/Paris', default_user: 'osiris', extra_packages: '', join_domain: true, domain: 'entreprise.local', domain_join_user: '', domain_join_password: '', win_image: '', win_index: 6, enable_bitlocker: true, bitlocker_pin: false, network_drives: '[]', printers: '[]', post_script: '', tv_suffix: '', app_ids: '', laps_rotation_days: 0, machine_type: 'workstation', ssh_authorized_keys: '' })

  // ── Infrastructure (Hyperviseurs) ──────────────────────────────────────────
  const [hypervisors, setHypervisors]   = useState<Hypervisor[]>([])
  const [newHv, setNewHv]               = useState({ name: '', url: '', token_id: '', token_secret: '', tls_verify: false, snippets_storage: '' })
  const [hvTestResult, setHvTestResult] = useState<Record<number, { ok: boolean; proxmox_version?: string; nodes?: ProxmoxNode[]; error?: string } | null>>({})
  const [hvTesting, setHvTesting]       = useState<Record<number, boolean>>({})
  // Création de VM
  const [showVmForm, setShowVmForm]     = useState(false)
  const [vmHvId, setVmHvId]             = useState<number | ''>('')
  const [vmNode, setVmNode]             = useState('')
  const [vmStorages, setVmStorages]     = useState<{storage:string;type:string;avail_gb:number;total_gb:number}[]>([])
  const [vmNetworks, setVmNetworks]     = useState<{iface:string;type:string;address:string}[]>([])
  const [vmNodes, setVmNodes]           = useState<ProxmoxNode[]>([])
  const [vmForm, setVmForm]             = useState({ hostname: '', client: '', os: 'ubuntu', profile_id: '', ou: '', storage: '', bridge: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, iso: '', boot_mode: 'pxe', cloud_template_id: '' })
  const [vmTemplates, setVmTemplates]   = useState<ProxmoxTemplate[]>([])
  const [vmCreating, setVmCreating]     = useState(false)

  // ── Drivers ────────────────────────────────────────────────────────────────
  const [drivers, setDrivers]           = useState<DriverPack[]>([])
  const [driversLoading, setDriversLoading] = useState(false)
  const [syncing, setSyncing]           = useState<string | null>(null)
  const [downloadingPack, setDownloadingPack] = useState<number | null>(null)
  const [driverSearch, setDriverSearch]       = useState('')
  const [expandedVendors, setExpandedVendors] = useState<Set<string>>(new Set())

  // ── Sélection en lot ──────────────────────────────────────────────────────
  const [selectedMacs, setSelectedMacs] = useState<Set<string>>(new Set())

  // ── Logs déploiement + historique ─────────────────────────────────────────
  const [deployLogs, setDeployLogs]         = useState<Record<string, string[]>>({})
  const [expandedLogs, setExpandedLogs]     = useState<Set<string>>(new Set())
  const [machineHistory, setMachineHistory] = useState<Record<string, DeploymentEvent[]>>({})
  const logEndRefs = useRef<Record<string, HTMLPreElement | null>>({})
  const [bitlockerData, setBitlockerData] = useState<Record<string, { key: string | null, pin: string | null }>>({})
  const [lapsData, setLapsData] = useState<Record<string, string>>({})
  const [editingNotes, setEditingNotes] = useState<Record<string, string>>({})

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

  const resetFilters = () => { setSearch(''); setStatusFilter(''); setOsFilter(''); setSmokeFilter(false) }
  const hasActiveFilter = !!(search || statusFilter || osFilter || smokeFilter)

  // ── Changement de mot de passe ─────────────────────────────────────────────
  const [showSettingsModal, setShowSettingsModal] = useState(false)
  const [settingsTab, setSettingsTab] = useState<'password' | 'totp' | 'apikeys' | 'integrations'>('password')
  const [apiKeys, setApiKeys] = useState<any[]>([])
  const [newKeyName, setNewKeyName] = useState('')
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNew, setPwNew]         = useState('')
  const [pwConfirm, setPwConfirm] = useState('')
  const [pwError, setPwError]     = useState<string | null>(null)
  const [pwSuccess, setPwSuccess] = useState(false)
  const [pwLoading, setPwLoading] = useState(false)

  // ── Journal d'activité ──────────────────────────────────────────────────────
  const [auditLogs, setAuditLogs]         = useState<AuditLogEntry[]>([])
  const [auditLoading, setAuditLoading]   = useState(false)
  const [auditFilterAction, setAuditFilterAction] = useState('')
  const [auditFilterEmail, setAuditFilterEmail]   = useState('')
  const [auditFilterMac, setAuditFilterMac]       = useState('')

  // Dashboard
  const [dashboard, setDashboard] = useState<any>(null)
  const [dashboardLoading, setDashboardLoading] = useState(false)

  // Domaines AD par organisation
  const [domainConfigs, setDomainConfigs] = useState<any[]>([])
  const [newDomainConfig, setNewDomainConfig] = useState({ organization_id: 0, name: '', domain: '', join_user: '', join_password: '', default_ou: '' })

  // 2FA
  const [totpSetup, setTotpSetup] = useState<{secret: string, uri: string} | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [totpEnabled, setTotpEnabled] = useState(false)
  const [totpDisablePassword, setTotpDisablePassword] = useState('')
  const [totpStep, setTotpStep] = useState<null | 'setup' | 'confirm_disable'>(null)

  // Login 2FA
  const [pendingTotp, setPendingTotp] = useState<{temp_token: string} | null>(null)
  const [totpLoginCode, setTotpLoginCode] = useState('')

  // ── Chargement des données ──────────────────────────────────────────────────

  const fetchAll = (token: string, orgFilter: number | null = null) => {
    setLoading(true)
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

  const fetchApps = (token: string) => {
    fetch(`${API_URL}/apps`, { headers: authHeader(token) })
      .then((res) => res.ok ? res.json() : [])
      .then((data) => setApps(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  const fetchCaptures = (token: string) => {
    fetch(`${API_URL}/capture`, { headers: authHeader(token) })
      .then(r => r.json()).then(d => setCaptureJobs(d.jobs ?? []))
      .catch(() => {})
  }

  const handleRegisterCapture = () => {
    if (!captureMac || !captureWim) return
    fetch(`${API_URL}/capture/register?mac=${encodeURIComponent(captureMac)}&wim_name=${encodeURIComponent(captureWim)}`,
      { method: 'POST', headers: authHeader(auth!.token) })
      .then(r => { if (!r.ok) throw new Error('Erreur'); return r.json() })
      .then(() => {
        fetchCaptures(auth!.token)
        setCaptureStep(4)
        toast.success('Machine enregistrée en mode capture — démarrez-la en PXE !')
      })
      .catch(() => toast.error('Erreur lors de l\'enregistrement'))
  }

  const handleDeleteCapture = (mac: string) => {
    fetch(`${API_URL}/capture/${mac}`, { method: 'DELETE', headers: authHeader(auth!.token) })
      .then(() => { fetchCaptures(auth!.token); toast.success('Job de capture supprimé') })
  }

  const fetchDashboard = (token: string) => {
    setDashboardLoading(true)
    fetch(`${API_URL}/dashboard`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setDashboard(data); setDashboardLoading(false) })
      .catch(() => { setDashboard({}); setDashboardLoading(false) })
  }

  const fetchDomainConfigs = (token: string, orgId?: number) => {
    const url = orgId ? `${API_URL}/domain-configs?org_id=${orgId}` : `${API_URL}/domain-configs`
    fetch(url, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : [])
      .then(setDomainConfigs)
      .catch(() => {})
  }

  const fetchTotpStatus = (token: string) => {
    fetch(`${API_URL}/auth/totp/status`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setTotpEnabled(data.totp_enabled) })
      .catch(() => {})
  }

  const startTotpSetup = () => {
    if (!auth) return
    fetch(`${API_URL}/auth/totp/setup`, { headers: authHeader(auth.token) })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setTotpSetup({ secret: data.secret, uri: data.uri }); setTotpStep('setup'); setTotpCode('') })
      .catch(() => toast.error('Impossible de demarrer la configuration 2FA'))
  }

  const confirmTotpEnable = () => {
    if (!auth || !totpSetup) return
    fetch(`${API_URL}/auth/totp/enable`, {
      method: 'POST',
      headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ secret: totpSetup.secret, code: totpCode }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(() => { setTotpEnabled(true); setTotpStep(null); setTotpSetup(null); toast.success('Double authentification activee') })
      .catch(() => toast.error('Code incorrect ou expire'))
  }

  const disableTotp = () => {
    if (!auth) return
    fetch(`${API_URL}/auth/totp/disable`, {
      method: 'POST',
      headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: totpDisablePassword }),
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(() => { setTotpEnabled(false); setTotpStep(null); setTotpDisablePassword(''); toast.success('Double authentification desactivee') })
      .catch(() => toast.error('Mot de passe incorrect'))
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

  const fetchApiKeys = (token: string) => {
    fetch(`${API_URL}/auth/api-keys`, { headers: authHeader(token) })
      .then(r => r.ok ? r.json() : [])
      .then(setApiKeys)
      .catch(() => {})
  }

  const createApiKey = () => {
    if (!auth || !newKeyName.trim()) return
    fetch(`${API_URL}/auth/api-keys`, {
      method: 'POST',
      headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newKeyName.trim() }),
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { setCreatedKey(data.key); setNewKeyName(''); fetchApiKeys(auth.token); toast.success('Cle creee') })
      .catch(() => toast.error('Erreur creation cle'))
  }

  const revokeApiKey = (id: number) => {
    if (!auth) return
    fetch(`${API_URL}/auth/api-keys/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(r => { if (r.ok) { fetchApiKeys(auth.token); toast.success('Cle revoquee') } else throw new Error() })
      .catch(() => toast.error('Erreur revocation'))
  }

  const fetchWims = () => {
    if (!auth) return
    fetch(`${API_URL}/wims`, { headers: authHeader(auth.token) })
      .then(r => r.ok ? r.json() : [])
      .then(data => setWims(Array.isArray(data) ? data : []))
      .catch(() => {})
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

  const handlePatchOrg = (id: number, webhook_url: string) => {
    if (!auth) return
    fetch(`${API_URL}/organizations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ webhook_url }),
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(() => { fetchOrgs(auth.token); toast.success('Webhook enregistré') })
      .catch(() => toast.error('Erreur enregistrement webhook'))
  }

  const fetchAuditLogs = (token: string, action = auditFilterAction, email = auditFilterEmail, mac = auditFilterMac) => {
    setAuditLoading(true)
    const params = new URLSearchParams({ limit: '100' })
    if (action)  params.set('action', action)
    if (email)   params.set('user_email', email)
    if (mac)     params.set('mac', mac)
    fetch(`${API_URL}/audit-logs?${params}`, { headers: authHeader(token) })
      .then((res) => { if (res.status === 401) setAuth(null); return res.ok ? res.json() : [] })
      .then((data) => { setAuditLogs(Array.isArray(data) ? data : []); setAuditLoading(false) })
      .catch(() => setAuditLoading(false))
  }

  useEffect(() => {
    if (!auth) return
    fetchAll(auth.token, selectedOrg)
    fetchOrgs(auth.token)
    fetchProfiles(auth.token)
    if (auth.role === 'admin') { fetchUsers(auth.token); fetchImages(auth.token); fetchApps(auth.token) }
  }, [auth, selectedOrg])

  useEffect(() => {
    if (!auth) return
    if (activeTab === 'dashboard') { fetchDashboard(auth.token); return }
    if (auth.role !== 'admin') return
    if (activeTab === 'drivers') fetchDrivers(auth.token)
    else if (activeTab === 'journal') fetchAuditLogs(auth.token)
    else if (activeTab === 'admin') { fetchDomainConfigs(auth.token); fetchTotpStatus(auth.token) }
    else if (activeTab === 'capture') fetchCaptures(auth.token)
    else if (activeTab === 'infrastructure') fetchHypervisors(auth.token)
  }, [activeTab])

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
          if (auth) fetchCaptures(auth.token)
        } else {
          const { status, deployed_at } = msg
          if (status === 'pending') setDeployLogs((prev) => { const n = { ...prev }; delete n[mac]; return n })
          setMachines((prev) =>
            prev.map((m: Machine) => m.mac === mac ? { ...m, status, deployed_at: deployed_at ?? m.deployed_at, dism_progress: status === 'deployed' ? 100 : m.dism_progress } : m)
          )
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

  useEffect(() => {
    for (const mac of Array.from(expandedLogs)) {
      const el = logEndRefs.current[mac]
      if (el) el.scrollTop = el.scrollHeight
    }
  }, [deployLogs, expandedLogs])

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

  const handleCreateProfile = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    fetch(`${API_URL}/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify(newProfile),
    })
      .then((res) => { if (!res.ok) throw new Error('Erreur création'); return res.json() })
      .then(() => {
        setNewProfile({ os: 'ubuntu', name: '', locale: 'fr_FR.UTF-8', keyboard: 'fr', timezone: 'Europe/Paris', default_user: 'osiris', extra_packages: '', join_domain: true, domain: 'entreprise.local', domain_join_user: '', domain_join_password: '', win_image: '', win_index: 6, enable_bitlocker: true, bitlocker_pin: false, network_drives: '[]', printers: '[]', post_script: '', tv_suffix: '', app_ids: '', laps_rotation_days: 0, machine_type: 'workstation', ssh_authorized_keys: '' })
        fetchProfiles(auth.token)
        toast.success('Profil créé')
      })
      .catch((err) => toast.error(err.message))
  }

  const handleCreateImage = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    fetch(`${API_URL}/images`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth!.token) },
      body: JSON.stringify(newImage),
    })
      .then((res) => { if (!res.ok) throw new Error('Erreur création'); return res.json() })
      .then(() => { setNewImage({ name: '', version: '', os: 'ubuntu', iso_url: '' }); fetchImages(auth!.token); toast.success('Image ajoutée — téléchargement en cours') })
      .catch((err) => toast.error(err.message))
  }

  const handleDeleteImage = (id: number) => {
    fetch(`${API_URL}/images/${id}`, { method: 'DELETE', headers: authHeader(auth!.token) })
      .then(() => { fetchImages(auth!.token); toast.success('Image supprimée') })
      .catch(() => toast.error('Erreur suppression image'))
  }

  const handleDeleteProfile = (id: number) => {
    fetch(`${API_URL}/profiles/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(r => { if (r.ok) { fetchProfiles(auth.token); toast.success('Profil supprimé') } })
      .catch(() => toast.error('Erreur suppression profil'))
  }

  const handleCloneProfile = (id: number) => {
    fetch(`${API_URL}/profiles/${id}/clone`, { method: 'POST', headers: authHeader(auth.token) })
      .then(r => { if (r.ok) { fetchProfiles(auth.token); toast.success('Profil duplique') } else throw new Error() })
      .catch(() => toast.error('Erreur duplication profil'))
  }

  const handlePatchProfile = (id: number, patch: Partial<Profile>) => {
    fetch(`${API_URL}/profiles/${id}`, {
      method: 'PATCH',
      headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
      .then(r => { if (r.ok) { fetchProfiles(auth.token); toast.success('Profil mis à jour') } })
      .catch(() => toast.error('Erreur mise à jour profil'))
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

  // ── Drivers ────────────────────────────────────────────────────────────────

  const fetchDrivers = (token: string, vendor = 'all') => {
    setDriversLoading(true)
    const qs = vendor !== 'all' ? `?vendor=${vendor}` : ''
    fetch(`${API_URL}/drivers${qs}`, { headers: authHeader(token) })
      .then((r) => r.json())
      .then((d) => setDrivers(Array.isArray(d) ? d : []))
      .catch(() => {})
      .finally(() => setDriversLoading(false))
  }

  const fetchHypervisors = (token: string) => {
    fetch(`${API_URL}/hypervisors`, { headers: authHeader(token) })
      .then(r => { if (r.status === 401) setAuth(null); return r.ok ? r.json() : [] })
      .then((data) => setHypervisors(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  const handleCreateHv = (e: React.FormEvent) => {
    e.preventDefault()
    fetch(`${API_URL}/hypervisors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({ ...newHv, type: 'proxmox' }),
    }).then(r => { if (r.ok) { fetchHypervisors(auth.token); setNewHv({ name: '', url: '', token_id: '', token_secret: '', tls_verify: false, snippets_storage: '' }); toast.success('Hyperviseur ajouté') } else throw new Error() })
      .catch(() => toast.error('Erreur création hyperviseur'))
  }

  const handleDeleteHv = (id: number) => {
    fetch(`${API_URL}/hypervisors/${id}`, { method: 'DELETE', headers: authHeader(auth.token) })
      .then(r => { if (r.ok) { fetchHypervisors(auth.token); toast.success('Hyperviseur supprimé') } })
  }

  const handleTestHv = (id: number) => {
    setHvTesting(prev => ({ ...prev, [id]: true }))
    setHvTestResult(prev => ({ ...prev, [id]: null }))
    fetch(`${API_URL}/hypervisors/${id}/test`, { method: 'POST', headers: authHeader(auth.token) })
      .then(async r => {
        const data = await r.json()
        if (r.ok) setHvTestResult(prev => ({ ...prev, [id]: { ok: true, ...data } }))
        else setHvTestResult(prev => ({ ...prev, [id]: { ok: false, error: data.detail ?? 'Erreur inconnue' } }))
      })
      .catch(() => setHvTestResult(prev => ({ ...prev, [id]: { ok: false, error: 'Impossible de joindre OSIRIS' } })))
      .finally(() => setHvTesting(prev => ({ ...prev, [id]: false })))
  }

  const loadVmResources = (hvId: number, node: string) => {
    setVmStorages([]); setVmNetworks([])
    const h = authHeader(auth.token)
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/storages`, { headers: h })
      .then(r => r.json()).then(setVmStorages).catch(() => {})
    fetch(`${API_URL}/hypervisors/${hvId}/nodes/${node}/networks`, { headers: h })
      .then(r => r.json()).then(setVmNetworks).catch(() => {})
  }

  const handleVmHvChange = (hvId: number) => {
    setVmHvId(hvId); setVmNode(''); setVmStorages([]); setVmNetworks([]); setVmNodes([])
    setVmForm(f => ({ ...f, storage: '', bridge: '' }))
    fetch(`${API_URL}/hypervisors/${hvId}/nodes`, { headers: authHeader(auth.token) })
      .then(r => r.json()).then((nodes: ProxmoxNode[]) => {
        setVmNodes(nodes)
        if (nodes.length === 1) {
          setVmNode(nodes[0].node)
          loadVmResources(hvId, nodes[0].node)
        }
      }).catch(() => {})
  }

  const handleVmNodeChange = (node: string) => {
    setVmNode(node)
    setVmStorages([]); setVmNetworks([]); setVmTemplates([])
    setVmForm(f => ({ ...f, storage: '', bridge: '', cloud_template_id: '' }))
    if (vmHvId) {
      loadVmResources(Number(vmHvId), node)
      fetch(`${API_URL}/hypervisors/${vmHvId}/nodes/${node}/templates`, { headers: authHeader(auth.token) })
        .then(r => r.json()).then(setVmTemplates).catch(() => {})
    }
  }

  const handleCreateVm = (e: React.FormEvent) => {
    e.preventDefault()
    if (!vmHvId || !vmNode) return
    setVmCreating(true)
    fetch(`${API_URL}/hypervisors/${vmHvId}/create-vm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(auth.token) },
      body: JSON.stringify({
        ...vmForm,
        node: vmNode,
        profile_id: vmForm.profile_id ? Number(vmForm.profile_id) : null,
        cloud_template_id: vmForm.cloud_template_id ? Number(vmForm.cloud_template_id) : null,
        organization_id: selectedOrg,
      }),
    }).then(async r => {
      if (!r.ok) { const e = await r.json(); throw new Error(e.detail ?? 'Erreur') }
      return r.json()
    }).then(data => {
      toast.success(`VM "${data.hostname}" créée (VMID ${data.vm_id}) - en attente de boot PXE`)
      setShowVmForm(false)
      setVmForm({ hostname: '', client: '', os: 'ubuntu', profile_id: '', ou: '', storage: '', bridge: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, iso: '', boot_mode: 'pxe', cloud_template_id: '' })
      fetchAll(auth.token, selectedOrg)
    }).catch(err => toast.error(err.message))
      .finally(() => setVmCreating(false))
  }

  const handleSync = (vendor: string, delay: number) => {
    setSyncing(vendor)
    fetch(`${API_URL}/drivers/sync/${vendor}`, { method: 'POST', headers: authHeader(auth.token) })
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.status }))
          toast.error(`Erreur sync ${vendor} : ${err.detail}`)
          setSyncing(null)
          return
        }
        setTimeout(() => { fetchDrivers(auth.token); setSyncing(null) }, delay)
      })
      .catch((err) => { toast.error(`Erreur réseau : ${err.message}`); setSyncing(null) })
  }

  const toggleVendor = (vendor: string) =>
    setExpandedVendors(prev => { const s = new Set(prev); s.has(vendor) ? s.delete(vendor) : s.add(vendor); return s })

  const handleDownloadPack = (id: number) => {
    setDownloadingPack(id)
    fetch(`${API_URL}/drivers/${id}/download`, { method: 'POST', headers: authHeader(auth.token) })
      .then(() => {})
      .catch(() => {})
      .finally(() => setDownloadingPack(null))
  }

  const handlePasswordChange = (e: React.FormEvent<HTMLFormElement>) => {
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
            <div className="flex items-center gap-2.5">
              <IcoOsiris cls="w-5 h-5 text-blue-500" />
              <span className="text-lg font-black tracking-[0.22em] text-white uppercase select-none">Osiris</span>
            </div>
            <div className="hidden sm:flex items-center gap-2 text-[11px] font-mono text-slate-600 border-l border-slate-800 pl-5">
              <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${error ? 'bg-red-500' : 'bg-emerald-500 animate-pulse'}`} />
              {error ? 'API hors ligne' : loading ? 'Connexion…' : 'Connecté'}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono text-slate-700 hidden sm:block">{auth.email}</span>
            <button onClick={() => { setShowSettingsModal(true); fetchTotpStatus(auth.token); fetchApiKeys(auth.token); setPwCurrent(''); setPwNew(''); setPwConfirm(''); setPwError(null); setPwSuccess(false); setSettingsTab('password'); setCreatedKey(null) }} className="osiris-action-btn" title="Parametres du compte"><IcoGear /></button>
            <button onClick={() => setAuth(null)} className="osiris-btn-ghost text-xs">Deconnexion</button>
          </div>
        </div>
        {/* ── Onglets ──────────────────────────────────────────────────── */}
        <div className="max-w-7xl mx-auto px-6 flex items-center gap-0 border-t border-slate-800/40">
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
              className={`px-5 py-2.5 text-xs font-semibold tracking-wide border-b-2 transition-colors cursor-pointer ${
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
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

            {/* Organisations */}
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
                        onBlur={e => { if (e.target.value !== org.webhook_url) handlePatchOrg(org.id, e.target.value) }}
                        className="osiris-input text-[10px] font-mono flex-1"
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
                      <button onClick={() => handleDeleteProfile(p.id)} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
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
                    {newProfile.machine_type === 'server' && (
                      <div className="col-span-2 sm:col-span-3 space-y-1">
                        <p className="text-[9px] uppercase tracking-widest text-slate-600">Cles SSH autorisees (une par ligne)</p>
                        <textarea rows={3} placeholder="ssh-ed25519 AAAA... user@host" value={newProfile.ssh_authorized_keys ?? ''} onChange={e => setNewProfile({ ...newProfile, ssh_authorized_keys: e.target.value })} className="osiris-input text-[10px] font-mono w-full resize-y" />
                      </div>
                    )}
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
                <input placeholder="Suffixe TeamViewer (optionnel)" title="Mot de passe TV = NOMPC_MAJUSCULES + ce suffixe" value={newProfile.tv_suffix ?? ''} onChange={e => setNewProfile({ ...newProfile, tv_suffix: e.target.value })} className="osiris-input text-xs font-mono col-span-2 sm:col-span-1" />
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
                  const eligible = apps.filter(a => os === 'windows' ? a.winget_id : a.apt_package)

                  if (eligible.length === 0) return null
                  const selected = new Set((newProfile.app_ids ?? '').split(',').filter(Boolean))
                  const toggle = (id: number) => {
                    const s = new Set(selected)
                    s.has(String(id)) ? s.delete(String(id)) : s.add(String(id))
                    setNewProfile({ ...newProfile, app_ids: Array.from(s).join(',') })
                  }
                  return (
                    <div className="col-span-2 sm:col-span-3 pt-1">
                      <p className="text-[10px] uppercase tracking-widest text-slate-600 mb-1.5">Applications à installer</p>
                      <div className="flex flex-wrap gap-1.5">
                        {eligible.map(a => {
                          const on = selected.has(String(a.id))
                          return (
                            <button key={a.id} type="button" onClick={() => toggle(a.id)}
                              className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] border transition-colors cursor-pointer ${on ? 'bg-blue-600/20 border-blue-500 text-blue-300' : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-500'}`}>
                              <span>{a.icon}</span><span>{a.name}</span>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )
                })()}
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
                <div className="flex gap-2">
                  <input required placeholder="URL ISO  (https://...)" value={newImage.iso_url} onChange={e => setNewImage({ ...newImage, iso_url: e.target.value })} className="osiris-input text-xs font-mono flex-1 min-w-0" />
                  <button type="submit" className="osiris-btn text-xs flex-shrink-0">↓ Télécharger</button>
                </div>
              </form>
            </div>

          </div>
        )}

        {/* ── Onglet Tableau de bord ───────────────────────────────────────── */}
        {activeTab === 'dashboard' && (
          <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Tableau de bord</h2>
              <button onClick={() => fetchDashboard(auth.token)} className="osiris-btn text-xs">
                {dashboardLoading ? 'Chargement...' : <><IcoRefresh cls="w-3 h-3 inline" /> Rafraichir</>}
              </button>
            </div>
            {dashboardLoading ? (
              <p className="text-slate-700 font-mono text-xs">Chargement...</p>
            ) : !dashboard || dashboard.total_machines === 0 ? (
              <p className="text-slate-700 font-mono text-xs">Aucune machine enregistree pour l'instant.</p>
            ) : (
              <>
                {/* Compteurs globaux */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {(['deployed', 'pending', 'deploying', 'failed'] as const).map(s => {
                    const colors: Record<string, string> = { deployed: 'text-green-400', pending: 'text-blue-400', deploying: 'text-yellow-400', failed: 'text-red-400' }
                    const labels: Record<string, string> = { deployed: 'Deployes', pending: 'En attente', deploying: 'En cours', failed: 'Echoues' }
                    return (
                      <div key={s} className="bg-slate-900 border border-slate-800/60 rounded p-4 text-center">
                        <p className={`text-3xl font-bold ${colors[s]}`}>{dashboard.status_counts[s] ?? 0}</p>
                        <p className="text-[10px] text-slate-500 mt-1 uppercase tracking-widest">{labels[s]}</p>
                      </div>
                    )
                  })}
                </div>

                {/* Alertes */}
                {dashboard.alerts.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-[9px] uppercase tracking-widest text-slate-600">Alertes</p>
                    {dashboard.alerts.map((a: any, i: number) => (
                      <div key={i} className={`text-xs p-2 rounded border font-mono ${a.type === 'stuck_deploying' ? 'border-yellow-800/50 bg-yellow-950/30 text-yellow-400' : 'border-red-800/50 bg-red-950/30 text-red-400'}`}>
                        {a.type === 'stuck_deploying' ? `En cours depuis plus de 30 min` : `Echec recent`} - <strong>{a.hostname}</strong> ({a.mac})
                      </div>
                    ))}
                  </div>
                )}

                {/* Stats par org */}
                {dashboard.org_stats.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-[9px] uppercase tracking-widest text-slate-600">Par organisation</p>
                    {dashboard.org_stats.sort((a: any, b: any) => b.total - a.total).map((o: any) => (
                      <div key={o.org_id} className="bg-slate-900 border border-slate-800/60 rounded p-3 flex items-center gap-4">
                        <span className="text-slate-300 text-sm font-medium w-40 truncate">{o.org_name}</span>
                        <div className="flex-1 flex gap-1 h-2">
                          {(['deployed', 'pending', 'deploying', 'failed'] as const).map(s => {
                            const pct = o.total ? Math.round((o[s] ?? 0) / o.total * 100) : 0
                            const colors = { deployed: 'bg-green-500', pending: 'bg-blue-500', deploying: 'bg-yellow-500', failed: 'bg-red-500' }
                            return pct > 0 ? <div key={s} className={`${colors[s]} rounded`} style={{ width: `${pct}%` }} title={`${s}: ${o[s]}`} /> : null
                          })}
                        </div>
                        <span className="text-slate-600 text-[10px] font-mono w-16 text-right">{o.total} machine{o.total > 1 ? 's' : ''}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Derniers deploiements */}
                {dashboard.recent_deployments.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-[9px] uppercase tracking-widest text-slate-600">Deploiements recents</p>
                    <div className="border border-slate-800/60 rounded overflow-hidden">
                      {dashboard.recent_deployments.map((e: any, i: number) => (
                        <div key={i} className={`flex items-center gap-3 px-3 py-2 text-xs font-mono ${i % 2 === 0 ? 'bg-slate-900/40' : ''}`}>
                          <span className={`w-16 text-center rounded px-1 py-0.5 text-[9px] font-bold ${e.status === 'deployed' ? 'bg-green-900/60 text-green-400' : 'bg-red-900/60 text-red-400'}`}>{e.status}</span>
                          <span className="text-slate-300 w-40 truncate">{e.hostname}</span>
                          <span className="text-slate-600 flex-1 truncate">{e.profile_name}</span>
                          <span className="text-slate-700">{new Date(e.timestamp).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* ── Onglet Infrastructure ────────────────────────────────────────── */}
        {activeTab === 'infrastructure' && auth.role === 'admin' && (
          <div className="osiris-table-wrap p-5 space-y-6 max-w-4xl">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Hyperviseurs</h2>

            {/* Liste */}
            <div className="space-y-3">
              {hypervisors.length === 0 && <p className="text-slate-700 text-xs font-mono">Aucun hyperviseur enregistré</p>}
              {hypervisors.map(h => {
                const result = hvTestResult[h.id]
                return (
                  <div key={h.id} className="border border-slate-800/60 rounded p-4 space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-white font-medium">{h.name}</span>
                          <span className="inline-block border border-blue-800/60 text-blue-400 rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider">{h.type}</span>
                          {!h.tls_verify && <span className="inline-block border border-amber-800/60 text-amber-500 rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider">TLS non verifie</span>}
                        </div>
                        <p className="text-[11px] font-mono text-slate-500 mt-0.5 truncate">{h.url}</p>
                        <p className="text-[10px] font-mono text-slate-600">{h.token_id || '—'}</p>
                      </div>
                      <div className="flex gap-1.5 flex-shrink-0">
                        <button onClick={() => handleTestHv(h.id)} disabled={hvTesting[h.id]}
                          className="osiris-btn text-xs px-3 disabled:opacity-50">
                          {hvTesting[h.id] ? '...' : 'Tester'}
                        </button>
                        <button onClick={() => handleDeleteHv(h.id)} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                      </div>
                    </div>

                    {/* Résultat du test */}
                    {result && (
                      <div className={`rounded p-3 text-xs font-mono space-y-2 ${result.ok ? 'bg-green-950/40 border border-green-800/40' : 'bg-red-950/40 border border-red-800/40'}`}>
                        {result.ok ? (
                          <>
                            <p className="text-green-400">Connexion OK - Proxmox {result.proxmox_version}</p>
                            {result.nodes && result.nodes.length > 0 && (
                              <table className="w-full text-[10px]">
                                <thead>
                                  <tr className="text-slate-500">
                                    <th className="text-left pr-4">Noeud</th>
                                    <th className="text-left pr-4">Statut</th>
                                    <th className="text-right pr-4">CPU</th>
                                    <th className="text-right pr-4">vCPU</th>
                                    <th className="text-right">RAM</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {result.nodes.map(n => (
                                    <tr key={n.node} className="text-slate-300">
                                      <td className="pr-4 font-semibold">{n.node}</td>
                                      <td className={`pr-4 ${n.status === 'online' ? 'text-green-400' : 'text-red-400'}`}>{n.status}</td>
                                      <td className="text-right pr-4">{n.cpu}%</td>
                                      <td className="text-right pr-4">{n.maxcpu}</td>
                                      <td className="text-right">{n.mem_gb} / {n.maxmem_gb} Go</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </>
                        ) : (
                          <p className="text-red-400">{result.error}</p>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Formulaire d'ajout */}
            {/* Bouton + formulaire création VM */}
            {hypervisors.length > 0 && (
              <div className="pt-3 border-t border-slate-800/50">
                {!showVmForm ? (
                  <button onClick={() => setShowVmForm(true)} className="osiris-btn text-xs px-4">+ Créer une VM</button>
                ) : (
                  <form onSubmit={handleCreateVm} className="space-y-3">
                    <div className="flex items-center justify-between">
                      <p className="text-[9px] uppercase tracking-widest text-slate-600">Nouvelle VM</p>
                      <button type="button" onClick={() => setShowVmForm(false)} className="text-slate-600 hover:text-slate-300 text-xs">Annuler</button>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <input required placeholder="Hostname" value={vmForm.hostname} onChange={e => setVmForm(f => ({...f, hostname: e.target.value}))} className="osiris-input text-xs font-mono" />
                      <input required placeholder="Client / label" value={vmForm.client} onChange={e => setVmForm(f => ({...f, client: e.target.value}))} className="osiris-input text-xs" />
                      <select value={vmForm.os} onChange={e => setVmForm(f => ({...f, os: e.target.value}))} className="osiris-input text-xs">
                        <option value="ubuntu">Ubuntu</option>
                        <option value="debian">Debian</option>
                      </select>
                      <select value={vmForm.profile_id} onChange={e => setVmForm(f => ({...f, profile_id: e.target.value}))} className="osiris-input text-xs">
                        <option value="">Profil par défaut</option>
                        {profiles.filter(p => p.os === vmForm.os).map(p => (
                          <option key={p.id} value={p.id}>{p.name}{p.machine_type === 'server' ? ' [serveur]' : ''}</option>
                        ))}
                      </select>
                      <input placeholder="OU (optionnel)" value={vmForm.ou} onChange={e => setVmForm(f => ({...f, ou: e.target.value}))} className="osiris-input text-xs font-mono col-span-2" />
                    </div>

                    {/* Sélection hyperviseur + noeud */}
                    <div className="grid grid-cols-2 gap-2">
                      <select required value={vmHvId} onChange={e => handleVmHvChange(Number(e.target.value))} className="osiris-input text-xs">
                        <option value="">Hyperviseur...</option>
                        {hypervisors.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
                      </select>
                      <select required value={vmNode} onChange={e => handleVmNodeChange(e.target.value)} className="osiris-input text-xs" disabled={!vmHvId || vmNodes.length === 0}>
                        <option value="">Noeud...</option>
                        {vmNodes.map(n => (
                          <option key={n.node} value={n.node}>{n.node} — {n.cpu}% CPU · {n.mem_gb}/{n.maxmem_gb} Go RAM</option>
                        ))}
                      </select>
                    </div>

                    {/* Mode de boot */}
                    <div className="flex gap-2">
                      {(['pxe', 'cloudinit'] as const).map(mode => (
                        <button key={mode} type="button"
                          onClick={() => setVmForm(f => ({...f, boot_mode: mode, cloud_template_id: '', iso: ''}))}
                          className={`flex-1 py-1.5 rounded text-xs border transition-colors ${vmForm.boot_mode === mode ? 'bg-blue-600/20 border-blue-500 text-blue-300' : 'bg-slate-900 border-slate-700 text-slate-500 hover:border-slate-500'}`}>
                          {mode === 'pxe' ? 'PXE (ISO / installation)' : 'Cloud-init (clone de template)'}
                        </button>
                      ))}
                    </div>

                    {/* Ressources */}
                    <div className="grid grid-cols-2 gap-2">
                      <select required value={vmForm.storage} onChange={e => setVmForm(f => ({...f, storage: e.target.value}))} className="osiris-input text-xs" disabled={vmStorages.length === 0}>
                        <option value="">Stockage...</option>
                        {vmStorages.map(s => <option key={s.storage} value={s.storage}>{s.storage} ({s.type}) — {s.avail_gb} Go libres</option>)}
                      </select>
                      <select required value={vmForm.bridge} onChange={e => setVmForm(f => ({...f, bridge: e.target.value}))} className="osiris-input text-xs" disabled={vmNetworks.length === 0}>
                        <option value="">Bridge réseau...</option>
                        {vmNetworks.map(n => <option key={n.iface} value={n.iface}>{n.iface}{n.address ? ` (${n.address})` : ''}</option>)}
                      </select>
                      <div className="flex items-center gap-1">
                        <label className="text-[10px] text-slate-500 shrink-0">vCPU</label>
                        <input type="number" min={1} max={64} value={vmForm.vcpus} onChange={e => setVmForm(f => ({...f, vcpus: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                      </div>
                      <div className="flex items-center gap-1">
                        <label className="text-[10px] text-slate-500 shrink-0">RAM Mo</label>
                        <input type="number" min={512} step={512} value={vmForm.ram_mb} onChange={e => setVmForm(f => ({...f, ram_mb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                      </div>
                      <div className="flex items-center gap-1 col-span-2">
                        <label className="text-[10px] text-slate-500 shrink-0">Disque Go</label>
                        <input type="number" min={8} value={vmForm.disk_gb} onChange={e => setVmForm(f => ({...f, disk_gb: Number(e.target.value)}))} className="osiris-input text-xs w-full" />
                      </div>

                      {vmForm.boot_mode === 'pxe' ? (
                        <input placeholder="ISO Proxmox (ex: local:iso/ubuntu-24.04.iso) — optionnel" value={vmForm.iso} onChange={e => setVmForm(f => ({...f, iso: e.target.value}))} className="osiris-input text-xs font-mono col-span-2" />
                      ) : (
                        <select required value={vmForm.cloud_template_id} onChange={e => setVmForm(f => ({...f, cloud_template_id: e.target.value}))} className="osiris-input text-xs col-span-2" disabled={vmTemplates.length === 0}>
                          <option value="">{vmTemplates.length === 0 ? (vmNode ? 'Aucun template trouvé sur ce noeud' : 'Choisir un noeud d\'abord') : 'Template Proxmox...'}</option>
                          {vmTemplates.map(t => <option key={t.vmid} value={t.vmid}>{t.name} (VMID {t.vmid}) — {t.cores} vCPU · {t.maxmem_gb} Go</option>)}
                        </select>
                      )}
                    </div>

                    <div className="text-[10px] text-slate-600 bg-slate-900/60 rounded p-2 font-mono">
                      {vmForm.boot_mode === 'pxe'
                        ? 'Boot order : PXE → disque → ISO. La VM s\'enregistrera dans OSIRIS au premier boot réseau.'
                        : 'Clone complet du template + cloud-init injecté via snippets Proxmox. Démarrage ~30s, pas de PXE requis.'}
                    </div>
                    <button type="submit" disabled={vmCreating || !vmNode || !vmForm.storage || !vmForm.bridge} className="osiris-btn text-xs px-4 w-full disabled:opacity-50">
                      {vmCreating ? 'Création en cours...' : 'Créer et démarrer la VM'}
                    </button>
                  </form>
                )}
              </div>
            )}

            <form onSubmit={handleCreateHv} className="space-y-3 pt-3 border-t border-slate-800/50">
              <p className="text-[9px] uppercase tracking-widest text-slate-600">Ajouter un hyperviseur</p>
              <div className="grid grid-cols-2 gap-2">
                <input required placeholder="Nom  (ex : Proxmox Lab)" value={newHv.name} onChange={e => setNewHv({ ...newHv, name: e.target.value })} className="osiris-input text-xs" />
                <input required placeholder="URL  (https://proxmox.local:8006)" value={newHv.url} onChange={e => setNewHv({ ...newHv, url: e.target.value })} className="osiris-input text-xs font-mono" />
                <input placeholder="Token ID  (osiris@pve!osiris-token)" value={newHv.token_id} onChange={e => setNewHv({ ...newHv, token_id: e.target.value })} className="osiris-input text-xs font-mono" />
                <input type="password" placeholder="Token secret" value={newHv.token_secret} onChange={e => setNewHv({ ...newHv, token_secret: e.target.value })} className="osiris-input text-xs font-mono" />
                <input placeholder="Stockage snippets cloud-init (ex: local) — optionnel" value={newHv.snippets_storage} onChange={e => setNewHv({ ...newHv, snippets_storage: e.target.value })} className="osiris-input text-xs font-mono col-span-2" title="Nom du stockage Proxmox avec content-type snippets, requis pour cloud-init complet" />
              </div>
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                  <input type="checkbox" checked={newHv.tls_verify} onChange={e => setNewHv({ ...newHv, tls_verify: e.target.checked })} className="accent-blue-500" />
                  Verifier le certificat TLS (decocher si cert self-signe)
                </label>
                <button type="submit" className="osiris-btn text-xs px-4">+ Ajouter</button>
              </div>
            </form>
          </div>
        )}

        {/* ── Onglet Journal ───────────────────────────────────────────────── */}
        {activeTab === 'journal' && auth.role === 'admin' && (
          <div className="osiris-table-wrap overflow-x-auto">
            <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-slate-800/80">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500 mr-auto">Journal d'activité</h2>
              <select value={auditFilterAction} onChange={e => setAuditFilterAction(e.target.value)}
                className="osiris-input text-[10px] py-1 w-40">
                <option value="">Toutes les actions</option>
                {Object.entries(ACTION_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
              <input value={auditFilterEmail} onChange={e => setAuditFilterEmail(e.target.value)}
                placeholder="Utilisateur…" className="osiris-input text-[10px] py-1 w-36" />
              <input value={auditFilterMac} onChange={e => setAuditFilterMac(e.target.value)}
                placeholder="MAC…" className="osiris-input text-[10px] py-1 w-32 font-mono" />
              <button onClick={() => fetchAuditLogs(auth.token, auditFilterAction, auditFilterEmail, auditFilterMac)}
                className="osiris-btn text-[10px]">
                {auditLoading ? '…' : <><IcoSearch cls="w-3 h-3 inline" /> Filtrer</>}
              </button>
              <button onClick={() => { setAuditFilterAction(''); setAuditFilterEmail(''); setAuditFilterMac(''); fetchAuditLogs(auth.token, '', '', '') }}
                className="osiris-btn-ghost text-[10px]">
                <IcoRefresh cls="w-3 h-3 inline" /> Reset
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

        {/* ── Domaines AD (dans onglet Admin, section separee) ─────────────── */}
        {activeTab === 'admin' && auth.role === 'admin' && (
          <div className="max-w-7xl mx-auto px-6 py-4 border-t border-slate-800/40 space-y-3">
            <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Domaines AD par organisation</h2>
            <p className="text-[10px] text-slate-600">Configurez les credentials AD au niveau de l'organisation. Les profils peuvent utiliser ces configs au lieu de saisir le domaine manuellement.</p>
            {domainConfigs.length > 0 && (
              <div className="space-y-1">
                {domainConfigs.map((dc: any) => (
                  <div key={dc.id} className="flex items-center justify-between py-1.5 px-3 border border-slate-800/60 rounded text-xs">
                    <div>
                      <span className="text-white font-medium">{dc.name}</span>
                      <span className="text-slate-500 ml-3 font-mono">{dc.domain}</span>
                      {dc.join_user && <span className="text-slate-600 ml-2">({dc.join_user})</span>}
                      {dc.default_ou && <span className="text-slate-700 ml-2 font-mono text-[9px]">{dc.default_ou}</span>}
                    </div>
                    <button onClick={() => fetch(`${API_URL}/domain-configs/${dc.id}`, { method: 'DELETE', headers: authHeader(auth.token) }).then(r => { if (r.ok) fetchDomainConfigs(auth.token) })} className="osiris-action-btn osiris-action-btn--danger"><IcoX /></button>
                  </div>
                ))}
              </div>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-slate-800/40">
              <select value={newDomainConfig.organization_id} onChange={e => setNewDomainConfig({...newDomainConfig, organization_id: parseInt(e.target.value)})} className="osiris-input text-xs">
                <option value={0}>-- Organisation --</option>
                {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
              <input placeholder="Nom (ex: Siege principal)" value={newDomainConfig.name} onChange={e => setNewDomainConfig({...newDomainConfig, name: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="Domaine (ex: corp.local)" value={newDomainConfig.domain} onChange={e => setNewDomainConfig({...newDomainConfig, domain: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="Compte jonction AD" value={newDomainConfig.join_user} onChange={e => setNewDomainConfig({...newDomainConfig, join_user: e.target.value})} className="osiris-input text-xs font-mono" />
              <input type="password" placeholder="Mot de passe jonction" value={newDomainConfig.join_password} onChange={e => setNewDomainConfig({...newDomainConfig, join_password: e.target.value})} className="osiris-input text-xs font-mono" />
              <input placeholder="OU par defaut (optionnel)" value={newDomainConfig.default_ou} onChange={e => setNewDomainConfig({...newDomainConfig, default_ou: e.target.value})} className="osiris-input text-xs font-mono" />
              <button onClick={() => {
                if (!newDomainConfig.organization_id || !newDomainConfig.name || !newDomainConfig.domain) { toast.error('Organisation, nom et domaine requis'); return }
                fetch(`${API_URL}/domain-configs`, { method: 'POST', headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' }, body: JSON.stringify(newDomainConfig) })
                  .then(r => { if (r.ok) { fetchDomainConfigs(auth.token); setNewDomainConfig({ organization_id: 0, name: '', domain: '', join_user: '', join_password: '', default_ou: '' }); toast.success('Configuration AD ajoutee') } else throw new Error() })
                  .catch(() => toast.error('Erreur'))
              }} className="osiris-btn text-xs col-span-2 sm:col-span-1">Ajouter</button>
            </div>
          </div>
        )}

        {/* ── Onglet Capture ───────────────────────────────────────────────── */}
        {activeTab === 'capture' && auth.role === 'admin' && (
          <div className="osiris-table-wrap overflow-x-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/80">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Capture d'une Golden Image</h2>
              <button onClick={() => fetchCaptures(auth.token)} className="osiris-btn-ghost text-[10px]">
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
        )}

        {/* ── Onglet Drivers ───────────────────────────────────────────────── */}
        {activeTab === 'drivers' && auth.role === 'admin' && (
          <div className="osiris-table-wrap overflow-x-auto">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800/80">
              <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500">Catalogue Drivers</h2>
              <div className="flex gap-2 flex-wrap">
                <button onClick={() => fetchDrivers(auth.token)} className="osiris-btn-ghost text-[10px]">
                  {driversLoading ? 'Chargement…' : <><IcoRefresh cls="w-3 h-3 inline" /> Rafraîchir</>}
                </button>
                <button onClick={() => handleSync('dell', 15000)} disabled={syncing !== null} className="osiris-btn text-xs">
                  {syncing === 'dell' ? 'Dell en cours…' : <><IcoRefresh cls="w-3 h-3 inline" /> Dell</>}
                </button>
                <button onClick={() => handleSync('hp', 30000)} disabled={syncing !== null} className="osiris-btn text-xs">
                  {syncing === 'hp' ? 'HP en cours…' : <><IcoRefresh cls="w-3 h-3 inline" /> HP</>}
                </button>
                <button onClick={() => handleSync('lenovo', 20000)} disabled={syncing !== null} className="osiris-btn text-xs">
                  {syncing === 'lenovo' ? 'Lenovo en cours…' : <><IcoRefresh cls="w-3 h-3 inline" /> Lenovo</>}
                </button>
              </div>
            </div>
            {driversLoading ? (
              <div className="flex items-center gap-2.5 text-slate-600 font-mono text-xs p-5">
                <span className="inline-block w-1.5 h-1.5 bg-blue-600 rounded-full animate-ping" />
                Chargement…
              </div>
            ) : drivers.length === 0 ? (
              <p className="text-slate-700 font-mono text-xs p-5">Aucun driver : lancez une synchronisation pour remplir le catalogue.</p>
            ) : (() => {
              const q = driverSearch.toLowerCase()
              const isSearching = q.length > 0

              // Groupement par vendor
              const groups: Record<string, DriverPack[]> = {}
              for (const d of drivers) {
                if (!groups[d.vendor]) groups[d.vendor] = []
                if (!isSearching || d.model.toLowerCase().includes(q)) groups[d.vendor].push(d)
              }
              const vendorOrder = ['dell', 'hp', 'lenovo']
              const vendorLabel: Record<string, string> = { dell: 'Dell', hp: 'HP', lenovo: 'Lenovo' }

              const DriverRow = ({ d }: { d: DriverPack }) => (
                <tr className="osiris-row">
                  <td className="px-4 py-2 font-mono text-xs text-white">{d.model}</td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-500">{d.os_code}</td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-600 whitespace-nowrap">{d.size_mb ? `${d.size_mb} MB` : '—'}</td>
                  <td className="px-4 py-2">
                    <span className={`osiris-status-badge ${
                      d.status === 'ready'       ? 'osiris-status--deployed' :
                      d.status === 'downloading' ? 'osiris-status--deploying' :
                      d.status === 'failed'      ? 'osiris-status--failed' :
                                                   'osiris-status--pending'
                    }`}>{d.status}</span>
                  </td>
                  <td className="px-4 py-2">
                    {d.status !== 'ready' && d.status !== 'downloading' && (
                      <button onClick={() => handleDownloadPack(d.id)} disabled={downloadingPack === d.id} className="osiris-action-btn text-[10px]">
                        {downloadingPack === d.id ? '…' : <IcoDownload />}
                      </button>
                    )}
                    {d.status === 'ready' && <span className="text-emerald-600 font-mono text-[10px] flex items-center gap-1"><IcoCheck cls="w-3 h-3" /> Prêt</span>}
                    {d.status === 'downloading' && <span className="text-blue-500 font-mono text-[10px] animate-pulse">En cours…</span>}
                  </td>
                </tr>
              )

              return (
                <>
                  {/* Barre de recherche */}
                  <div className="px-5 py-3 border-b border-slate-800/80 flex items-center gap-3">
                    <span className="text-slate-600 flex-shrink-0"><IcoSearch /></span>
                    <input type="text" placeholder="Rechercher un modèle…"
                      value={driverSearch} onChange={e => setDriverSearch(e.target.value)}
                      className="osiris-input text-xs flex-1 max-w-sm" />
                    {isSearching && (
                      <span className="text-[10px] font-mono text-slate-600">
                        {Object.values(groups).flat().length} résultat{Object.values(groups).flat().length !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>

                  {isSearching ? (
                    /* ── Mode recherche : tableau plat ── */
                    <table className="w-full text-sm">
                      <thead><tr className="border-b border-slate-800/80">
                        {['Modèle', 'OS', 'Taille', 'Statut', 'Action'].map(h => (
                          <th key={h} className="text-left px-4 py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600 whitespace-nowrap">{h}</th>
                        ))}
                      </tr></thead>
                      <tbody>
                        {Object.values(groups).flat().slice(0, 100).map(d => <DriverRow key={d.id} d={d} />)}
                      </tbody>
                    </table>
                  ) : (
                    /* ── Mode accordéon : dossiers par vendor ── */
                    <div className="divide-y divide-slate-800/60">
                      {vendorOrder.filter(v => (groups[v]?.length ?? 0) > 0 || drivers.some(d => d.vendor === v)).map(vendor => {
                        const items = groups[vendor] ?? []
                        const total = drivers.filter(d => d.vendor === vendor).length
                        const open  = expandedVendors.has(vendor)
                        const ready = items.filter(d => d.status === 'ready').length
                        return (
                          <div key={vendor}>
                            {/* En-tête du dossier */}
                            <button onClick={() => toggleVendor(vendor)}
                              className="w-full flex items-center gap-3 px-5 py-3.5 hover:bg-slate-800/30 transition-colors text-left">
                              <span className="text-slate-500 w-3 flex-shrink-0">{open ? <IcoChevDown /> : <IcoChevRight />}</span>
                              <span className="font-bold text-sm text-white tracking-wide">{vendorLabel[vendor]}</span>
                              <span className="text-[10px] font-mono text-slate-600">{total} modèle{total !== 1 ? 's' : ''}</span>
                              {ready > 0 && <span className="text-[10px] font-mono text-emerald-600">{ready} prêt{ready !== 1 ? 's' : ''}</span>}
                              <span className="ml-auto text-[10px] text-slate-700">{open ? 'Fermer' : 'Ouvrir'}</span>
                            </button>
                            {/* Contenu du dossier */}
                            {open && (
                              <div className="border-t border-slate-800/60 bg-slate-950/40">
                                <table className="w-full text-sm">
                                  <thead><tr className="border-b border-slate-800/60">
                                    {['Modèle', 'OS', 'Taille', 'Statut', 'Action'].map(h => (
                                      <th key={h} className="text-left px-4 py-2.5 text-[10px] font-semibold uppercase tracking-widest text-slate-700 whitespace-nowrap">{h}</th>
                                    ))}
                                  </tr></thead>
                                  <tbody>
                                    {items.slice(0, 200).map(d => <DriverRow key={d.id} d={d} />)}
                                    {items.length > 200 && (
                                      <tr><td colSpan={5} className="px-4 py-3 text-center text-[10px] font-mono text-slate-700">
                                        … {items.length - 200} modèles masqués — utilisez la recherche pour les trouver
                                      </td></tr>
                                    )}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </>
              )
            })()}
          </div>
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
          <div className="flex items-center gap-2.5 text-slate-600 font-mono text-xs py-6">
            <span className="inline-block w-1.5 h-1.5 bg-blue-600 rounded-full animate-ping" />
            Chargement…
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
          <div className="osiris-table-wrap overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800/80">
                  <th className="px-4 py-3 w-8">
                    <input type="checkbox"
                      checked={selectedMacs.size === filteredMachines.length && filteredMachines.length > 0}
                      ref={el => { if (el) el.indeterminate = selectedMacs.size > 0 && selectedMacs.size < filteredMachines.length }}
                      onChange={toggleSelectAll}
                      className="accent-blue-500 cursor-pointer" />
                  </th>
                  {["Nom d'hôte", "Adresse MAC", "Client / Org", "OS", "Statut", "OU / Actions"].map(h => (
                    <th key={h} className="text-left px-4 py-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredMachines.length === 0 ? (
                  <tr><td colSpan={7} className="px-4 py-16 text-center text-slate-700 font-mono text-xs">
                    {machines.length === 0 ? 'Aucune machine enregistrée' : 'Aucun résultat pour cette recherche'}
                  </td></tr>
                ) : filteredMachines.map((machine) => (
                  <React.Fragment key={machine.id}>
                  <tr className={`osiris-row transition-colors ${selectedMacs.has(machine.mac) ? 'bg-blue-950/20' : ''}`}>
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
                          onClick={() => {
                            const isOpen = expandedLogs.has(machine.mac)
                            setExpandedLogs(prev => { const s = new Set(prev); isOpen ? s.delete(machine.mac) : s.add(machine.mac); return s })
                            if (!expandedLogs.has(machine.mac)) fetchHistory(machine.mac)
                          }}>
                          {(() => { try { const t = JSON.parse(machine.smoke_results ?? '[]'); const n = t.filter((x: any) => !x.ok).length; return `${n} alerte${n > 1 ? 's' : ''}` } catch { return 'Alertes' } })()}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-xs text-slate-600 truncate max-w-[140px]" title={machine.ou}>{machine.ou || '—'}</span>
                        <div className="flex items-center gap-1 ml-auto flex-shrink-0">
                          {(deployLogs[machine.mac]?.length ?? 0) > 0 && (
                            <button
                              onClick={() => {
                                const isOpen = expandedLogs.has(machine.mac)
                                setExpandedLogs(prev => {
                                  const s = new Set(prev)
                                  isOpen ? s.delete(machine.mac) : s.add(machine.mac)
                                  return s
                                })
                                if (!isOpen) fetchHistory(machine.mac)
                              }}
                              className="osiris-action-btn"
                              title="Logs / Historique"
                            >{expandedLogs.has(machine.mac) ? <IcoChevUp /> : <IcoChevDown />}</button>
                          )}
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
                          {machine.proxmox_vm_id ? (() => {
                            const ps = vmPowerState[machine.mac]
                            const loading = vmPowerLoading[machine.mac]
                            const hv = hypervisors.find(h => h.id === machine.hypervisor_id)
                            const consoleUrl = hv ? `${hv.url}/?console=kvm&novnc=1&vmid=${machine.proxmox_vm_id}&node=${machine.proxmox_node}` : ''
                            return (
                              <>
                                <button onClick={() => fetchVmStatus(machine.mac)} className="osiris-action-btn" title={ps ? `VM ${ps.status} · CPU ${ps.cpu}% · RAM ${ps.mem_mb} Mo` : 'Voir statut VM'}>
                                  <span className={`inline-block w-2 h-2 rounded-full ${!ps ? 'bg-slate-600' : ps.status === 'running' ? 'bg-green-500' : 'bg-red-500'}`} />
                                </button>
                                {ps?.status === 'running' ? (<>
                                  <button onClick={() => handleVmPower(machine.mac, 'shutdown')} disabled={loading} title="Arrêt propre" className="osiris-action-btn text-[10px]">⏻</button>
                                  <button onClick={() => handleVmPower(machine.mac, 'reboot')} disabled={loading} title="Redémarrer" className="osiris-action-btn text-[10px]">↺</button>
                                </>) : ps?.status === 'stopped' ? (
                                  <button onClick={() => handleVmPower(machine.mac, 'start')} disabled={loading} title="Démarrer la VM" className="osiris-action-btn text-[10px]">▶</button>
                                ) : null}
                                {consoleUrl && (
                                  <a href={consoleUrl} target="_blank" rel="noreferrer" className="osiris-action-btn" title="Console noVNC (ouvre Proxmox)">
                                    <IcoTerminal />
                                  </a>
                                )}
                                <button onClick={() => {
                                  const next = snapshotsMac === machine.mac ? null : machine.mac
                                  setSnapshotsMac(next)
                                  if (next) fetchSnapshots(next)
                                }} className="osiris-action-btn" title="Snapshots">
                                  <IcoCamera />
                                </button>
                              </>
                            )
                          })() : null}
                          {auth.role === 'admin' && (
                            <button onClick={() => { setDeletingMac(machine.mac); setDeleteDestroyVm(false) }} className="osiris-action-btn osiris-action-btn--danger" title="Supprimer"><IcoX /></button>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                  {expandedLogs.has(machine.mac) && (
                    <tr className="bg-[#060912]">
                      <td colSpan={7} className="px-4 pt-3 pb-4 space-y-3">
                        {/* ── Logs live ── */}
                        {(deployLogs[machine.mac]?.length ?? 0) > 0 && (
                          <div>
                            <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1">Logs en direct</p>
                            <pre ref={el => { logEndRefs.current[machine.mac] = el }} className="text-[10px] font-mono text-slate-400 max-h-40 overflow-y-auto leading-relaxed whitespace-pre-wrap">
                              {deployLogs[machine.mac].join('\n')}
                            </pre>
                          </div>
                        )}
                        {/* ── Historique ── */}
                        <div>
                          <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Historique des déploiements</p>
                          {(machineHistory[machine.mac]?.length ?? 0) === 0 ? (
                            <p className="text-[10px] font-mono text-slate-700">Aucun événement enregistré</p>
                          ) : (
                            <div className="space-y-px">
                              {machineHistory[machine.mac].map(ev => {
                                const colors: Record<string, string> = {
                                  deployed: 'text-green-400', deploying: 'text-blue-400',
                                  pending: 'text-slate-400', failed: 'text-red-400',
                                }
                                const d = new Date(ev.timestamp)
                                const fmt = d.toLocaleString('fr-FR', { day:'2-digit', month:'2-digit', year:'2-digit', hour:'2-digit', minute:'2-digit' })
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
                                  const tests: {name: string; ok: boolean; detail?: string}[] = JSON.parse(machine.smoke_results ?? '[]')
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
                        {(machine.hw_model || machine.hw_serial) && (
                          <div>
                            <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Inventaire materiel</p>
                            <div className="flex flex-wrap gap-4 text-[10px] font-mono">
                              {machine.hw_model  && <span className="text-slate-400">{machine.hw_model}</span>}
                              {machine.hw_ram_gb  ? <span className="text-slate-500">{machine.hw_ram_gb} Go RAM</span> : null}
                              {machine.hw_serial && <span className="text-slate-600">S/N : {machine.hw_serial}</span>}
                            </div>
                          </div>
                        )}
                        {/* ── BitLocker (admins uniquement) ── */}
                        {auth?.role === 'admin' && machine.os === 'windows' && (
                          <div>
                            <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">BitLocker</p>
                            {machine.has_bitlocker ? (
                              bitlockerData[machine.mac] ? (
                                <div className="space-y-1.5">
                                  {bitlockerData[machine.mac].pin && (
                                    <div className="flex items-center gap-2">
                                      <span className="text-[9px] text-slate-600 w-24 shrink-0">PIN (6 chiffres)</span>
                                      <span className="font-mono text-[12px] text-amber-400 tracking-[0.2em]">{bitlockerData[machine.mac].pin}</span>
                                      <button onClick={() => { navigator.clipboard.writeText(bitlockerData[machine.mac].pin!); toast.success('PIN copie') }} className="osiris-btn text-[10px] px-2 py-0.5">Copier</button>
                                    </div>
                                  )}
                                  {bitlockerData[machine.mac].key && (
                                    <div className="flex items-center gap-2">
                                      <span className="text-[9px] text-slate-600 w-24 shrink-0">Cle 48 chiffres</span>
                                      <span className="font-mono text-[10px] text-slate-300 tracking-wider">{bitlockerData[machine.mac].key}</span>
                                      <button onClick={() => { navigator.clipboard.writeText(bitlockerData[machine.mac].key!); toast.success('Cle copiee') }} className="osiris-btn text-[10px] px-2 py-0.5">Copier</button>
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <button onClick={() => fetchBitlockerKey(machine.mac)} className="osiris-btn text-[10px] px-2 py-1">Afficher les cles</button>
                              )
                            ) : (
                              <span className="text-[10px] font-mono text-slate-700">Aucune cle enregistree</span>
                            )}
                          </div>
                        )}
                        {/* ── LAPS ── */}
                        {auth.role === 'admin' && machine.os === 'windows' && (
                          <div>
                            <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Mot de passe admin local (LAPS)</p>
                            {machine.has_laps ? (
                              <div className="space-y-1.5">
                                {lapsData[machine.mac] ? (
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono text-sm text-green-400 tracking-wider">{lapsData[machine.mac]}</span>
                                    <button onClick={() => { navigator.clipboard.writeText(lapsData[machine.mac]); toast.success('Mot de passe copie') }} className="osiris-btn text-[10px] px-2 py-0.5">Copier</button>
                                  </div>
                                ) : (
                                  <button onClick={() => fetchLapsPassword(machine.mac)} className="osiris-btn text-[10px] px-2 py-1">Afficher le mot de passe</button>
                                )}
                                {machine.laps_rotated_at && (
                                  <p className="text-[10px] font-mono text-slate-600">
                                    Derniere rotation : {new Date(machine.laps_rotated_at).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })}
                                  </p>
                                )}
                              </div>
                            ) : (
                              <span className="text-[10px] font-mono text-slate-700">Aucun mot de passe LAPS enregistre</span>
                            )}
                          </div>
                        )}
                        {/* ── Utilisateur affecte ── */}
                        <div>
                          <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Utilisateur affecte (optionnel)</p>
                          <div className="flex gap-2">
                            <input
                              placeholder="Nom"
                              defaultValue={machine.user_name ?? ''}
                              onBlur={e => {
                                if (e.target.value !== (machine.user_name ?? ''))
                                  fetch(`${API_URL}/machines/${machine.mac}`, { method: 'PATCH', headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' }, body: JSON.stringify({ user_name: e.target.value }) }).then(r => { if (r.ok) fetchAll(auth.token) })
                              }}
                              className="osiris-input text-xs flex-1"
                            />
                            <input
                              placeholder="Email"
                              defaultValue={machine.user_email ?? ''}
                              onBlur={e => {
                                if (e.target.value !== (machine.user_email ?? ''))
                                  fetch(`${API_URL}/machines/${machine.mac}`, { method: 'PATCH', headers: { ...authHeader(auth.token), 'Content-Type': 'application/json' }, body: JSON.stringify({ user_email: e.target.value }) }).then(r => { if (r.ok) fetchAll(auth.token) })
                              }}
                              className="osiris-input text-xs flex-1"
                            />
                          </div>
                        </div>
                        {/* ── Notes ── */}
                        <div>
                          <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-1.5">Notes</p>
                          <div className="flex gap-2">
                            <textarea
                              rows={2}
                              placeholder="Notes libres sur cette machine..."
                              defaultValue={machine.notes ?? ''}
                              onChange={e => setEditingNotes(prev => ({ ...prev, [machine.mac]: e.target.value }))}
                              className="osiris-input text-[10px] font-mono flex-1 resize-none"
                            />
                            <button
                              onClick={() => saveNotes(machine.mac, editingNotes[machine.mac] ?? machine.notes ?? '')}
                              className="osiris-btn text-[10px] px-3 self-start"
                            >Sauvegarder</button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                  {snapshotsMac === machine.mac && (
                    <tr className="bg-[#060912]">
                      <td colSpan={7} className="px-5 py-4">
                        <div className="space-y-3">
                          <p className="text-[9px] uppercase tracking-widest text-slate-500">Snapshots Proxmox - VMID {machine.proxmox_vm_id}</p>
                          {snapshotsLoading ? (
                            <p className="text-[10px] font-mono text-slate-600">Chargement…</p>
                          ) : snapshots.filter(s => s.name !== 'current').length === 0 ? (
                            <p className="text-[10px] font-mono text-slate-700">Aucun snapshot</p>
                          ) : (
                            <div className="space-y-1">
                              {snapshots.filter(s => s.name !== 'current').map(snap => (
                                <div key={snap.name} className="flex items-center gap-3 text-[10px] font-mono py-1 border-b border-slate-800/40 last:border-0">
                                  <span className="text-slate-400 font-semibold w-32 shrink-0 truncate" title={snap.name}>{snap.name}</span>
                                  <span className="text-slate-600 flex-1 truncate">{snap.description || '—'}</span>
                                  <span className="text-slate-700 shrink-0">{snap.snaptime ? new Date(snap.snaptime * 1000).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''}</span>
                                  <button onClick={() => handleRollback(machine.mac, snap.name)} className="osiris-btn text-[9px] px-2 py-0.5 shrink-0">Restaurer</button>
                                  <button onClick={() => handleDeleteSnapshot(machine.mac, snap.name)} className="osiris-action-btn osiris-action-btn--danger shrink-0"><IcoX cls="w-3 h-3" /></button>
                                </div>
                              ))}
                            </div>
                          )}
                          <div className="flex items-center gap-2 pt-1">
                            <input value={newSnapName} onChange={e => setNewSnapName(e.target.value)} placeholder="Nom du snapshot" className="osiris-input text-[10px] w-36 shrink-0" maxLength={40} />
                            <input value={newSnapDesc} onChange={e => setNewSnapDesc(e.target.value)} placeholder="Description (optionnel)" className="osiris-input text-[10px] flex-1" />
                            <button onClick={() => handleCreateSnapshot(machine.mac)} disabled={snapshotCreating || !newSnapName.trim()} className="osiris-btn text-[10px] px-3 shrink-0">
                              {snapshotCreating ? '…' : 'Créer'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        </>}
      </div>

      {/* ── Modale : changement de mot de passe ──────────────────────────── */}
      {showSettingsModal && (
        <div className="osiris-overlay" onClick={(e) => { if (e.target === e.currentTarget) { setShowSettingsModal(false); setTotpStep(null); setTotpSetup(null) } }}>
          <div className="osiris-modal" style={{ maxWidth: '480px' }}>
            <div className="osiris-modal-header">
              <h2 className="text-xs font-bold uppercase tracking-widest text-white">Parametres du compte</h2>
              <button onClick={() => { setShowSettingsModal(false); setTotpStep(null); setTotpSetup(null) }} className="text-slate-600 hover:text-slate-300 cursor-pointer transition-colors p-1"><IcoX cls="w-4 h-4" /></button>
            </div>
            {/* Sous-onglets */}
            <div className="flex border-b border-slate-800">
              {([
                { id: 'password', label: 'Mot de passe' },
                { id: 'totp', label: '2FA' },
                { id: 'apikeys', label: 'Cles API' },
                { id: 'integrations', label: 'Integrations' },
              ] as const).map(t => (
                <button key={t.id} onClick={() => { setSettingsTab(t.id as any); if (t.id === 'apikeys') fetchApiKeys(auth.token) }}
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
                  <button onClick={() => setShowSettingsModal(false)} className="osiris-btn w-full justify-center">Fermer</button>
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
                    <button type="button" onClick={() => setShowSettingsModal(false)} className="osiris-btn-ghost">Annuler</button>
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
                    {apiKeys.map((k: any) => (
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

      {/* ── Modale : navigateur WIM ──────────────────────────────────────── */}
      {showWimPicker && (
        <div className="osiris-overlay" onClick={e => { if (e.target === e.currentTarget) setShowWimPicker(null) }}>
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
                <label className="text-xs text-slate-400 self-center">Suffixe TeamViewer</label>
                <input type="password" className="osiris-input text-xs font-mono" placeholder="(inchangé si vide)" onChange={e => setEditingProfile({ ...editingProfile, tv_suffix: e.target.value })} />
                {(editingProfile.os === 'ubuntu' || editingProfile.os === 'debian') && (<>
                  <label className="text-xs text-slate-400 self-center">Type de machine</label>
                  <select value={editingProfile.machine_type ?? 'workstation'} onChange={e => setEditingProfile({ ...editingProfile, machine_type: e.target.value })} className="osiris-input text-xs">
                    <option value="workstation">Poste de travail</option>
                    <option value="server">Serveur</option>
                  </select>
                </>)}
              </div>
              {(editingProfile.os === 'ubuntu' || editingProfile.os === 'debian') && editingProfile.machine_type === 'server' && (
                <div className="pt-2 border-t border-slate-800/40 space-y-1">
                  <p className="text-[9px] uppercase tracking-widest text-slate-600">Cles SSH autorisees (une par ligne)</p>
                  <textarea rows={3} placeholder="ssh-ed25519 AAAA... user@host" defaultValue={editingProfile.ssh_authorized_keys} onChange={e => setEditingProfile({ ...editingProfile, ssh_authorized_keys: e.target.value })} className="osiris-input text-[10px] font-mono w-full resize-y" />
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
                const eligible = apps.filter(a => editingProfile.os === 'windows' ? a.winget_id : a.apt_package)
                if (eligible.length === 0) return null
                const selected = new Set((editingProfile.app_ids ?? '').split(',').filter(Boolean))
                const toggle = (id: number) => {
                  const s = new Set(selected)
                  s.has(String(id)) ? s.delete(String(id)) : s.add(String(id))
                  setEditingProfile({ ...editingProfile, app_ids: Array.from(s).join(',') })
                }
                return (
                  <div>
                    <p className="text-[10px] uppercase tracking-widest text-slate-600 mb-1.5">Applications à installer</p>
                    <div className="flex flex-wrap gap-1.5">
                      {eligible.map(a => {
                        const on = selected.has(String(a.id))
                        return (
                          <button key={a.id} type="button" onClick={() => toggle(a.id)}
                            className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] border transition-colors cursor-pointer ${on ? 'bg-blue-600/20 border-blue-500 text-blue-300' : 'bg-slate-900 border-slate-700 text-slate-400 hover:border-slate-500'}`}>
                            <span>{a.icon}</span><span>{a.name}</span>
                          </button>
                        )
                      })}
                    </div>
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
