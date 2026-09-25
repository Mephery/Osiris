// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Logique pure de l'écran Organisations, testable sans monter de composant.
import type { Organization, OrganizationPatch } from './types'

/** Le slug proposé pour un nom : « Plénitude & Co » → « plenitude-co ».
 *  Le taper à la main était une question de plus, sans réponse évidente pour
 *  qui découvre l'outil ; il reste modifiable avant création. */
export const slugDepuisNom = (nom: string): string =>
  nom.normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

/** Ce qui se modifie depuis la fiche. Le slug n'y est pas : l'API ne le
 *  modifie pas, et un champ proposé sans effet est pire qu'un champ absent. */
export type BrouillonOrg = Pick<Organization, 'name' | 'webhook_url' | 'zabbix_server' | 'mac_prefix'> & {
  /** Écriture seule : vide = inchangé. */
  bios_password: string
}

export const brouillonDe = (o: Organization): BrouillonOrg => ({
  name: o.name, webhook_url: o.webhook_url, zabbix_server: o.zabbix_server,
  mac_prefix: o.mac_prefix, bios_password: '',
})

/** Le PATCH à envoyer : seulement ce qui a changé. Un champ inchangé n'est pas
 *  renvoyé, pour qu'un enregistrement n'écrase jamais une valeur modifiée
 *  ailleurs entre-temps. Le mot de passe BIOS ne part que s'il a été saisi. */
export const changementsOrg = (o: Organization, b: BrouillonOrg): OrganizationPatch => {
  const patch: OrganizationPatch = {}
  for (const k of ['name', 'webhook_url', 'zabbix_server', 'mac_prefix'] as const) {
    if (b[k].trim() !== o[k]) patch[k] = b[k].trim()
  }
  if (b.bios_password) patch.bios_password = b.bios_password
  return patch
}
