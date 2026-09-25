// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Disques supplémentaires d'une VM Linux, côté formulaire. Mêmes règles que
// `backend/disques.py` : le serveur a le dernier mot, mais une erreur se dit
// ici, au moment de la saisie, plutôt qu'en 422 après le récapitulatif.

export interface DisqueForm {
  taille_gb: number
  point_montage: string
  libelle: string
  lvm: boolean
  systeme_fichiers: 'ext4' | 'xfs'
  /** Le libellé suit le point de montage tant qu'on ne l'a pas retouché. */
  libelleTouche?: boolean
}

export const MAX_DISQUES = 4
const LIBELLE_RE = /^[a-z0-9][a-z0-9_-]{0,11}$/
const MONTAGE_RE = /^(\/[a-zA-Z0-9._-]+)+$/
const MONTAGES_INTERDITS = new Set(['/', '/bin', '/boot', '/dev', '/etc', '/lib', '/lib64', '/proc',
  '/run', '/sbin', '/sys', '/tmp', '/usr', '/var', '/root'])

/** « /var/lib/mysql » → « mysql » (même calcul que le serveur). */
export const libelleDepuisMontage = (montage: string): string => {
  const dernier = montage.replace(/\/+$/, '').split('/').pop()?.toLowerCase() ?? ''
  return dernier.replace(/[^a-z0-9_-]/g, '-').replace(/^[-_]+|[-_]+$/g, '').slice(0, 12) || 'data'
}

/** Le disque de données que propose un profil : un /data en LVM et ext4,
 *  exactement ce que produisait l'ancien champ unique. */
export const disqueData = (taille_gb: number): DisqueForm =>
  ({ taille_gb, point_montage: '/data', libelle: 'data', lvm: true, systeme_fichiers: 'ext4' })

/** Un disque de plus : le premier /data, /data2… libre, 10 Go, LVM, ext4. */
export const nouveauDisque = (existants: DisqueForm[]): DisqueForm => {
  const pris = new Set(existants.map(d => d.point_montage))
  let n = 1
  while (pris.has(n === 1 ? '/data' : `/data${n}`)) n++
  const montage = n === 1 ? '/data' : `/data${n}`
  return { taille_gb: 10, point_montage: montage, libelle: libelleDepuisMontage(montage), lvm: true, systeme_fichiers: 'ext4' }
}

/** Ce qui ne va pas dans la liste, disque par disque, dans les mots du serveur. */
export const erreursDisques = (disques: DisqueForm[]): string[] => {
  const erreurs: string[] = []
  const montages = new Set<string>(), libelles = new Set<string>()
  disques.forEach((d, i) => {
    const montage = d.point_montage.trim().replace(/\/+$/, '') || '/'
    const libelle = (d.libelle || libelleDepuisMontage(montage)).trim().toLowerCase()
    const erreur =
      !(d.taille_gb >= 1 && d.taille_gb <= 16384) ? 'sa taille doit être comprise entre 1 et 16384 Go'
      : !MONTAGE_RE.test(montage) ? `le point de montage « ${montage} » doit être un chemin absolu simple (ex : /data)`
      : MONTAGES_INTERDITS.has(montage) ? `« ${montage} » est un répertoire du système : y monter un disque vierge le masquerait`
      : montages.has(montage) ? `« ${montage} » est déjà utilisé par un autre disque`
      : !LIBELLE_RE.test(libelle) ? `le libellé « ${libelle} » doit faire 1 à 12 caractères : minuscules, chiffres, - et _`
      : libelles.has(libelle) ? `le libellé « ${libelle} » est déjà utilisé par un autre disque`
      : ''
    if (erreur) erreurs.push(`Disque ${i + 1} : ${erreur}.`)
    montages.add(montage)
    libelles.add(libelle)
  })
  return erreurs
}

/** Ce qui part au serveur : sans l'état propre au formulaire. */
export const disquesPourServeur = (disques: DisqueForm[]) =>
  disques.map(({ taille_gb, point_montage, libelle, lvm, systeme_fichiers }) =>
    ({ taille_gb, point_montage, libelle, lvm, systeme_fichiers }))

/** Une ligne lisible, pour le récapitulatif. */
export const decrireDisque = (d: { taille_gb: number; point_montage: string; libelle: string; lvm: boolean; systeme_fichiers: string }) =>
  `Disque « ${d.libelle} » : ${d.taille_gb} Go sur ${d.point_montage} · ${d.lvm ? 'LVM' : 'sans LVM'} · ${d.systeme_fichiers}`
