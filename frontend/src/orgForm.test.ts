// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { brouillonDe, changementsOrg, slugDepuisNom } from './orgForm'
import type { Organization } from './types'

const acme: Organization = {
  id: 1, name: 'Acme', slug: 'acme', webhook_url: '', zabbix_server: '192.0.2.130',
  mac_prefix: '', has_bios_password: true,
}

describe('slugDepuisNom', () => {
  it('retire accents, espaces et ponctuation', () => {
    expect(slugDepuisNom('Plénitude & Co')).toBe('plenitude-co')
    expect(slugDepuisNom("Human's Connexion")).toBe('human-s-connexion')
    expect(slugDepuisNom('  Midi 2i  ')).toBe('midi-2i')
  })
})

describe('changementsOrg', () => {
  it("n'envoie rien quand rien n'a changé — le BIOS vide compris", () => {
    expect(changementsOrg(acme, brouillonDe(acme))).toEqual({})
  })

  // Dérivé du brouillon lui-même : un champ ajouté à la fiche mais oublié dans
  // le calcul du PATCH serait modifiable à l'écran et jamais enregistré.
  it('envoie chaque champ modifiable qui a changé', () => {
    const b = brouillonDe(acme)
    for (const k of Object.keys(b) as (keyof typeof b)[]) {
      const modifie = { ...b, [k]: 'nouvelle-valeur' }
      expect(Object.keys(changementsOrg(acme, modifie))).toEqual([k])
    }
  })

  it("n'efface pas un collecteur en enregistrant un autre champ", () => {
    expect(changementsOrg(acme, { ...brouillonDe(acme), webhook_url: 'https://hook.test' }))
      .toEqual({ webhook_url: 'https://hook.test' })
  })

  it('ignore les espaces autour de la saisie', () => {
    expect(changementsOrg(acme, { ...brouillonDe(acme), zabbix_server: ' 192.0.2.130 ' })).toEqual({})
  })
})
