// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { buildCreateVmPayload, completerPrefixeCidr, dansLeReseau, imageDuProfilIgnoree, adressageFixeImpossible, profilParDefaut, profilsPourVm, avecProfil, modeParDefaut, champsManquants, gabaritsPourMode, gabaritParDefaut, FORMULAIRE_VIDE, recapVm, etapesVm, reseauxPourVm, stockageParDefaut, adressesPrises, occupantDe, type ChargeVm, type ContexteRecap } from './vmForm'

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

describe('profilParDefaut', () => {
  // Même règle que _resolve_profile côté serveur : le plus ancien de l'OS.
  // L'écran l'annonce par son nom — il doit désigner celui qui sera réellement pris.
  const profils = [
    { id: 7, os: 'ubuntu' },
    { id: 3, os: 'debian' },
    { id: 2, os: 'ubuntu' },
    { id: 9, os: 'ubuntu' },
  ]

  it("prend le plus petit identifiant de l'OS, quel que soit l'ordre reçu", () => {
    expect(profilParDefaut(profils, 'ubuntu')?.id).toBe(2)
  })

  it("ignore les profils d'un autre OS", () => {
    expect(profilParDefaut(profils, 'debian')?.id).toBe(3)
  })

  it("ne désigne rien quand l'OS n'a aucun profil", () => {
    expect(profilParDefaut(profils, 'windows')).toBeUndefined()
  })
})

describe('profilsPourVm', () => {
  const sans = { alerte: 'Aucun accès prévu pour une VM' }
  const avec = { alerte: '' }
  const profils = [
    { id: 13, os: 'ubuntu', resume: avec },
    { id: 1, os: 'ubuntu', resume: sans },
    { id: 4, os: 'ubuntu', resume: sans },
    { id: 14, os: 'debian', resume: avec },
  ]

  it("met à part les profils sans accès, quel que soit leur nom ou leur rang", () => {
    const { utilisables, inutilisables } = profilsPourVm(profils, 'ubuntu')
    expect(utilisables.map(p => p.id)).toEqual([13])
    expect(inutilisables.map(p => p.id)).toEqual([1, 4])
  })

  it("le premier utilisable est celui qu'on présélectionne — jamais un profil sans accès", () => {
    // Le cas du piège : le plus ancien profil Ubuntu (1) est celui sans accès
    expect(profilsPourVm(profils, 'ubuntu').utilisables[0]?.id).toBe(13)
  })

  it("ne propose rien quand aucun profil de l'OS ne donne accès", () => {
    expect(profilsPourVm(profils.filter(p => p.id !== 14), 'debian').utilisables).toEqual([])
  })
})

describe('avecProfil', () => {
  const form = { profile_id: '', vcpus: 2, ram_mb: 2048, disk_gb: 20, data_disk_gb: 0, hostname: 'srv' }

  it('reprend le gabarit matériel du profil et garde le reste du formulaire', () => {
    const f = avecProfil(form, { id: 13, vm_vcpus: 4, vm_ram_mb: 8192, vm_disk_gb: 60, vm_data_disk_gb: 10 })
    expect(f).toEqual({ profile_id: '13', vcpus: 4, ram_mb: 8192, disk_gb: 60, data_disk_gb: 10, hostname: 'srv' })
  })

  it("sans profil, vide la sélection plutôt que d'en garder une d'un autre OS", () => {
    expect(avecProfil({ ...form, profile_id: '13' }, undefined).profile_id).toBe('')
  })
})

describe('modeParDefaut', () => {
  it('clone le gabarit sur vSphere, Linux comme Windows', () => {
    expect(modeParDefaut('vsphere', 'ubuntu')).toBe('template')
    expect(modeParDefaut('vsphere', 'windows')).toBe('template')
  })

  it("passe par cloud-init pour Linux sur Proxmox : c'est le seul canal qui y porte une adresse", () => {
    expect(modeParDefaut('proxmox', 'debian')).toBe('cloudinit')
  })

  it('garde WinPE pour Windows sur Proxmox, et ne propose jamais cloud-init à Windows', () => {
    expect(modeParDefaut('proxmox', 'windows')).toBe('pxe')
    for (const hv of ['proxmox', 'vsphere', undefined]) expect(modeParDefaut(hv, 'windows')).not.toBe('cloudinit')
  })
})

describe('champsManquants', () => {
  const complet = { hostname: 'srv', client: 'Acme', boot_mode: 'template', template_id: '9003', storage: 'ds1', bridge: 'vlan' }

  it('ne réclame rien quand tout est rempli', () => {
    expect(champsManquants(complet, true, 'Clus01')).toEqual([])
  })

  it("nomme ce qui manque, dans l'ordre de l'écran", () => {
    expect(champsManquants({ ...complet, bridge: '', storage: '' }, true, 'Clus01')).toEqual(['stockage', 'réseau'])
  })

  it("ne réclame pas de nœud tant qu'aucun hyperviseur n'est choisi", () => {
    expect(champsManquants(complet, false, '')).toEqual(['hyperviseur'])
  })

  it("ne réclame pas de gabarit en PXE, qui n'en clone aucun", () => {
    expect(champsManquants({ ...complet, boot_mode: 'pxe', template_id: '' }, true, 'n')).toEqual([])
  })
})

describe('gabaritsPourMode', () => {
  const modeles = [
    { vmid: 1, osiris: { os: 'linux' } },
    { vmid: 2, osiris: null },                 // modèle d'un collègue, sans agent
    { vmid: 3, osiris: { os: 'windows' } },
    { vmid: 4, osiris: { os: '' } },           // marqué à la main, système inconnu
    { vmid: 5 },                               // réponse d'un ancien serveur
  ]

  it("en clone nu, ne propose que les gabarits OSIRIS du bon système — le reste est grisé", () => {
    const g = gabaritsPourMode(modeles, 'template', 'debian')
    expect(g.proposes.map(m => m.vmid)).toEqual([1, 4])
    expect(g.autres.map(m => m.vmid)).toEqual([2, 3, 5])
    expect(g.autresChoisissables).toBe(false)
  })

  it("un gabarit marqué à la main se trie sur le système déclaré à l'hyperviseur", () => {
    // Vu le 18/09 : un gabarit Windows marqué à la main se proposait sous Debian
    const marques = [{ vmid: 7, famille: 'windows', osiris: { os: '' } }, { vmid: 8, famille: 'linux', osiris: { os: '' } }]
    expect(gabaritsPourMode(marques, 'template', 'debian').proposes.map(m => m.vmid)).toEqual([8])
  })

  it('un gabarit Windows ne se propose pas sous un profil Linux, et inversement', () => {
    expect(gabaritsPourMode(modeles, 'template', 'windows').proposes.map(m => m.vmid)).toEqual([3, 4])
  })

  it("en cloud-init, qui n'a pas besoin de l'agent, tout reste choisissable", () => {
    expect(gabaritsPourMode(modeles, 'cloudinit', 'ubuntu').autresChoisissables).toBe(true)
  })
})

describe('distribution des gabarits', () => {
  // Ce que montrait Nova le 25/09 : Ubuntu choisi, Debian proposé à égalité
  const nova = [
    { vmid: 9003, name: 'ubuntu-24.04-osiris-v3', famille: 'linux', distribution: 'ubuntu', osiris: { os: '', etat: 'inconnu' } },
    { vmid: 9005, name: 'debian-12-osiris', famille: 'linux', distribution: 'debian', osiris: { os: 'linux', etat: 'a_jour' } },
  ]

  it("ne propose pas un gabarit Debian quand on a choisi Ubuntu", () => {
    const g = gabaritsPourMode(nova, 'cloudinit', 'ubuntu')
    expect(g.proposes.map(m => m.vmid)).toEqual([9003])
    expect(g.autres.map(m => m.vmid)).toEqual([9005])
  })

  it('présélectionne le gabarit de la distribution choisie', () => {
    expect(gabaritParDefaut(nova, 'cloudinit', 'ubuntu')).toBe('9003')
    expect(gabaritParDefaut(nova, 'cloudinit', 'debian')).toBe('9005')
  })

  it("entre deux gabarits de la distribution, l'agent à jour puis la version la plus récente", () => {
    const vcenter = [
      { vmid: 1, name: 'osiris-ubuntu-24.04-v2', distribution: 'ubuntu', osiris: { os: 'linux', etat: 'perime' } },
      { vmid: 2, name: 'osiris-ubuntu-24.04-v9', distribution: 'ubuntu', osiris: { os: 'linux', etat: 'a_jour' } },
      { vmid: 3, name: 'osiris-ubuntu-24.04-v10', distribution: 'ubuntu', osiris: { os: 'linux', etat: 'a_jour' } },
    ]
    expect(gabaritParDefaut(vcenter, 'template', 'ubuntu')).toBe('3')
  })

  it("une distribution inconnue reste proposée mais n'est jamais présélectionnée", () => {
    const flou = [{ vmid: 4, name: 'linux-generique', famille: 'linux', distribution: '', osiris: { os: 'linux', etat: 'a_jour' } }]
    expect(gabaritsPourMode(flou, 'template', 'ubuntu').proposes.map(m => m.vmid)).toEqual([4])
    expect(gabaritParDefaut(flou, 'template', 'ubuntu')).toBe('')
  })

  it('ne présélectionne rien en PXE, qui ne clone rien', () => {
    expect(gabaritParDefaut([], 'pxe', 'ubuntu')).toBe('')
  })
})

describe('recapVm', () => {
  const ctx: ContexteRecap = { hyperviseur: 'Cluster A', dossiers: false }
  const champsMontres = (c: ChargeVm, x: ContexteRecap = ctx) =>
    new Set(recapVm(c, x).flatMap(s => s.lignes.flatMap(l => l.champs)))

  // L'invariant qui fait du récapitulatif autre chose qu'un décor : tout champ
  // rempli envoyé au serveur y est montré (un champ vide ET sans objet, comme le
  // dossier sur Proxmox, peut se taire). Dérivé du formulaire lui-même, jamais d'une
  // liste : un champ ajouté demain au formulaire fait échouer ce test tant que
  // le récapitulatif ne le montre pas.
  it.each(['template', 'cloudinit', 'pxe'] as const)('montre chaque champ envoyé (mode %s)', mode => {
    const rempli = Object.fromEntries(Object.entries(FORMULAIRE_VIDE).map(([k, v]) =>
      [k, typeof v === 'number' ? 3 : k === 'organization_id' ? 1 : k === 'template_id' || k === 'profile_id' ? '9' : 'x'])) as unknown as typeof FORMULAIRE_VIDE
    const charge = buildCreateVmPayload({ ...rempli, boot_mode: mode }, 'n1')
    const manquants = Object.keys(charge).filter(k => !champsMontres(charge).has(k as keyof ChargeVm))
    expect(manquants).toEqual([])
  })

  const texte = (c: ChargeVm, x: ContexteRecap = ctx) =>
    recapVm(c, x).flatMap(s => s.lignes.map(l => l.texte)).join('\n')

  it('dit « DHCP » plutôt que de taire une adresse vide', () => {
    expect(texte(buildCreateVmPayload(FORMULAIRE_VIDE, 'n1'))).toMatch(/DHCP/)
  })

  it('signale une VM sans organisation, donc sans supervision', () => {
    const l = recapVm(buildCreateVmPayload(FORMULAIRE_VIDE, 'n1'), ctx)[0].lignes
      .find(l => l.champs.includes('organization_id'))
    expect(l?.attention).toBe(true)
  })

  it('nomme le gabarit et le réseau plutôt que leurs identifiants', () => {
    const c = buildCreateVmPayload({ ...FORMULAIRE_VIDE, template_id: '9005', bridge: 'vmbr320' }, 'n1')
    const t = texte(c, { ...ctx, gabarit: 'debian-12-osiris', reseau: 'vmbr320 — Clients' })
    expect(t).toContain('« debian-12-osiris »')
    expect(t).toContain('vmbr320 — Clients')
  })

  it('ne parle de dossier que sur un hyperviseur qui en a', () => {
    const c = buildCreateVmPayload(FORMULAIRE_VIDE, 'n1')
    expect(texte(c)).not.toMatch(/Dossier/)
    expect(texte(c, { ...ctx, dossiers: true })).toMatch(/Dossier racine du datacenter/)
  })
})

describe('etapesVm', () => {
  it('annonce une durée dans chaque mode', () => {
    for (const boot_mode of ['template', 'cloudinit', 'pxe'] as const) {
      expect(etapesVm({ boot_mode, os: 'debian', node: 'n1' }).join(' ')).toMatch(/environ/)
    }
  })

  it('parle de WinPE pour un Windows en PXE', () => {
    expect(etapesVm({ boot_mode: 'pxe', os: 'windows', node: 'n1' })[0]).toMatch(/WinPE/)
  })
})

describe('reseauxPourVm', () => {
  const reseaux = [
    { iface: 'vmbr320', reserve: '' },
    { iface: 'vmbr13', reserve: 'hyperviseur' },
    { iface: 'vmbr150', reserve: 'pxe' },
  ]

  it("propose les réseaux de machines et range les autres derrière la case", () => {
    const r = reseauxPourVm(reseaux, false, '')
    expect(r.proposes.map(n => n.iface)).toEqual(['vmbr320'])
    expect(r.reserves).toEqual([])
    expect(r.masques).toBe(2)
  })

  it('montre tout quand la case est cochée', () => {
    const r = reseauxPourVm(reseaux, true, '')
    expect(r.reserves.map(n => n.iface)).toEqual(['vmbr13', 'vmbr150'])
    expect(r.masques).toBe(0)
  })

  // Décocher la case après avoir choisi vmbr13 ne doit pas laisser une
  // sélection que la liste ne montre plus.
  it('garde visible le réseau réservé déjà choisi', () => {
    const r = reseauxPourVm(reseaux, false, 'vmbr13')
    expect(r.reserves.map(n => n.iface)).toEqual(['vmbr13'])
    expect(r.masques).toBe(1)
  })
})

describe('stockageParDefaut', () => {
  it('préfère un stockage partagé, même moins spacieux qu\'un local', () => {
    expect(stockageParDefaut([
      { storage: 'local-btrfs', avail_gb: 430, shared: false },
      { storage: 'ceph', avail_gb: 100, shared: true },
    ])).toBe('ceph')
  })

  it('entre deux partagés, prend le plus spacieux', () => {
    expect(stockageParDefaut([
      { storage: 'vol01', avail_gb: 1600, shared: true },
      { storage: 'vol02', avail_gb: 2400, shared: true },
    ])).toBe('vol02')
  })

  it('ne choisit pas un disque local à la place de l\'opérateur', () => {
    expect(stockageParDefaut([
      { storage: 'local-a', avail_gb: 100, shared: false },
      { storage: 'local-b', avail_gb: 200, shared: false },
    ])).toBe('')
  })

  it('prend le seul stockage quand il n\'y a rien à décider', () => {
    expect(stockageParDefaut([{ storage: 'local', avail_gb: 100, shared: false }])).toBe('local')
  })
})

describe('adresses déjà prises', () => {
  const usage = {
    adresses: [
      { ip: '192.0.2.10', vm: 'web-01', source: 'agent' },
      { ip: '192.0.2.9', vm: 'dns-01', source: 'configuration' },
    ],
    sans_adresse: ['muette'],
  }

  it("réunit l'hyperviseur et les fiches OSIRIS, sans doublon, dans l'ordre des adresses", () => {
    expect(adressesPrises(usage, ['192.0.2.10', '192.0.2.241'])).toEqual([
      { ip: '192.0.2.9', vm: 'dns-01' },
      { ip: '192.0.2.10', vm: 'web-01' },
      { ip: '192.0.2.241', vm: 'fiche OSIRIS' },
    ])
  })

  it("garde les fiches OSIRIS quand l'hyperviseur n'a pas répondu", () => {
    expect(adressesPrises(null, ['192.0.2.241'])).toEqual([{ ip: '192.0.2.241', vm: 'fiche OSIRIS' }])
  })

  it("nomme la VM qui occupe l'adresse saisie", () => {
    const prises = adressesPrises(usage, [])
    expect(occupantDe('192.0.2.10', prises)).toBe('web-01')
    expect(occupantDe('192.0.2.11', prises)).toBeNull()
    expect(occupantDe('', prises)).toBeNull()
  })
})
