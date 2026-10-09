import { describe, expect, it } from 'vitest'
import { commandeSsh, provenanceAdresse, type AdresseMachine } from './adresseMachine'

const base: AdresseMachine = { ip: '192.0.2.10', ips: ['192.0.2.10'], source: 'constatee', le: null, compte: 'humans' }

describe('adresse de la machine', () => {
  it('seule une adresse lue en direct est présentée comme sûre', () => {
    expect(provenanceAdresse(base).sure).toBe(true)
    expect(provenanceAdresse({ ...base, source: 'remontee' }).sure).toBe(false)
    expect(provenanceAdresse({ ...base, source: 'declaree' }).sure).toBe(false)
  })

  it('une adresse remontée dit de quand elle date', () => {
    const p = provenanceAdresse({ ...base, source: 'remontee', le: '2026-10-09T08:12:00+00:00' })
    expect(p.texte).toMatch(/09\/10/)
    expect(p.texte).toMatch(/DHCP/)
  })

  it('la commande SSH vise le compte du profil', () => {
    expect(commandeSsh(base)).toBe('ssh humans@192.0.2.10')
    expect(commandeSsh({ ...base, compte: '' })).toBe('')
    expect(commandeSsh({ ...base, ip: '' })).toBe('')
  })
})
