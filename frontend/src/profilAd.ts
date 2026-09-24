// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Logique pure du choix de configuration AD dans un profil (ProfilesSection),
// séparée pour rester testable — un fichier .tsx ne peut exporter que des composants.
import type { DomainConfig, Organization } from './types'

/** La fiche Domaine AD à laquelle le profil est lié, s'il l'est et qu'elle existe encore. */
export const ficheDuProfil = (
  domainConfigId: number | null | undefined, fiches: DomainConfig[],
): DomainConfig | undefined =>
  domainConfigId ? fiches.find(f => f.id === domainConfigId) : undefined

/** Le compte de jonction se saisit-il dans le profil ?
 *
 *  Non dès que la fiche liée porte le sien : c'est lui qui sert au déploiement
 *  (le serveur efface d'ailleurs celui du profil). Proposer quand même les champs,
 *  c'était faire remplir un compte que rien ne lirait. Une fiche SANS compte
 *  (domaine et Wi-Fi seulement) laisse en revanche le compte au profil. */
export const compteSaisiDansLeProfil = (fiche: DomainConfig | undefined): boolean =>
  !fiche?.join_user

/** Libellé d'une fiche dans la liste : l'organisation d'abord, c'est par elle
 *  qu'on cherche (« le domaine de Plénitude »), puis le domaine lui-même. */
export const libelleFiche = (fiche: DomainConfig, organisations: Organization[]): string => {
  const org = organisations.find(o => o.id === fiche.organization_id)?.name
  const nom = fiche.name && fiche.name !== org ? ` (${fiche.name})` : ''
  return `${org ?? 'Organisation inconnue'} — ${fiche.domain}${nom}`
}
