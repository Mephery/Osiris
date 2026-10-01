// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Schéma de partition du disque système LVM, côté formulaire. Miroir de
// `backend/disques.py` (schema_partition + valider_systeme) : le serveur a le
// dernier mot, mais l'aperçu se calcule ici, instantanément, à chaque frappe.
// Convention : un disque = [EFI] + /boot + VG « osiris » { swap, /, extras… }.

import type { DisqueForm } from './disquesForm'

export const EFI_MB = 512
export const BOOT_GB = 1
export const VG_NOM = 'osiris'
export const ROOT_GB_DEFAUT = 200
export const SWAP_GB_DEFAUT = 2
export const ROOT_GB_MIN = 10
export const SWAP_GB_MIN = 1

export interface Tranche {
  nom: string
  montage: string
  taille_gb: number
  fs: string
  type: 'partition' | 'lvm'
}

export interface SchemaPartition {
  vg: string
  uefi: boolean
  tranches: Tranche[]
  total_gb: number
}

/** Le schéma complet : les tranches (pour l'aperçu) et la taille totale du disque
 *  à provisionner. Les tailles s'additionnent — c'est cette somme que
 *  l'hyperviseur crée. Mêmes règles d'arrondi que le serveur (au Go supérieur). */
export const schemaPartition = (
  root_gb: number = ROOT_GB_DEFAUT,
  swap_gb: number = SWAP_GB_DEFAUT,
  extras: Pick<DisqueForm, 'libelle' | 'point_montage' | 'taille_gb' | 'systeme_fichiers'>[] = [],
  uefi = true,
): SchemaPartition => {
  const tranches: Tranche[] = []
  if (uefi) tranches.push({ nom: 'EFI', montage: '/boot/efi', taille_gb: EFI_MB / 1024, fs: 'vfat', type: 'partition' })
  tranches.push({ nom: 'boot', montage: '/boot', taille_gb: BOOT_GB, fs: 'ext4', type: 'partition' })
  tranches.push({ nom: 'swap', montage: 'swap', taille_gb: swap_gb, fs: 'swap', type: 'lvm' })
  tranches.push({ nom: 'root', montage: '/', taille_gb: root_gb, fs: 'ext4', type: 'lvm' })
  for (const d of extras) {
    tranches.push({ nom: d.libelle, montage: d.point_montage, taille_gb: d.taille_gb, fs: d.systeme_fichiers, type: 'lvm' })
  }
  const total_gb = Math.ceil(tranches.reduce((a, t) => a + t.taille_gb, 0))
  return { vg: VG_NOM, uefi, tranches, total_gb }
}

/** Ce qui ne va pas sur / et swap, dans les mots du serveur. */
export const erreursSysteme = (root_gb: number, swap_gb: number): string[] => {
  const e: string[] = []
  if (!(root_gb >= ROOT_GB_MIN && root_gb <= 16384))
    e.push(`La taille de / doit être comprise entre ${ROOT_GB_MIN} et 16384 Go.`)
  if (!(swap_gb >= SWAP_GB_MIN && swap_gb <= 256))
    e.push(`La taille du swap doit être comprise entre ${SWAP_GB_MIN} et 256 Go.`)
  return e
}

/** Une tranche, en texte lisible, pour l'aperçu/récapitulatif. */
export const decrireTranche = (t: Tranche): string => {
  const taille = t.taille_gb < 1 ? `${Math.round(t.taille_gb * 1024)} Mo` : `${t.taille_gb} Go`
  const ou = t.montage === 'swap' ? 'swap' : t.montage
  return `${ou} — ${taille} · ${t.type === 'lvm' ? 'LVM' : 'partition'} · ${t.fs}`
}
