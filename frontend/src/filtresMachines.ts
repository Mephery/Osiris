// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Filtres de la liste des machines : logique pure, testable sans monter l'écran.

type MachineFiltrable = {
  status?: string
  hypervisor_id?: number | null
  profile_id?: number | null
  deployed_at?: string | null
  statut_depuis?: string | null
  tests_en_echec?: string[]
}

/** '' = tous · 'physique' · 'vm' · 'hv:<id>' = les VM d'un hyperviseur précis. */
export const correspondType = (m: MachineFiltrable, filtre: string): boolean => {
  if (!filtre) return true
  const vm = m.hypervisor_id != null
  if (filtre === 'physique') return !vm
  if (filtre === 'vm') return vm
  if (filtre.startsWith('hv:')) return m.hypervisor_id === Number(filtre.slice(3))
  return true
}

/** '' = tous · 'aucun' = sans profil · sinon l'identifiant du profil. */
export const correspondProfil = (m: MachineFiltrable, filtre: string): boolean =>
  !filtre ? true : filtre === 'aucun' ? m.profile_id == null : m.profile_id === Number(filtre)

const JOUR = 86_400_000

/** '' · 'jour' · 'semaine' · 'mois' · 'ancien' (plus d'un mois) · 'jamais'. */
export const correspondDate = (m: MachineFiltrable, filtre: string, maintenant: number): boolean => {
  if (!filtre) return true
  if (!m.deployed_at) return filtre === 'jamais'
  if (filtre === 'jamais') return false
  const age = maintenant - new Date(m.deployed_at).getTime()
  return filtre === 'jour' ? age < JOUR
    : filtre === 'semaine' ? age < 7 * JOUR
    : filtre === 'mois' ? age < 30 * JOUR
    : filtre === 'ancien' ? age >= 30 * JOUR
    : true
}

/** Tests qui échouent PAR CONSTRUCTION sur un VLAN fermé : ils ne disent pas qu'une
 *  machine a un problème, seulement qu'elle ne sort pas sur internet. Les compter
 *  ferait remonter presque toutes les VM serveurs et noierait le reste. */
export const TESTS_ATTENDUS_EN_ECHEC = ['Acces internet (HTTPS)']

/** Seuils du « bloqué ». Un PC physique en attente n'est JAMAIS bloqué : il attend
 *  légitimement qu'on le démarre. Une VM, elle, démarre seule : trente minutes sans
 *  nouvelle (le seuil de la sonde de supervision), c'est qu'elle ne rappellera pas. */
const VM_EN_ATTENTE_MAX = 30 * 60_000
const EN_COURS_MAX = 2 * 3_600_000

/** Pourquoi une machine demande qu'on s'en occupe — `null` si elle va bien. */
export const raisonATraiter = (m: MachineFiltrable, maintenant: number): string | null => {
  if (m.status === 'failed') return 'déploiement en échec'
  const depuis = m.statut_depuis ? maintenant - new Date(m.statut_depuis).getTime() : 0
  if (m.status === 'pending' && m.hypervisor_id != null && depuis > VM_EN_ATTENTE_MAX)
    return 'VM en attente sans nouvelles'
  if (m.status === 'deploying' && depuis > EN_COURS_MAX) return 'déploiement bloqué'
  const echecs = (m.tests_en_echec ?? []).filter(t => !TESTS_ATTENDUS_EN_ECHEC.includes(t))
  if (echecs.length) return `tests en échec : ${echecs.join(', ')}`
  return null
}
