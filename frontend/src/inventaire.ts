// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Logique pure de l'écran Inventaire, testable sans monter de composant.
import type { InventaireVm } from './types'

/** Les réseaux présents dans l'inventaire, avec leur nombre de VM, par ordre
 *  d'usage décroissant : celui qu'on cherche est le plus souvent en tête. */
export const reseauxInventaire = (vms: InventaireVm[]): { reseau: string; vms: number }[] => {
  const compte = new Map<string, number>()
  for (const vm of vms) {
    for (const r of new Set(vm.cartes.map(c => c.reseau))) compte.set(r, (compte.get(r) ?? 0) + 1)
  }
  return [...compte].map(([reseau, n]) => ({ reseau, vms: n }))
    .sort((a, b) => b.vms - a.vms || a.reseau.localeCompare(b.reseau))
}

/** Les VM d'un réseau (« » = tous) dont le nom, la fiche OSIRIS ou une IP
 *  contient le texte cherché. */
export const filtrerInventaire = (vms: InventaireVm[], reseau: string, texte: string): InventaireVm[] => {
  const t = texte.trim().toLowerCase()
  return vms.filter(vm =>
    (!reseau || vm.cartes.some(c => c.reseau === reseau))
    && (!t || vm.nom.toLowerCase().includes(t) || vm.osiris.toLowerCase().includes(t)
        || vm.cartes.some(c => c.ips.some(a => a.ip.includes(t)))))
}
