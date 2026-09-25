// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { disqueData, disquesPourServeur, erreursDisques, libelleDepuisMontage, nouveauDisque } from './disquesForm'
import { avecProfil, buildCreateVmPayload, FORMULAIRE_VIDE } from './vmForm'

describe('libellé proposé', () => {
  // Mêmes cas que backend/tests/test_disques.py : les deux calculs ne doivent pas diverger
  it.each([
    ['/var/lib/mysql', 'mysql'],
    ['/srv/Web.Data', 'web-data'],
    ['/data/', 'data'],
    ['/un-nom-vraiment-trop-long', 'un-nom-vraim'],
  ])('%s → %s', (montage, attendu) => {
    expect(libelleDepuisMontage(montage)).toBe(attendu)
  })
})

describe('nouveauDisque', () => {
  it('propose /data, puis /data2, /data3…', () => {
    const un = nouveauDisque([])
    expect(un.point_montage).toBe('/data')
    expect(nouveauDisque([un]).point_montage).toBe('/data2')
    expect(nouveauDisque([un]).libelle).toBe('data2')
  })
})

describe('erreursDisques', () => {
  it('ne dit rien sur une liste correcte', () => {
    expect(erreursDisques([disqueData(10), nouveauDisque([disqueData(10)])])).toEqual([])
  })

  it('dit quoi corriger, disque par disque', () => {
    expect(erreursDisques([{ ...disqueData(10), point_montage: '/etc' }])[0])
      .toMatch(/Disque 1 : .*répertoire du système/)
    expect(erreursDisques([disqueData(10), disqueData(20)])[0]).toMatch(/Disque 2 : .*déjà utilisé/)
    expect(erreursDisques([{ ...disqueData(10), libelle: 'mon disque' }])[0]).toMatch(/libellé/)
  })
})

describe('les disques dans la charge envoyée', () => {
  it("n'envoie pas l'état propre au formulaire", () => {
    expect(disquesPourServeur([{ ...disqueData(10), libelleTouche: true }])).toEqual([
      { taille_gb: 10, point_montage: '/data', libelle: 'data', lvm: true, systeme_fichiers: 'ext4' }])
  })

  it('Linux envoie la liste, Windows le disque unique', () => {
    const linux = buildCreateVmPayload({ ...FORMULAIRE_VIDE, os: 'debian', disques: [disqueData(10)], data_disk_gb: 10 }, 'n1')
    expect(linux.disques).toHaveLength(1)
    expect(linux.data_disk_gb).toBe(0)
    const windows = buildCreateVmPayload({ ...FORMULAIRE_VIDE, os: 'windows', disques: [disqueData(10)], data_disk_gb: 10 }, 'n1')
    expect(windows.disques).toEqual([])
    expect(windows.data_disk_gb).toBe(10)
  })

  it('le disque de données du profil devient le premier de la liste', () => {
    const f = avecProfil(FORMULAIRE_VIDE, { id: 3, vm_data_disk_gb: 10 })
    expect(f.disques).toEqual([disqueData(10)])
    expect(avecProfil(FORMULAIRE_VIDE, { id: 4, vm_data_disk_gb: 0 }).disques).toEqual([])
  })
})
