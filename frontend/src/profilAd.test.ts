// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { compteSaisiDansLeProfil, ficheDuProfil, libelleFiche } from './profilAd'
import type { DomainConfig, Organization } from './types'

const fiche = (champs: Partial<DomainConfig>): DomainConfig => ({
  id: 1, organization_id: 7, name: 'Fiche', domain: 'client.local', join_user: '',
  default_ou: '', wifi_ssid: '', has_wifi_password: false, ...champs,
})
const orgs = [{ id: 7, name: 'Plénitude' }] as Organization[]

describe('ficheDuProfil', () => {
  it('retrouve la fiche liée', () => {
    expect(ficheDuProfil(1, [fiche({})])?.domain).toBe('client.local')
  })

  it('ne rend rien pour un profil sans fiche (null, 0) ou lié à une fiche supprimée', () => {
    expect(ficheDuProfil(null, [fiche({})])).toBeUndefined()
    expect(ficheDuProfil(0, [fiche({})])).toBeUndefined()
    expect(ficheDuProfil(2, [fiche({})])).toBeUndefined()
  })
})

describe('compteSaisiDansLeProfil', () => {
  it('masque le compte quand la fiche porte le sien', () => {
    expect(compteSaisiDansLeProfil(fiche({ join_user: 'svc-join' }))).toBe(false)
  })

  it('garde le compte dans le profil quand la fiche n\'en a pas', () => {
    expect(compteSaisiDansLeProfil(fiche({ join_user: '' }))).toBe(true)
  })

  it('garde le compte dans le profil sans fiche liée', () => {
    expect(compteSaisiDansLeProfil(undefined)).toBe(true)
  })
})

describe('libelleFiche', () => {
  it('nomme l\'organisation puis le domaine, sans répéter un nom identique', () => {
    expect(libelleFiche(fiche({ name: 'Plénitude' }), orgs)).toBe('Plénitude — client.local')
  })

  it('ajoute le nom de la fiche quand il apporte quelque chose', () => {
    expect(libelleFiche(fiche({ name: 'Siège' }), orgs)).toBe('Plénitude — client.local (Siège)')
  })
})
