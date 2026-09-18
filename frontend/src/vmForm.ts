// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Logique pure du formulaire de création de VM (InfrastructureTab), séparée pour
// rester testable sans monter de composant — et parce qu'un fichier .tsx ne peut
// exporter que des composants sans casser le Fast Refresh de Vite.

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
export const buildCreateVmPayload = <T extends { profile_id: unknown; template_id: unknown; organization_id: unknown }>(
  vmForm: T,
  vmNode: string,
) => ({
  ...vmForm,
  node: vmNode,
  profile_id: vmForm.profile_id ? Number(vmForm.profile_id) : null,
  template_id: vmForm.template_id ? Number(vmForm.template_id) : null,
  organization_id: vmForm.organization_id === '' ? null : Number(vmForm.organization_id),
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
export const avecProfil = <F extends { profile_id: string; vcpus: number; ram_mb: number; disk_gb: number; data_disk_gb: number }>(
  f: F,
  p: { id: number; vm_vcpus?: number; vm_ram_mb?: number; vm_disk_gb?: number; vm_data_disk_gb?: number } | undefined,
): F => p
  ? { ...f, profile_id: String(p.id), vcpus: p.vm_vcpus ?? f.vcpus, ram_mb: p.vm_ram_mb ?? f.ram_mb, disk_gb: p.vm_disk_gb ?? f.disk_gb, data_disk_gb: p.vm_data_disk_gb ?? f.data_disk_gb }
  : { ...f, profile_id: '' }

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
 *  aussi : un gabarit Windows sous un profil Ubuntu n'a aucun sens.
 *  cloud-init n'a pas besoin de l'agent : tout reste choisissable, les gabarits
 *  OSIRIS en tête. */
export const gabaritsPourMode = <T extends { vmid: number; famille?: string; osiris?: { os: string } | null }>(
  modeles: T[],
  mode: string,
  os: string,
): { proposes: T[]; autres: T[]; autresChoisissables: boolean } => {
  const famille = os === 'windows' ? 'windows' : 'linux'
  // Le système se lit d'abord sur l'hyperviseur (type d'invité), puis sur le
  // scellement : un gabarit marqué à la main ne porte que le premier.
  const systeme = (m: T) => m.famille || m.osiris?.os || ''
  const convient = (m: T) => Boolean(m.osiris) && (!systeme(m) || systeme(m) === famille)
  return {
    proposes: modeles.filter(convient),
    autres: modeles.filter(m => !convient(m)),
    autresChoisissables: mode !== 'template',
  }
}
