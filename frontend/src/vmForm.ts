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
