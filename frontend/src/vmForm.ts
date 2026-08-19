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
