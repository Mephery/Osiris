// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { COMPTE_VIDE, cleRecollee, comptePourServeur, decrireCompte, erreurCompte, typeEncode } from './compteForm'
import { buildCreateVmPayload, FORMULAIRE_VIDE } from './vmForm'

// Clé publique de test, générée par ssh-keygen (la clé privée n'a pas été gardée)
const CLE = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICXppthYpwxp0QIWcNdqXHfxn5W7eTIzryQ0nUoXyfUS jdupont@poste'
const compte = (c = {}) => ({ nom: 'jdupont', cle_ssh: CLE, sudo: false, ...c })

describe('typeEncode', () => {
  it('lit le type inscrit dans une vraie clé', () => {
    expect(typeEncode(CLE.split(' ')[1])).toBe('ssh-ed25519')
  })

  it("repère une clé tronquée, même sur un multiple de 4 caractères", () => {
    const corps = CLE.split(' ')[1]
    expect(typeEncode(corps.slice(0, 40))).toBe('')
    expect(typeEncode('pas du base64 !')).toBe('')
  })
})

describe('erreurCompte', () => {
  it('ne dit rien quand rien n\'est saisi, ni sur un compte correct', () => {
    expect(erreurCompte(COMPTE_VIDE)).toBe('')
    expect(erreurCompte(compte())).toBe('')
  })

  it.each([
    [{ nom: 'root' }, '', /compte du système/],
    [{ nom: 'humans' }, 'humans', /administration du profil/],
    [{ cle_ssh: '' }, '', /obligatoire/],
    [{ cle_ssh: 'AAAA jdupont' }, '', /son type/],
    [{ cle_ssh: CLE.slice(0, 60) }, '', /tronquée/],
    [{ nom: '1jdupont' }, '', /minuscule/],
  ])('%o → %s', (c, profil, attendu) => {
    expect(erreurCompte(compte(c), profil as string)).toMatch(attendu)
  })

  it('accepte une clé collée sur plusieurs lignes', () => {
    expect(erreurCompte(compte({ cle_ssh: CLE.replace(/ /g, '\n') }))).toBe('')
    expect(cleRecollee(CLE.replace(/ /g, '\n'))).toBe(CLE)
  })
})

describe('le compte dans la charge envoyée', () => {
  it('null quand rien n\'est saisi, et jamais sous Windows', () => {
    expect(comptePourServeur(COMPTE_VIDE)).toBeNull()
    expect(buildCreateVmPayload({ ...FORMULAIRE_VIDE, os: 'windows', compte: compte() }, 'n1').compte).toBeNull()
    expect(buildCreateVmPayload({ ...FORMULAIRE_VIDE, os: 'debian', compte: compte({ sudo: true }) }, 'n1').compte)
      .toEqual({ nom: 'jdupont', cle_ssh: CLE, sudo: true })
  })

  it('se relit dans le récapitulatif', () => {
    expect(decrireCompte(comptePourServeur(compte()))).toBe('Compte jdupont : clé ssh-ed25519 (jdupont@poste) · sans sudo')
    expect(decrireCompte(null)).toBe('Pas de compte en plus de celui du profil')
  })
})
