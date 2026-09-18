// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { correspondDate, correspondProfil, correspondType, raisonATraiter } from './filtresMachines'

const MAINTENANT = new Date('2026-09-18T17:00:00Z').getTime()
const ilY = (minutes: number) => new Date(MAINTENANT - minutes * 60_000).toISOString()

describe('correspondType', () => {
  const pc = { hypervisor_id: null }
  const vm = { hypervisor_id: 5 }
  it('sépare les physiques des VM', () => {
    expect(correspondType(pc, 'physique')).toBe(true)
    expect(correspondType(vm, 'physique')).toBe(false)
    expect(correspondType(vm, 'vm')).toBe(true)
  })
  it("isole les VM d'un hyperviseur", () => {
    expect(correspondType(vm, 'hv:5')).toBe(true)
    expect(correspondType(vm, 'hv:3')).toBe(false)
    expect(correspondType(pc, 'hv:5')).toBe(false)
  })
})

describe('correspondProfil', () => {
  it('trouve les machines sans profil, celles qui tombent sur le repli', () => {
    expect(correspondProfil({ profile_id: null }, 'aucun')).toBe(true)
    expect(correspondProfil({ profile_id: 13 }, 'aucun')).toBe(false)
    expect(correspondProfil({ profile_id: 13 }, '13')).toBe(true)
  })
})

describe('correspondDate', () => {
  it('range par ancienneté du déploiement', () => {
    expect(correspondDate({ deployed_at: ilY(60) }, 'jour', MAINTENANT)).toBe(true)
    expect(correspondDate({ deployed_at: ilY(60 * 24 * 40) }, 'mois', MAINTENANT)).toBe(false)
    expect(correspondDate({ deployed_at: ilY(60 * 24 * 40) }, 'ancien', MAINTENANT)).toBe(true)
  })
  it('« jamais » = aucune date de déploiement', () => {
    expect(correspondDate({ deployed_at: null }, 'jamais', MAINTENANT)).toBe(true)
    expect(correspondDate({ deployed_at: null }, 'semaine', MAINTENANT)).toBe(false)
  })
})

describe('raisonATraiter', () => {
  it('un échec est à traiter', () => {
    expect(raisonATraiter({ status: 'failed' }, MAINTENANT)).toMatch(/échec/)
  })
  it("une VM en attente depuis plus de 30 min ne rappellera pas", () => {
    expect(raisonATraiter({ status: 'pending', hypervisor_id: 5, statut_depuis: ilY(45) }, MAINTENANT)).not.toBeNull()
    expect(raisonATraiter({ status: 'pending', hypervisor_id: 5, statut_depuis: ilY(10) }, MAINTENANT)).toBeNull()
  })
  it("un PC physique en attente n'est jamais bloqué : il attend qu'on le démarre", () => {
    expect(raisonATraiter({ status: 'pending', hypervisor_id: null, statut_depuis: ilY(60 * 24 * 7) }, MAINTENANT)).toBeNull()
  })
  it("l'accès internet en échec sur un VLAN fermé n'est pas un problème", () => {
    expect(raisonATraiter({ status: 'deployed', tests_en_echec: ['Acces internet (HTTPS)'] }, MAINTENANT)).toBeNull()
    expect(raisonATraiter({ status: 'deployed', tests_en_echec: ['Acces internet (HTTPS)', 'Agent Zabbix'] }, MAINTENANT))
      .toBe('tests en échec : Agent Zabbix')
  })
})
