// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.

export interface AuthState {
  token: string;
  email: string;
  role: string;
}

export interface Organization {
  id: number;
  name: string;
  slug: string;
  webhook_url: string;
}

export interface WimFile {
  name: string;
  size_mb: number;
  modified_at: string;
  is_golden: boolean;
}

export interface Machine {
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
  dism_progress?: number;
  hw_serial?: string;
  hw_model?: string;
  hw_ram_gb?: number;
  has_bitlocker?: boolean;
  has_laps?: boolean;
  user_name?: string;
  user_email?: string;
  notes?: string;
  smoke_status?: string;
  smoke_results?: string;
  laps_rotated_at?: string | null;
  hypervisor_id?: number | null;
  proxmox_vm_id?: number;
  proxmox_node?: string;
}

export interface DriverPack {
  id: number;
  vendor: string;
  model: string;
  os_code: string;
  size_mb: number;
  status: string;
  local_path: string;
  download_url: string;
  catalog_updated: string;
}

export interface Profile {
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
  domain_join_user: string;
  domain_join_password: string;
  win_image: string;
  win_index: number;
  enable_bitlocker: boolean;
  bitlocker_pin: boolean;
  network_drives: string;
  printers: string;
  post_script: string;
  tv_suffix: string;
  app_ids: string;
  laps_rotation_days: number;
  machine_type: string;
  ssh_authorized_keys: string;
}

export interface Application {
  id: number;
  name: string;
  winget_id: string;
  apt_package: string;
  category: string;
  icon: string;
}

export interface DeploymentEvent {
  id: number;
  timestamp: string;
  status: string;
  os: string;
  profile_name: string;
  hostname: string;
}

export interface Hypervisor {
  id: number;
  name: string;
  type: string;
  url: string;
  token_id: string;
  token_secret: string;
  tls_verify: boolean;
  snippets_storage: string;
  organization_id: number | null;
  created_at: string;
}

export interface ProxmoxTemplate {
  vmid: number;
  name: string;
  status: string;
  cores: number;
  maxmem_gb: number;
}

export interface ProxmoxNode {
  node: string;
  status: string;
  cpu: number;
  maxcpu: number;
  mem_gb: number;
  maxmem_gb: number;
}

export interface OsImage {
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

export interface SnapshotEntry {
  name: string;
  description: string;
  snaptime: number;
  vmstate: boolean;
  parent?: string;
}

export interface AuditLogEntry {
  id: number;
  timestamp: string;
  user_email: string;
  action: string;
  target_mac: string | null;
  details: Record<string, unknown> | null;
}

export const ACTION_META: Record<string, { label: string; cls: string }> = {
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

export const IMAGE_STATUS: Record<string, { label: string; bar: string; badge: string }> = {
  queued:      { label: 'En attente',     bar: 'bg-slate-500',   badge: 'text-slate-400 border-slate-700' },
  downloading: { label: 'Téléchargement', bar: 'bg-blue-500',    badge: 'text-blue-400 border-blue-800' },
  extracting:  { label: 'Extraction',     bar: 'bg-amber-500',   badge: 'text-amber-400 border-amber-800' },
  ready:       { label: 'Prête',          bar: 'bg-emerald-500', badge: 'text-emerald-400 border-emerald-800' },
  failed:      { label: 'Erreur',         bar: 'bg-red-500',     badge: 'text-red-400 border-red-800' },
}

export function formatDetails(d: Record<string, unknown> | null): string {
  if (!d) return '—'
  return Object.entries(d).map(([k, v]) => `${k}: ${v}`).join(' · ')
}

export function formatMac(mac: string): string {
  return mac.match(/.{1,2}/g)?.join(':').toUpperCase() ?? mac
}

export const EMPTY_FORM: Machine = { mac: '', client: '', os: 'windows', hostname: '', ou: '', organization_id: null, profile_id: null }

export function authHeader(token: string) {
  return { 'Authorization': `Bearer ${token}` }
}
