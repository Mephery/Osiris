// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { buildCreateVmPayload, completerPrefixeCidr, dansLeReseau, imageDuProfilIgnoree, adressageFixeImpossible } from './vmForm'

describe('dansLeReseau', () => {
  it('accepte une adresse dans le même /24', () => {
    expect(dansLeReseau('192.168.1.42', '192.168.1.0/24')).toBe(true)
  })

  it('refuse une adresse hors du réseau', () => {
    expect(dansLeReseau('192.168.2.42', '192.168.1.0/24')).toBe(false)
  })

  it('ignore le préfixe déjà présent sur l\'adresse saisie', () => {
    expect(dansLeReseau('192.168.1.42/32', '192.168.1.0/24')).toBe(true)
  })

  it('se tait (null) plutôt que d\'alarmer sur une adresse incomplète', () => {
    expect(dansLeReseau('192.168.1', '192.168.1.0/24')).toBeNull()
  })

  it('se tait (null) sur un réseau qui n\'est pas encore résolu', () => {
    expect(dansLeReseau('192.168.1.42', '')).toBeNull()
  })

  // Piège de bit-shift JS : `-1 << 32` ne redonne pas 0 mais -1 (le décalage boucle
  // modulo 32), donc un masque /0 mal codé accepterait tout SAUF le réseau 0.0.0.0/0
  // lui-même. La garde explicite `Number(prefixe) === 0 ? 0 : ...` est ce qui évite
  // ce piège — ce test échoue si elle disparaît.
  it('un préfixe /0 accepte n\'importe quelle adresse', () => {
    expect(dansLeReseau('8.8.8.8', '0.0.0.0/0')).toBe(true)
  })

  it('un préfixe /32 n\'accepte que l\'adresse exacte', () => {
    expect(dansLeReseau('10.0.0.1', '10.0.0.1/32')).toBe(true)
    expect(dansLeReseau('10.0.0.2', '10.0.0.1/32')).toBe(false)
  })

  it('une frontière de sous-réseau ne déborde pas sur la suivante', () => {
    // 10.0.0.255 est la dernière adresse de 10.0.0.0/24, 10.0.1.0 la première du
    // /24 suivant : une erreur de masque les confondrait facilement.
    expect(dansLeReseau('10.0.0.255', '10.0.0.0/24')).toBe(true)
    expect(dansLeReseau('10.0.1.0', '10.0.0.0/24')).toBe(false)
  })
})

describe('completerPrefixeCidr', () => {
  it('ajoute le préfixe du réseau à une adresse nue', () => {
    expect(completerPrefixeCidr('192.168.1.42', 24)).toBe('192.168.1.42/24')
  })

  it('ne touche pas à une adresse qui a déjà un préfixe', () => {
    expect(completerPrefixeCidr('192.168.1.42/28', 24)).toBe('192.168.1.42/28')
  })

  it('ne touche pas à un champ vide', () => {
    expect(completerPrefixeCidr('', 24)).toBe('')
  })

  it('laisse l\'adresse inchangée si le préfixe du réseau est inconnu', () => {
    expect(completerPrefixeCidr('192.168.1.42', undefined)).toBe('192.168.1.42')
  })

  it('coupe les espaces superflus autour de l\'adresse', () => {
    expect(completerPrefixeCidr('  192.168.1.42  ', 24)).toBe('192.168.1.42/24')
  })
})

describe('buildCreateVmPayload', () => {
  // profile_id/template_id restent la chaîne brute du <select> tant qu'ils ne sont
  // pas choisis ; organization_id, lui, est déjà `number | ''` dans l'état du
  // formulaire (son onChange convertit à la saisie) — les deux formes se croisent
  // ici pour refléter fidèlement ce que le composant construit réellement.
  const base = {
    hostname: 'srv-test', os: 'ubuntu', profile_id: '', template_id: '',
    organization_id: '' as number | '', boot_mode: 'pxe',
  }

  it('convertit les identifiants vides en null plutôt qu\'en NaN', () => {
    // Number('') vaut 0, pas NaN : sans la garde explicite sur '', un profil ou
    // une organisation "aucun choix" partirait comme profile_id=0, un id valide
    // pour une autre fiche.
    const payload = buildCreateVmPayload(base, 'pve-node1')
    expect(payload.profile_id).toBeNull()
    expect(payload.template_id).toBeNull()
    expect(payload.organization_id).toBeNull()
  })

  it('convertit les identifiants renseignés en nombres', () => {
    const payload = buildCreateVmPayload(
      { ...base, profile_id: '3', template_id: '107', organization_id: 2 },
      'pve-node1',
    )
    expect(payload.profile_id).toBe(3)
    expect(payload.template_id).toBe(107)
    expect(payload.organization_id).toBe(2)
  })

  it('porte le noeud choisi séparément du reste du formulaire', () => {
    const payload = buildCreateVmPayload(base, 'pve-node2')
    expect(payload.node).toBe('pve-node2')
  })

  it('conserve les autres champs du formulaire tels quels', () => {
    const payload = buildCreateVmPayload(base, 'pve-node1')
    expect(payload.hostname).toBe('srv-test')
    expect(payload.os).toBe('ubuntu')
    expect(payload.boot_mode).toBe('pxe')
  })
})

describe('imageDuProfilIgnoree', () => {
  const profil2025 = { win_image: 'server2025.wim' }

  it("signale l'image du profil quand on clone un gabarit", () => {
    // Le cas du 25/08 : gabarit Windows Server 2022, profil nommé « 2025 ».
    expect(imageDuProfilIgnoree('template', profil2025)).toBe(true)
    expect(imageDuProfilIgnoree('cloudinit', profil2025)).toBe(true)
  })

  it('se tait en PXE, seul mode où le profil décide vraiment de l\'image', () => {
    expect(imageDuProfilIgnoree('pxe', profil2025)).toBe(false)
  })

  it("se tait quand le profil ne déclare aucune image", () => {
    // Rien à contredire : le gabarit est la seule source d'OS, et personne
    // n'a prétendu le contraire. Avertir ici ne ferait qu'user l'avertissement.
    expect(imageDuProfilIgnoree('template', { win_image: '' })).toBe(false)
    expect(imageDuProfilIgnoree('template', undefined)).toBe(false)
  })
})

describe('adressageFixeImpossible', () => {
  it('refuse le clone nu Proxmox : rien dans la VM ne lirait l\'adresse', () => {
    expect(adressageFixeImpossible('proxmox', 'template')).toBe(true)
  })

  it('accepte le clone nu vSphere : guestinfo porte l\'adresse', () => {
    expect(adressageFixeImpossible('vsphere', 'template')).toBe(false)
  })

  it('accepte cloud-init et PXE partout', () => {
    for (const t of ['proxmox', 'vsphere']) {
      expect(adressageFixeImpossible(t, 'cloudinit')).toBe(false)
      expect(adressageFixeImpossible(t, 'pxe')).toBe(false)
    }
  })

  it('traite un type inconnu comme du Proxmox', () => {
    // Le défaut historique du champ `type` : mieux vaut refuser à tort et le
    // dire que laisser passer une adresse qui sera perdue en silence.
    expect(adressageFixeImpossible(undefined, 'template')).toBe(true)
  })
})
