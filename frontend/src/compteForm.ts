// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
// Compte d'une personne précise sur UNE VM Linux, côté formulaire. Mêmes règles
// que `backend/comptes.py` : le serveur a le dernier mot, mais une clé tronquée
// se signale à la saisie, pas en 422 après le récapitulatif.

export interface CompteForm { nom: string; cle_ssh: string; sudo: boolean }

export const COMPTE_VIDE: CompteForm = { nom: '', cle_ssh: '', sudo: false }

const NOM_RE = /^[a-z_][a-z0-9_-]{0,31}$/
const RESERVES = new Set(['root', 'daemon', 'bin', 'sys', 'sync', 'games', 'man', 'lp', 'mail', 'news',
  'uucp', 'proxy', 'www-data', 'backup', 'list', 'irc', 'gnats', 'nobody', '_apt', 'messagebus', 'sshd',
  'zabbix', 'polkitd', 'syslog', 'uuidd', 'tcpdump', 'tss', 'landscape', 'fwupd-refresh', 'usbmux', 'dnsmasq'])
const TYPES_CLE = new Set(['ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384',
  'ecdsa-sha2-nistp521', 'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com'])

export const compteSaisi = (c: CompteForm) => Boolean(c.nom.trim() || c.cle_ssh.trim())

/** Une clé recollée : les retours à la ligne d'un copier-coller deviennent des espaces. */
export const cleRecollee = (cle: string) => cle.split(/\s+/).filter(Boolean).join(' ')

/** Le type inscrit DANS la clé si elle se lit entière (champs longueur + contenu
 *  jusqu'au dernier octet), « » sinon — même contrôle que le serveur. */
export const typeEncode = (corps: string): string => {
  let brut: string
  try { brut = atob(corps) } catch { return '' }
  const champs: string[] = []
  let i = 0
  while (i < brut.length) {
    if (i + 4 > brut.length) return ''
    const longueur = ((brut.charCodeAt(i) << 24) | (brut.charCodeAt(i + 1) << 16)
      | (brut.charCodeAt(i + 2) << 8) | brut.charCodeAt(i + 3)) >>> 0
    if (i + 4 + longueur > brut.length) return ''
    champs.push(brut.slice(i + 4, i + 4 + longueur))
    i += 4 + longueur
  }
  return champs.length >= 2 ? champs[0] : ''
}

/** Ce qui ne va pas, dans les mots du serveur ; vide si rien n'est saisi. */
export const erreurCompte = (c: CompteForm, utilisateurProfil = ''): string => {
  if (!compteSaisi(c)) return ''
  const nom = c.nom.trim()
  const [type, corps] = cleRecollee(c.cle_ssh).split(' ')
  return !NOM_RE.test(nom) ? `le nom « ${nom} » doit commencer par une minuscule et ne contenir que des minuscules, chiffres, - et _`
    : RESERVES.has(nom) || nom.startsWith('systemd-') ? `« ${nom} » est un compte du système : choisir un autre nom`
    : nom === utilisateurProfil.trim() ? `« ${nom} » est déjà le compte d'administration du profil`
    : !c.cle_ssh.trim() ? 'la clé SSH est obligatoire : sans elle, personne ne pourrait se connecter'
    : !TYPES_CLE.has(type) || !corps ? 'la clé SSH doit commencer par son type (ssh-ed25519, ssh-rsa, ecdsa-…)'
    : typeEncode(corps) !== type ? 'la clé SSH semble tronquée ou altérée : la recopier entièrement depuis le fichier .pub'
    : ''
}

/** Ce qui part au serveur : null quand rien n'est saisi. */
export const comptePourServeur = (c: CompteForm | undefined) =>
  c && compteSaisi(c) ? { nom: c.nom.trim(), cle_ssh: cleRecollee(c.cle_ssh), sudo: c.sudo } : null

/** Une ligne lisible pour le récapitulatif. */
export const decrireCompte = (c: { nom: string; cle_ssh: string; sudo: boolean } | null) => {
  if (!c) return 'Pas de compte en plus de celui du profil'
  const [type, , ...commentaire] = c.cle_ssh.split(' ')
  return `Compte ${c.nom} : clé ${type}${commentaire.length ? ` (${commentaire.join(' ')})` : ''} · ${c.sudo ? 'administrateur (sudo)' : 'sans sudo'}`
}
