// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import type { CodeEtatSite } from './types'

/** Comment afficher l'état d'un cache. Le message détaillé vient du serveur ;
 *  ici, seulement l'étiquette courte et sa couleur.
 *
 *  « Jamais » n'est pas une alerte : c'est l'état normal d'un site qu'on vient
 *  de créer. « Inachevée » non plus n'est pas rouge : une première copie dure
 *  plusieurs nuits et reprend seule. Ces deux-là le deviennent s'ils durent,
 *  ce que dit le message. */
export const presentationEtat = (code: CodeEtatSite): { libelle: string; classe: string } => {
  switch (code) {
    case 'a_jour':             return { libelle: 'À jour',             classe: 'text-emerald-300 border-emerald-500/40 bg-emerald-500/10' }
    case 'jamais':             return { libelle: 'Jamais synchronisé', classe: 'text-slate-300 border-slate-600 bg-slate-800/60' }
    case 'inachevee':          return { libelle: 'Copie inachevée',    classe: 'text-amber-300 border-amber-500/40 bg-amber-500/10' }
    case 'en_retard':          return { libelle: 'En retard',          classe: 'text-amber-300 border-amber-500/40 bg-amber-500/10' }
    case 'echec':              return { libelle: 'Copie en échec',     classe: 'text-red-300 border-red-500/40 bg-red-500/10' }
    case 'images_differentes': return { libelle: 'Images différentes', classe: 'text-red-300 border-red-500/40 bg-red-500/10' }
  }
}

/** « il y a 3 h » : l'opérateur juge un retard, pas un horodatage. */
export const depuis = (iso: string | null, maintenant: Date = new Date()): string => {
  if (!iso) return 'jamais'
  const s = Math.max(0, Math.round((maintenant.getTime() - new Date(iso).getTime()) / 1000))
  if (s < 60) return "à l'instant"
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`
  if (s < 48 * 3600) return `il y a ${Math.floor(s / 3600)} h`
  return `il y a ${Math.floor(s / 86400)} j`
}

export const taille = (octets: number): string => {
  if (octets < 1024) return `${octets} o`
  const unites = ['Ko', 'Mo', 'Go', 'To']
  let v = octets / 1024, i = 0
  while (v >= 1024 && i < unites.length - 1) { v /= 1024; i++ }
  return `${v.toLocaleString('fr-FR', { maximumFractionDigits: v < 10 ? 1 : 0 })} ${unites[i]}`
}

/** La ligne à coller telle quelle dans /etc/osiris-cache/cache.conf. */
export const ligneConf = (jeton: string): string => `SITE_JETON=${jeton}`
