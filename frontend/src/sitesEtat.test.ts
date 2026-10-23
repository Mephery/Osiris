// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { depuis, ligneConf, presentationEtat, taille } from './sitesEtat'
import type { CodeEtatSite } from './types'

describe('presentationEtat', () => {
  it('chaque état du serveur a une étiquette', () => {
    const codes: CodeEtatSite[] = ['jamais', 'inachevee', 'echec', 'en_retard', 'images_differentes', 'a_jour']
    for (const c of codes) expect(presentationEtat(c).libelle).toBeTruthy()
  })
  it("un site neuf n'est pas affiché comme une panne", () => {
    expect(presentationEtat('jamais').classe).not.toMatch(/red|amber/)
  })
  it("une copie coupée par la fenêtre de nuit n'est pas rouge : elle reprend seule", () => {
    expect(presentationEtat('inachevee').classe).not.toMatch(/red/)
  })
  it('un écart d’images est une alerte, pas un simple retard', () => {
    expect(presentationEtat('images_differentes').classe).toMatch(/red/)
  })
})

describe('depuis', () => {
  const maintenant = new Date('2026-10-23T12:00:00Z')
  it('dit le retard en clair', () => {
    expect(depuis(null, maintenant)).toBe('jamais')
    expect(depuis('2026-10-23T11:59:30Z', maintenant)).toBe("à l'instant")
    expect(depuis('2026-10-23T11:15:00Z', maintenant)).toBe('il y a 45 min')
    expect(depuis('2026-10-23T02:00:00+00:00', maintenant)).toBe('il y a 10 h')
    expect(depuis('2026-10-20T12:00:00Z', maintenant)).toBe('il y a 3 j')
  })
})

describe('taille', () => {
  it('choisit une unité lisible', () => {
    expect(taille(883)).toBe('883 o')
    expect(taille(863_096_248)).toBe('823 Mo')
    expect(taille(1_500_000_000)).toBe('1,4 Go')
  })
})

describe('ligneConf', () => {
  it('donne la ligne exacte de cache.conf', () => {
    expect(ligneConf('abc')).toBe('SITE_JETON=abc')
  })
})
