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
  /** Adresse du serveur/proxy Zabbix de l'organisation. Vide = pas de supervision. */
  zabbix_server: string;
  /** Préfixe MAC imposé par le client, 4 octets hexa sans séparateur (ex: "02aabbcc").
   *  Vide = on ne réécrit pas la MAC des machines. */
  mac_prefix: string;
  /** Le mot de passe BIOS n'est jamais renvoyé en clair : on sait seulement s'il existe. */
  has_bios_password: boolean;
}

/** Corps d'un PATCH d'organisation. `bios_password` est en ÉCRITURE SEULE : il
 *  s'envoie mais ne fait pas partie d'`Organization`, que l'API ne renvoie jamais
 *  avec le secret en clair. Champ absent = valeur en base conservée. */
export type OrganizationPatch = Partial<Omit<Organization, 'has_bios_password'>> & {
  bios_password?: string;
};

export interface VpnTunnel {
  id: number;
  organization_id: number;
  name: string;
  slug: string;
  has_config: boolean;
  remote_dns: string;
  route_cidr: string;
  vpn_username: string;
  has_password: boolean;
  requires_totp: boolean;
  enabled: boolean;
  status: string;
  last_applied_at: string | null;
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
  /** MAC de l'adaptateur USB-Ethernet utilisé pour CE déploiement. Facultative, et
   *  oubliée automatiquement par OSIRIS en fin de déploiement (le dongle redevient
   *  réutilisable sur une autre machine). Chaîne vide = libérer explicitement. */
  deploy_mac?: string | null;
  client: string;
  os: string;
  hostname: string;
  ou: string;
  status?: string;
  deployed_at?: string | null;
  organization_id?: number | null;
  profile_id?: number | null;
  driver_pack_id?: number | null;
  dism_progress?: number;
  hw_serial?: string;
  hw_model?: string;
  hw_ram_gb?: number;
  hw_disk_gb?: number;
  hw_disk_type?: string;
  hw_cpu?: string;
  has_bitlocker?: boolean;
  has_laps?: boolean;
  user_name?: string;
  user_email?: string;
  /** Installer l'agent Zabbix au premier démarrage (sans effet si l'organisation
   *  n'a pas de collecteur renseigné). Activé par défaut. */
  supervised?: boolean;
  /** Adressage IP fixe appliqué par cloud-init. Vide = DHCP. */
  ip_cidr?: string;
  gateway?: string;
  dns_servers?: string;
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
  error: string;
  hw_ids: string;
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
  /** Gabarit matériel des VM créées avec ce profil (valeurs par défaut du formulaire). */
  vm_vcpus: number;
  vm_ram_mb: number;
  vm_disk_gb: number;
  /** Second disque monté sur /data. 0 = pas de disque de données. */
  vm_data_disk_gb: number;
  /** Linux : poser un mot de passe root aléatoire, stocké chiffré côté OSIRIS. */
  set_root_password: boolean;
}

export interface Application {
  id: number;
  name: string;
  winget_id: string;
  apt_package: string;
  category: string;
  icon: string;
  install_type?: string;
  installer_file?: string;
  /** Script bash exécuté après l'apt-get install de ce paquet, au premier démarrage. */
  linux_post_install?: string;
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
  /** Une autorité de certification est-elle renseignée pour cet hyperviseur ? */
  ca_present: boolean;
  /** De quoi relire l'autorité collée sans afficher tout le PEM. */
  ca_resume: { autorite?: string; expire_le?: string; erreur?: string };
  /** Pool Proxmox d'accueil des VM créées par OSIRIS. Vide = pas de pool.
   *  Permet de n'attribuer au jeton que des droits sur `/pool/<pool>` au lieu de `/`,
   *  et donc de faire refuser par l'hyperviseur toute action sur une VM tierce. */
  pool: string;
  snippets_storage: string;
  /** URL d'OSIRIS telle que la voient les VM de cet hyperviseur. Vide = URL globale. */
  callback_url: string;
  organization_id: number | null;
  created_at: string;
}

export interface ProxmoxTemplate {
  vmid: number;
  /** Nœud qui détient la configuration du template. Le déploiement peut viser un
   *  autre nœud : sur un stockage partagé, OSIRIS clone vers celui qu'on choisit. */
  node?: string;
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

/** Stockage d'un hyperviseur où OSIRIS peut écrire — pool Proxmox ou datastore
 *  vSphere, ramenés au même format. `node` vide = partagé par tout le cluster. */
export interface ClusterStorage {
  storage: string;
  node: string;
  type: string;
  shared: boolean;
  online: boolean;
  total_gb: number;
  avail_gb: number;
  used_pct: number;
  roles: string[];
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

// Événement du flux d'activité temps réel du dashboard (alimenté par le WebSocket dans App.tsx).
export interface LiveEvent {
  id: string;
  timestamp: number;
  mac: string;
  hostname: string;
  kind: 'status' | 'capture';
  status?: string;
  success?: boolean;
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

export const EMPTY_FORM: Machine = { mac: '', deploy_mac: '', client: '', os: 'windows', hostname: '', ou: '', organization_id: null, profile_id: null, driver_pack_id: null, hw_serial: '', supervised: true }

export function authHeader(token: string) {
  return { 'Authorization': `Bearer ${token}` }
}
