// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Logique pure du formulaire de création de VM (InfrastructureTab), séparée pour
// rester testable sans monter de composant — et parce qu'un fichier .tsx ne peut
// exporter que des composants sans casser le Fast Refresh de Vite.
import { decrireDisque, disqueData, disquesPourServeur, type DisqueForm } from './disquesForm'

/** L'adresse saisie tombe-t-elle dans le réseau du bridge choisi ? `null` si l'une
 *  des deux n'est pas exploitable — on se tait plutôt que d'alarmer à tort.
 *
 *  Se tromper de réseau ne fait échouer aucun appel : la VM naît, démarre, ne route
 *  nulle part et reste « en attente » sans un mot d'explication. C'est le symptôme
 *  le plus coûteux de toute la chaîne, et le seul moment où il est bon marché de
 *  l'attraper est ici, avant de valider. */
export const dansLeReseau = (ip: string, reseau: string): boolean | null => {
  const adresse = ip.split('/')[0].trim()
  const [base, prefixe] = reseau.split('/')
  const quadruplet = /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/
  if (!quadruplet.test(adresse) || !quadruplet.test(base ?? '')) return null
  const entier = (a: string) => a.split('.').reduce((acc, o) => acc * 256 + Number(o), 0)
  const masque = Number(prefixe) === 0 ? 0 : (-1 << (32 - Number(prefixe))) >>> 0
  return ((entier(adresse) & masque) >>> 0) === ((entier(base) & masque) >>> 0)
}

/** Complète l'adresse saisie avec le préfixe du réseau si elle n'en a pas déjà un.
 *  Ne touche à rien d'autre : une adresse vide, déjà préfixée, ou un préfixe
 *  inconnu ressortent inchangés. */
export const completerPrefixeCidr = (ipCidr: string, prefixe: number | undefined): string =>
  ipCidr && prefixe !== undefined && !ipCidr.includes('/')
    ? `${ipCidr.trim()}/${prefixe}`
    : ipCidr

/** Construit le corps envoyé à `/hypervisors/{id}/create-vm` à partir du formulaire.
 *  Isolé du fetch pour que les conversions — '' → null, chaîne → nombre — se
 *  vérifient sans simuler tout un cycle de rendu React. Générique sur `T` pour que
 *  le reste des champs du formulaire garde son vrai type plutôt que de s'effacer
 *  derrière un `Record<string, unknown>`. */
export const buildCreateVmPayload = <T extends { profile_id: unknown; template_id: unknown; organization_id: unknown;
                                                 os?: string; disques?: DisqueForm[]; data_disk_gb?: number }>(
  vmForm: T,
  vmNode: string,
) => ({
  ...vmForm,
  node: vmNode,
  profile_id: vmForm.profile_id ? Number(vmForm.profile_id) : null,
  template_id: vmForm.template_id ? Number(vmForm.template_id) : null,
  organization_id: vmForm.organization_id === '' ? null : Number(vmForm.organization_id),
  // Linux : la liste des disques ; Windows : le disque de données unique. Jamais
  // les deux — le serveur refuserait la liste sous Windows.
  disques: vmForm.os === 'windows' ? [] : disquesPourServeur(vmForm.disques ?? []),
  data_disk_gb: vmForm.os === 'windows' ? (vmForm.data_disk_gb ?? 0) : 0,
})

/** L'image système déclarée par le profil sera-t-elle ignorée par ce mode d'amorçage ?
 *
 *  `win_image` n'est lu que par le script de déploiement WinPE, donc uniquement en
 *  mode `pxe`. Cloner un gabarit ne passe jamais par là : l'OS du clone est celui
 *  de l'image clonée, quoi qu'annonce le profil.
 *
 *  Le 25/08, une VM a été créée depuis un gabarit Windows Server 2022 avec le
 *  profil nommé « Windows Server 2025 ». Rien dans le formulaire ne disait que ce
 *  nom ne s'appliquait pas à ce mode — et rien n'aurait échoué non plus : on
 *  obtient simplement un OS différent de celui qu'on croit avoir demandé. */
export const imageDuProfilIgnoree = (
  bootMode: string,
  profil: { win_image?: string } | undefined,
): boolean => bootMode !== 'pxe' && Boolean(profil?.win_image)

/** Ce couple hyperviseur / mode d'amorçage sait-il porter une adresse fixe ?
 *
 *  Un clone NU ne reçoit aucune injection : c'est sa définition. Encore faut-il
 *  que quelque chose, dans la VM, sache lire l'adresse qu'on veut lui donner.
 *  Sur vSphere `guestinfo` sert de canal et l'agent gravé le lit ; sur Proxmox
 *  il n'existe aucun équivalent, et l'adresse saisie était simplement PERDUE —
 *  la VM démarrait en DHCP, ou sans rien du tout sur un VLAN qui n'en a pas,
 *  puis restait muette sans qu'aucune erreur ne soit levée.
 *
 *  L'API refuse désormais ce couple, mais un champ qu'on ne peut pas remplir
 *  vaut mieux qu'un formulaire rejeté après coup. */
export const adressageFixeImpossible = (
  typeHyperviseur: string | undefined,
  bootMode: string,
): boolean => (typeHyperviseur ?? 'proxmox').toLowerCase() === 'proxmox'
  && bootMode === 'template'

/** Le profil qu'OSIRIS utilisera quand aucun n'est choisi : le plus ancien de
 *  l'OS, comme `_resolve_profile` côté serveur.
 *
 *  « Profil par défaut » laisse croire à un réglage neutre. C'est en réalité un
 *  profil bien précis — pour Ubuntu, un poste de travail qui joint l'AD et ne
 *  dépose aucune clé SSH —, choisi sans que personne l'ait vu. */
export const profilParDefaut = <P extends { id: number; os: string }>(
  profils: P[],
  os: string,
): P | undefined =>
  profils.filter(p => p.os === os).reduce<P | undefined>((plusAncien, p) => (!plusAncien || p.id < plusAncien.id ? p : plusAncien), undefined)

/** Les profils d'un OS, séparés entre ceux qui peuvent créer une VM et les autres.
 *
 *  Un profil sans aucune porte d'entrée (ni clé SSH, ni domaine, ni root de
 *  secours — cf. `resume.alerte`, calculé par le serveur) déploierait une VM où
 *  personne n'entre ; le serveur la refuse. Le formulaire ne doit donc pas le
 *  proposer comme un choix ordinaire : quelqu'un qui découvre l'outil prend le
 *  nom le plus rassurant, « Ubuntu — par défaut », qui était justement celui-là.
 *
 *  Le tri porte sur ce que fait le profil, jamais sur son nom ou son numéro : un
 *  profil créé demain sans clé tombera tout seul du bon côté. */
export const profilsPourVm = <P extends { id: number; os: string; resume?: { alerte: string } }>(
  profils: P[],
  os: string,
): { utilisables: P[]; inutilisables: P[] } => {
  const duSysteme = profils.filter(p => p.os === os).sort((a, b) => a.id - b.id)
  return {
    utilisables: duSysteme.filter(p => !p.resume?.alerte),
    inutilisables: duSysteme.filter(p => Boolean(p.resume?.alerte)),
  }
}

/** Sélectionne un profil et reprend son gabarit matériel : c'est le profil qui
 *  sait ce que demande ce type de serveur. Les valeurs restent modifiables. */
export const avecProfil = <F extends { profile_id: string; vcpus: number; ram_mb: number; disk_gb: number; data_disk_gb: number; disques?: DisqueForm[] }>(
  f: F,
  p: { id: number; vm_vcpus?: number; vm_ram_mb?: number; vm_disk_gb?: number; vm_data_disk_gb?: number } | undefined,
): F => {
  if (!p) return { ...f, profile_id: '' }
  const data = p.vm_data_disk_gb ?? f.data_disk_gb
  return {
    ...f, profile_id: String(p.id), vcpus: p.vm_vcpus ?? f.vcpus, ram_mb: p.vm_ram_mb ?? f.ram_mb,
    disk_gb: p.vm_disk_gb ?? f.disk_gb, data_disk_gb: data,
    // Le disque de données du profil devient le premier de la liste (Linux)
    ...(f.disques !== undefined ? { disques: data ? [disqueData(data)] : [] } : {}),
  }
}

export type ModeVm = 'pxe' | 'template' | 'cloudinit'

/** Le mode d'amorçage qui marche, selon l'hyperviseur et le système.
 *
 *  Le formulaire partait en PXE pour tout le monde : le mode le plus lent, et
 *  celui qu'on n'utilise presque plus. Le choix n'est pas du goût, il découle de
 *  ce que chaque hyperviseur sait porter :
 *  - vSphere : le clone NU du gabarit, dont l'agent lit son adresse dans
 *    `guestinfo` — validé sous Linux et Windows ;
 *  - Proxmox, Linux : cloud-init, seul canal qui y porte une adresse fixe (un
 *    clone nu n'en reçoit aucune, le serveur le refuse) ;
 *  - Proxmox, Windows : PXE / WinPE, faute de gabarit sysprepé à cloner.
 *  Les autres modes restent accessibles dans les options avancées. */
export const modeParDefaut = (typeHv: string | undefined, os: string): ModeVm => {
  if ((typeHv ?? '').toLowerCase() === 'proxmox') return os === 'windows' ? 'pxe' : 'cloudinit'
  return 'template'
}

/** Ce qui manque encore pour pouvoir créer la VM, dans l'ordre de l'écran.
 *  Un bouton grisé sans raison laisse chercher ; une liste dit quoi faire. */
export const champsManquants = (f: {
  hostname: string; client: string; boot_mode: string; template_id: string; storage: string; bridge: string
}, hvChoisi: boolean, noeud: string): string[] => [
  !f.hostname.trim() && 'nom',
  !f.client.trim() && 'client',
  !hvChoisi && 'hyperviseur',
  hvChoisi && !noeud && 'nœud',
  f.boot_mode !== 'pxe' && !f.template_id && 'gabarit',
  !f.storage && 'stockage',
  !f.bridge && 'réseau',
].filter((c): c is string => Boolean(c))

/** Les modèles d'un hyperviseur, triés selon ce que le mode exige d'eux.
 *
 *  Un clone NU ne reçoit aucune injection : c'est l'agent gravé dans le gabarit
 *  qui rappelle OSIRIS. Un modèle sans agent y démarre et ne rappelle jamais —
 *  il est donc proposé grisé, avec la raison. Un modèle d'un autre système
 *  aussi : un gabarit Windows sous un profil Ubuntu n'a aucun sens, et un
 *  gabarit Debian quand on a choisi Ubuntu non plus. Une distribution inconnue
 *  reste proposée, après les autres : mieux vaut ne pas trier que cacher à tort.
 *  cloud-init n'a pas besoin de l'agent : tout reste choisissable, les gabarits
 *  OSIRIS en tête. */
export const gabaritsPourMode = <T extends { vmid: number; famille?: string; distribution?: string; osiris?: { os: string } | null }>(
  modeles: T[],
  mode: string,
  os: string,
): { proposes: T[]; autres: T[]; autresChoisissables: boolean } => {
  const famille = os === 'windows' ? 'windows' : 'linux'
  // Le système se lit d'abord sur l'hyperviseur (type d'invité), puis sur le
  // scellement : un gabarit marqué à la main ne porte que le premier.
  const systeme = (m: T) => m.famille || m.osiris?.os || ''
  const convient = (m: T) => Boolean(m.osiris) && (!systeme(m) || systeme(m) === famille)
    && (!m.distribution || m.distribution === os)
  return {
    proposes: modeles.filter(convient)
      .sort((a, b) => Number(b.distribution === os) - Number(a.distribution === os)),
    autres: modeles.filter(m => !convient(m)),
    autresChoisissables: mode !== 'template',
  }
}

const RANG_AGENT: Record<string, number> = { a_jour: 0, perime: 1, inconnu: 2 }

/** Le gabarit à présélectionner : celui de la distribution choisie, à l'agent
 *  le plus frais, puis la version la plus récente d'après le nom (« v3 » avant
 *  « v2 »). Aucun gabarit de CETTE distribution : rien — un gabarit au système
 *  incertain ne se choisit pas à la place de l'opérateur. */
export const gabaritParDefaut = <T extends { vmid: number; name: string; famille?: string; distribution?: string; osiris?: { os: string; etat?: string } | null }>(
  modeles: T[],
  mode: string,
  os: string,
): string => {
  const [meilleur] = gabaritsPourMode(modeles, mode, os).proposes
    .filter(m => m.distribution === os)
    .sort((a, b) => (RANG_AGENT[a.osiris?.etat ?? ''] ?? 3) - (RANG_AGENT[b.osiris?.etat ?? ''] ?? 3)
      || b.name.localeCompare(a.name, undefined, { numeric: true }))
  return meilleur ? String(meilleur.vmid) : ''
}

export const LIBELLE_MODE: Record<ModeVm, string> = {
  template: 'Clone du gabarit',
  cloudinit: 'Clone + cloud-init',
  pxe: 'Installation PXE',
}

/** Le formulaire de création de VM à l'ouverture. Ici plutôt que dans le composant
 *  pour que le test du récapitulatif en dérive ses champs : un champ ajouté ici
 *  sans être montré au récapitulatif fait échouer ce test. */
export const FORMULAIRE_VIDE = { organization_id: '' as number | '', hostname: '', client: '', os: 'ubuntu', profile_id: '', ou: '', storage: '', bridge: '', folder: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, data_disk_gb: 0, disques: [] as DisqueForm[], ip_cidr: '', gateway: '', dns_servers: '', iso: '', boot_mode: 'template' as ModeVm, template_id: '', post_script: '' }

export type ChargeVm = ReturnType<typeof buildCreateVmPayload<typeof FORMULAIRE_VIDE>>

export const tailleRam = (mo: number) => mo >= 1024 ? `${+(mo / 1024).toFixed(1)} Go` : `${mo} Mo`

const NOM_OS: Record<string, string> = { ubuntu: 'Ubuntu', debian: 'Debian', windows: 'Windows' }

/** Une ligne du récapitulatif, et les champs envoyés qu'elle montre. */
export interface LigneRecap { texte: string; champs: (keyof ChargeVm)[]; attention?: boolean }
export interface SectionRecap { titre: string; lignes: LigneRecap[] }

/** Ce que le formulaire sait nommer mieux que la charge : la charge porte des
 *  identifiants (organisation 3, gabarit 9005), l'écran doit dire leur nom. */
export interface ContexteRecap {
  hyperviseur: string
  organisation?: string
  profil?: { name: string; resume?: { lignes: { sujet: string; texte: string }[] } }
  gabarit?: string
  reseau?: string
  stockage?: string
  /** vSphere seulement : Proxmox n'a pas de dossiers, la ligne n'y dirait rien. */
  dossiers: boolean
}

/** Le récapitulatif avant création, lu dans la charge qui PART au serveur.
 *
 *  Pas dans le formulaire : un récapitulatif recopié champ par champ diverge un
 *  jour de ce qui est envoyé — c'est la famille des « champs décoratifs », un
 *  réglage montré qui n'est pas celui appliqué. Ici chaque ligne déclare les
 *  champs qu'elle montre, et le test exige que TOUS les champs de la charge
 *  soient montrés. Une valeur vide se dit (« DHCP », « aucun script ») au lieu
 *  de disparaître : ce qu'on a accepté sans le voir est justement ce qu'il faut
 *  voir ici. */
export const recapVm = (c: ChargeVm, ctx: ContexteRecap): SectionRecap[] => {
  const clone = c.boot_mode !== 'pxe'
  const os = NOM_OS[c.os] ?? c.os
  const profil = ctx.profil
    ? `Profil « ${ctx.profil.name} »${ctx.profil.resume?.lignes.length
        ? ' : ' + ctx.profil.resume.lignes.map(l => `${l.sujet} ${l.texte}`).join(' · ') : ''}`
    : 'Aucun profil'
  return [
    { titre: 'La machine', lignes: [
      { texte: `${c.hostname} · client ${c.client}`, champs: ['hostname', 'client'] },
      c.organization_id === null
        ? { texte: 'Aucune organisation : la VM ne sera pas supervisée', champs: ['organization_id'], attention: true }
        : { texte: `Organisation ${ctx.organisation ?? c.organization_id} : supervisée`, champs: ['organization_id'] },
      { texte: clone
          ? `${os} : système du gabarit « ${ctx.gabarit ?? c.template_id ?? '?'} », pas celui du profil`
          : `${os} : installé par le réseau`,
        champs: ['os', 'template_id'] },
      { texte: profil, champs: ['profile_id'], attention: !ctx.profil },
    ] },
    { titre: 'Où', lignes: [
      { texte: `${ctx.hyperviseur} › ${c.node} · stockage ${ctx.stockage ?? c.storage} · réseau ${ctx.reseau ?? c.bridge}`,
        champs: ['node', 'storage', 'bridge'] },
      ...(ctx.dossiers || c.folder
        ? [{ texte: `Dossier ${c.folder || 'racine du datacenter'}`, champs: ['folder'] as (keyof ChargeVm)[] }]
        : []),
    ] },
    { titre: 'Adresse', lignes: [
      c.ip_cidr
        ? { texte: `${c.ip_cidr} · passerelle ${c.gateway || 'aucune'} · DNS ${c.dns_servers || 'aucun'}`,
            champs: ['ip_cidr', 'gateway', 'dns_servers'] }
        : { texte: "DHCP : un serveur DHCP doit répondre sur ce réseau, sinon la VM ne contactera jamais OSIRIS",
            champs: ['ip_cidr', 'gateway', 'dns_servers'] },
    ] },
    { titre: 'Matériel', lignes: [
      { texte: `${c.vcpus} vCPU · ${tailleRam(c.ram_mb)} RAM · disque système ${c.disk_gb} Go`,
        champs: ['vcpus', 'ram_mb', 'disk_gb'] },
      // Chaque disque sur sa ligne : c'est ici qu'on relit un point de montage
      ...(c.disques.length
        ? c.disques.map(d => ({ texte: decrireDisque(d), champs: ['disques', 'data_disk_gb'] as (keyof ChargeVm)[] }))
        : [{ texte: c.data_disk_gb ? `Disque de données : ${c.data_disk_gb} Go` : 'Pas de disque supplémentaire',
             champs: ['disques', 'data_disk_gb'] as (keyof ChargeVm)[] }]),
    ] },
    { titre: 'Comment', lignes: [
      { texte: LIBELLE_MODE[c.boot_mode] + (c.iso ? ` · ISO ${c.iso}` : ''), champs: ['boot_mode', 'iso'] },
      { texte: `OU Active Directory : ${c.ou || 'non précisée (emplacement par défaut)'}`, champs: ['ou'] },
      { texte: c.post_script.trim()
          ? `Script propre à cette VM : ${c.post_script.trim().split('\n').length} ligne(s), exécuté après celui du profil`
          : 'Pas de script propre à cette VM',
        champs: ['post_script'] },
    ] },
  ]
}

/** Ce qui va se passer après le clic, et combien de temps. Un déploiement qui
 *  n'annonce pas sa durée passe pour planté à la première minute : c'est ainsi
 *  qu'un collègue a abandonné l'outil en août. Durées mesurées, données en
 *  « environ » — une promesse tenue au plus près vaut mieux qu'une précise. */
export const etapesVm = (c: Pick<ChargeVm, 'boot_mode' | 'os' | 'node'>, gabarit?: string): string[] => {
  const suivi = 'Suivi en direct dans Machines, jusqu\'à « déployée »'
  if (c.boot_mode === 'pxe') return [
    c.os === 'windows'
      ? 'La VM démarre sur WinPE et installe Windows : environ 20 min'
      : 'La VM démarre sur le réseau et installe le système : environ 20 min',
    'Elle contacte OSIRIS à la fin de l\'installation',
    suivi,
  ]
  return [
    `Copie du gabarit${gabarit ? ` « ${gabarit} »` : ''} sur ${c.node}`,
    c.boot_mode === 'cloudinit'
      ? 'Configuration par cloud-init au démarrage (nom, réseau, comptes) : environ 30 s'
      : 'Au démarrage, l\'agent OSIRIS du gabarit contacte OSIRIS : environ 2 min',
    suivi,
  ]
}

/** Les réseaux à proposer, selon que l'opérateur a demandé à tout voir.
 *
 *  Le serveur dit pourquoi un réseau n'est pas fait pour une VM (`reserve`) ;
 *  ici on le range. Le réseau déjà choisi reste toujours visible : décocher la
 *  case ne doit pas laisser une sélection que l'écran ne montre plus. */
export const reseauxPourVm = <N extends { iface: string; reserve?: string }>(
  reseaux: N[],
  tousVisibles: boolean,
  choisi: string,
): { proposes: N[]; reserves: N[]; masques: number } => {
  const reserves = reseaux.filter(n => n.reserve)
  return {
    proposes: reseaux.filter(n => !n.reserve),
    reserves: tousVisibles ? reserves : reserves.filter(n => n.iface === choisi),
    masques: tousVisibles ? 0 : reserves.filter(n => n.iface !== choisi).length,
  }
}

/** Le stockage à présélectionner : le partagé qui a le plus de place.
 *
 *  Partagé d'abord, car un disque local enferme la VM sur son nœud (ni
 *  migration, ni redémarrage ailleurs s'il tombe). Puis la place libre, ce qui
 *  répartit les VM entre volumes voisins. Aucun partagé : le seul stockage s'il
 *  n'y en a qu'un, sinon rien — on ne choisit pas un disque local à la place
 *  de l'opérateur. */
export const stockageParDefaut = (
  stockages: { storage: string; avail_gb: number; shared?: boolean }[],
): string => {
  const partages = stockages.filter(s => s.shared).sort((a, b) => b.avail_gb - a.avail_gb)
  if (partages.length) return partages[0].storage
  return stockages.length === 1 ? stockages[0].storage : ''
}

/** Ce que l'hyperviseur sait des adresses d'un réseau (GET …/network-usage). */
export interface UsageReseau {
  adresses: { ip: string; vm: string; source: string }[]
  /** VM branchées sur ce réseau dont aucune adresse n'est connue : éteintes,
   *  en DHCP, sans agent. Inconnue ne veut pas dire libre. */
  sans_adresse: string[]
}

/** Les adresses prises sur ce réseau : celles lues sur l'hyperviseur, plus les
 *  fiches d'OSIRIS qu'il ne voit pas (une VM éteinte en DHCP, par exemple).
 *  Triées dans l'ordre des adresses, pas des chaînes (« .9 » avant « .10 »). */
export const adressesPrises = (usage: UsageReseau | null, occupeesOsiris: string[]): { ip: string; vm: string }[] => {
  const prises = new Map<string, string>()
  for (const a of usage?.adresses ?? []) if (!prises.has(a.ip)) prises.set(a.ip, a.vm)
  for (const ip of occupeesOsiris) if (!prises.has(ip)) prises.set(ip, 'fiche OSIRIS')
  const rang = (ip: string) => ip.split('.').reduce((acc, o) => acc * 256 + Number(o), 0)
  return [...prises].map(([ip, vm]) => ({ ip, vm })).sort((a, b) => rang(a.ip) - rang(b.ip))
}

/** Qui occupe déjà cette adresse, ou null. */
export const occupantDe = (ip: string, prises: { ip: string; vm: string }[]): string | null =>
  (ip && prises.find(p => p.ip === ip)?.vm) || null

/** Les adresses prises, regroupées pour se lire d'un coup d'œil : le préfixe
 *  commun une seule fois, puis des plages de derniers octets.
 *  [.10, .11, .12, .14, .241] → [{ prefixe: '192.0.2', plages: ['10–12', '14', '241'] }].
 *  Dix-huit adresses complètes à la suite faisaient un mur que personne ne lit
 *  (vu le 25/09) ; c'est pourtant là qu'on cherche un trou. */
export const plagesAdresses = (prises: { ip: string; vm: string }[]):
    { prefixe: string; plages: { texte: string; vms: string[] }[] }[] => {
  const parPrefixe = new Map<string, { octet: number; ip: string; vm: string }[]>()
  for (const p of prises) {
    const i = p.ip.lastIndexOf('.')
    const liste = parPrefixe.get(p.ip.slice(0, i)) ?? []
    liste.push({ octet: Number(p.ip.slice(i + 1)), ip: p.ip, vm: p.vm })
    parPrefixe.set(p.ip.slice(0, i), liste)
  }
  return [...parPrefixe].map(([prefixe, adresses]) => {
    adresses.sort((a, b) => a.octet - b.octet)
    const plages: { texte: string; vms: string[] }[] = []
    let debut = 0
    for (let i = 1; i <= adresses.length; i++) {
      if (i === adresses.length || adresses[i].octet !== adresses[i - 1].octet + 1) {
        const [a, b] = [adresses[debut], adresses[i - 1]]
        plages.push({
          texte: a === b ? `${a.octet}` : `${a.octet}–${b.octet}`,
          vms: adresses.slice(debut, i).map(x => `${x.ip} ${x.vm}`),
        })
        debut = i
      }
    }
    return { prefixe, plages }
  })
}
