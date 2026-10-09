// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { choixEffectif, choixPossible, decrireResultat } from './zabbixRetrait'

describe('choixEffectif', () => {
  it('VM détruite : désactiver par défaut', () => {
    expect(choixEffectif(null, true)).toBe('desactiver')
  })
  it('fiche seule : ne rien changer par défaut', () => {
    expect(choixEffectif(null, false)).toBe('rien')
  })
  it("le choix de l'opérateur l'emporte, VM détruite ou non", () => {
    expect(choixEffectif('supprimer', false)).toBe('supprimer')
    expect(choixEffectif('rien', true)).toBe('rien')
  })
})

describe('choixPossible', () => {
  it("seulement pour un hôte existant DANS le groupe d'OSIRIS", () => {
    expect(choixPossible({ configure: true, existe: true, gere: true })).toBe(true)
    expect(choixPossible({ configure: true, existe: true, gere: false })).toBe(false)
    expect(choixPossible({ configure: true, existe: false })).toBe(false)
    expect(choixPossible({ configure: false })).toBe(false)
    expect(choixPossible(null)).toBe(false)
  })
})

describe('decrireResultat', () => {
  it('se tait quand rien ne change', () => {
    expect(decrireResultat('inchange', 'vm')).toBeNull()
    expect(decrireResultat(undefined, 'vm')).toBeNull()
  })
  it("un échec dit quoi faire, sans laisser croire l'hôte retiré", () => {
    const m = decrireResultat("echec: le rôle Zabbix du jeton OSIRIS n'autorise pas host.delete", 'vm')
    expect(m).toContain("n'a pas suivi")
    expect(m).toContain('host.delete')
    expect(m).not.toContain('echec:')
  })
})
