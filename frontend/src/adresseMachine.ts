// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
/** L'adresse d'une machine telle que la rend `GET /machines/{mac}/adresse`. */
export interface AdresseMachine {
  ip: string
  ips: string[]
  /** constatee = lue en direct par l'hyperviseur ; remontee = vue par la machine
   *  au premier démarrage ; declaree = saisie à la création ; '' = inconnue. */
  source: '' | 'constatee' | 'remontee' | 'declaree'
  le: string | null
  /** Compte du profil à proposer dans `ssh compte@ip` (Linux seulement). */
  compte: string
}

/** Ce qu'on peut affirmer de l'adresse, en une ligne : d'où on la tient et
 *  jusqu'où s'y fier. Une IP déclarée affichée comme sûre enverrait chercher la
 *  machine là où elle n'est peut-être pas. */
export function provenanceAdresse(a: AdresseMachine): { texte: string; sure: boolean } {
  switch (a.source) {
    case 'constatee':
      return { texte: 'lue en direct sur la VM', sure: true }
    case 'remontee': {
      const quand = a.le
        ? new Date(a.le).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
        : ''
      return { texte: `vue par la machine au déploiement${quand ? ` (${quand})` : ''} — un bail DHCP a pu changer`, sure: false }
    }
    case 'declaree':
      return { texte: 'saisie à la création, non confirmée', sure: false }
    default:
      return { texte: 'inconnue : ni agent invité, ni remontée de la machine', sure: false }
  }
}

/** La commande SSH à copier, ou '' quand il n'y a rien à proposer. */
export function commandeSsh(a: AdresseMachine): string {
  return a.ip && a.compte ? `ssh ${a.compte}@${a.ip}` : ''
}
