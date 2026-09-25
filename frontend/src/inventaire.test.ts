// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { filtrerInventaire, reseauxInventaire } from './inventaire'
import type { InventaireVm } from './types'

const vm = (nom: string, reseaux: [string, string[]][], osiris = ''): InventaireVm => ({
  vmid: 0, nom, noeud: 'pve1', etat: 'allumee', genre: 'vm', osiris,
  cartes: reseaux.map(([reseau, ips]) => ({ reseau, ips: ips.map(ip => ({ ip, source: 'agent' })) })),
})

const vms = [
  vm('web-01', [['vmbr320', ['192.0.2.10']]]),
  vm('web-02', [['vmbr320', ['192.0.2.11']], ['vmbr12', ['198.51.100.5']]], 'srv-web-02'),
  vm('dc-01', [['vmbr160', ['203.0.113.2']]]),
]

describe('reseauxInventaire', () => {
  it('compte les VM par réseau, le plus peuplé en tête', () => {
    expect(reseauxInventaire(vms)).toEqual([
      { reseau: 'vmbr320', vms: 2 }, { reseau: 'vmbr12', vms: 1 }, { reseau: 'vmbr160', vms: 1 },
    ])
  })

  it('ne compte pas deux fois une VM à deux cartes sur le même réseau', () => {
    expect(reseauxInventaire([vm('double', [['vmbr320', []], ['vmbr320', []]])]))
      .toEqual([{ reseau: 'vmbr320', vms: 1 }])
  })
})

describe('filtrerInventaire', () => {
  it('filtre par réseau', () => {
    expect(filtrerInventaire(vms, 'vmbr320', '').map(v => v.nom)).toEqual(['web-01', 'web-02'])
  })

  it('cherche dans le nom, la fiche OSIRIS et les adresses', () => {
    expect(filtrerInventaire(vms, '', 'DC').map(v => v.nom)).toEqual(['dc-01'])
    expect(filtrerInventaire(vms, '', 'srv-web').map(v => v.nom)).toEqual(['web-02'])
    expect(filtrerInventaire(vms, '', '192.0.2.11').map(v => v.nom)).toEqual(['web-02'])
  })
})
