// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { authHeader, formatDetails, formatMac } from './types'

describe('formatMac', () => {
  // Découpe aveuglément tous les 2 caractères : ne suppose rien d'autre que ce
  // que garantit `validate_mac` côté backend (12 chiffres hexa, sans séparateur).
  // Son seul appelant (JournalTab) ne lui passe jamais autre chose — une adresse
  // déjà séparée par des ':' ressortirait hachée, mais ce cas ne se présente pas.
  it('insère les deux-points tous les deux caractères', () => {
    expect(formatMac('bc241178a350')).toBe('BC:24:11:78:A3:50')
  })

  it('renvoie l\'entrée telle quelle si elle ne ressemble pas à une MAC', () => {
    expect(formatMac('')).toBe('')
  })
})

describe('formatDetails', () => {
  it('joint les entrées avec « : » et « · »', () => {
    expect(formatDetails({ hostname: 'srv-test', vm_id: 117 })).toBe('hostname: srv-test · vm_id: 117')
  })

  it('renvoie un tiret cadratin pour un détail absent', () => {
    expect(formatDetails(null)).toBe('—')
  })

  it('renvoie une chaîne vide pour un objet vide, pas un tiret', () => {
    // Cas distinct du null : la ligne existe dans le journal mais n'a rien à dire,
    // ce n'est pas la même situation qu'un événement sans détails du tout.
    expect(formatDetails({})).toBe('')
  })
})

describe('authHeader', () => {
  it('construit l\'en-tête Bearer attendu par l\'API', () => {
    expect(authHeader('mon-jeton')).toEqual({ Authorization: 'Bearer mon-jeton' })
  })
})
