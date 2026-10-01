// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import {
  schemaPartition, erreursSysteme, decrireTranche,
  ROOT_GB_DEFAUT, SWAP_GB_DEFAUT, BOOT_GB,
} from './partitionForm'

// Mêmes cas que backend/tests/test_partition_schema.py : les deux calculs ne
// doivent pas diverger (ce que l'opérateur voit = ce que le serveur provisionne).

const parMontage = (s: ReturnType<typeof schemaPartition>) =>
  Object.fromEntries(s.tranches.map(t => [t.montage, t]))

describe('schemaPartition', () => {
  it('UEFI par défaut : EFI + /boot + swap + / , total arrondi au Go', () => {
    const s = schemaPartition()
    const m = parMontage(s)
    expect(Object.keys(m).sort()).toEqual(['/', '/boot', '/boot/efi', 'swap'])
    expect(m['/'].taille_gb).toBe(ROOT_GB_DEFAUT)      // 200
    expect(m['swap'].taille_gb).toBe(SWAP_GB_DEFAUT)   // 2
    expect(m['/boot'].taille_gb).toBe(BOOT_GB)         // 1
    expect(s.total_gb).toBe(204)                       // 0,5 + 1 + 2 + 200 = 203,5 -> 204
    expect(s.vg).toBe('osiris')
  })

  it('EFI et /boot sont des partitions, le reste en LVM', () => {
    const m = parMontage(schemaPartition())
    expect(m['/boot/efi'].type).toBe('partition')
    expect(m['/boot'].type).toBe('partition')
    expect(m['swap'].type).toBe('lvm')
    expect(m['/'].type).toBe('lvm')
  })

  it('BIOS : pas d\'EFI', () => {
    const s = schemaPartition(ROOT_GB_DEFAUT, SWAP_GB_DEFAUT, [], false)
    expect(parMontage(s)['/boot/efi']).toBeUndefined()
    expect(s.total_gb).toBe(203)                       // 1 + 2 + 200
  })

  it('les extras sont des LV et comptent dans le total', () => {
    const extras = [
      { libelle: 'home', point_montage: '/home', taille_gb: 50, systeme_fichiers: 'ext4' as const },
      { libelle: 'pg', point_montage: '/var/lib/postgresql', taille_gb: 80, systeme_fichiers: 'ext4' as const },
    ]
    const s = schemaPartition(30, 2, extras)
    const m = parMontage(s)
    expect(m['/home'].type).toBe('lvm')
    expect(m['/var/lib/postgresql'].type).toBe('lvm')
    expect(s.total_gb).toBe(164)                       // 0,5 + 1 + 2 + 30 + 50 + 80 = 163,5 -> 164
  })

  it('tailles personnalisées', () => {
    const s = schemaPartition(100, 4, [], false)
    expect(s.total_gb).toBe(105)                       // 1 + 4 + 100
  })
})

describe('erreursSysteme', () => {
  it('refuse un / trop petit', () => {
    expect(erreursSysteme(5, 2)).toHaveLength(1)
  })
  it('refuse un swap hors bornes', () => {
    expect(erreursSysteme(200, 0)).toHaveLength(1)
    expect(erreursSysteme(200, 9999)).toHaveLength(1)
  })
  it('laisse passer un système valide', () => {
    expect(erreursSysteme(200, 2)).toHaveLength(0)
  })
})

describe('decrireTranche', () => {
  it('affiche les Mo sous 1 Go (EFI) et « swap » pour le swap', () => {
    const efi = schemaPartition().tranches.find(t => t.montage === '/boot/efi')!
    expect(decrireTranche(efi)).toContain('512 Mo')
    const swap = schemaPartition().tranches.find(t => t.montage === 'swap')!
    expect(decrireTranche(swap)).toContain('swap')
  })
})
