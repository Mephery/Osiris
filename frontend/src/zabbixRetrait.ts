// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.

/** Sort de l'hôte Zabbix quand une machine quitte OSIRIS (cf. backend zabbix.py).
 *
 *  Sans choix, chaque VM supprimée laissait un hôte orphelin qui alertait
 *  « agent injoignable » jusqu'à ce que quelqu'un le retire à la main. */

export type ChoixZabbix = 'rien' | 'desactiver' | 'supprimer'

/** Réponse de GET /machines/{mac}/zabbix */
export interface EtatZabbix {
  configure: boolean
  existe?: boolean
  actif?: boolean
  /** Rangé dans le groupe d'OSIRIS : seul cas où OSIRIS y touche */
  gere?: boolean
  groupes?: string[]
  erreur?: string
}

export const LIBELLES_CHOIX: Record<ChoixZabbix, { titre: string; detail: string }> = {
  rien:       { titre: 'Ne rien changer', detail: 'la machine reste supervisée' },
  desactiver: { titre: 'Désactiver',      detail: "garde l'historique, coupe les alertes" },
  supprimer:  { titre: 'Supprimer',       detail: 'pour une VM de test : historique perdu' },
}

/** Présélection (choix de Coline, 08/10) : la VM disparaît ⇒ ses alertes n'ont
 *  plus de sens, on désactive sans perdre l'historique ; la fiche seule part ⇒
 *  la machine vit peut-être encore, on ne touche à rien. Un choix explicite de
 *  l'opérateur l'emporte toujours. */
export const choixEffectif = (choisi: ChoixZabbix | null, detruireVm: boolean): ChoixZabbix =>
  choisi ?? (detruireVm ? 'desactiver' : 'rien')

/** La section n'a de sens que pour un hôte qu'OSIRIS peut gérer. */
export const choixPossible = (e: EtatZabbix | null): boolean =>
  !!e && e.configure && !!e.existe && !!e.gere

/** Ce que le serveur a fait, en clair pour l'opérateur ; null = rien à dire. */
export const decrireResultat = (r: string | undefined, hostname: string): string | null => {
  if (!r || r === 'inchange') return null
  if (r === 'desactive') return `Hôte Zabbix ${hostname} désactivé.`
  if (r === 'supprime') return `Hôte Zabbix ${hostname} supprimé.`
  if (r === 'absent') return null
  if (r === 'non-gere') return `Hôte Zabbix ${hostname} hors du groupe OSIRIS : laissé intact.`
  return `Machine supprimée, mais Zabbix n'a pas suivi : ${r.replace(/^echec:\s*/, '')}. À faire à la main dans Zabbix (Data collection › Hosts).`
}
