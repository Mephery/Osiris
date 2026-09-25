// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { describe, expect, it } from 'vitest'
import { lireReponse } from './api'

const reponse = (status: number, corps?: unknown) =>
  new Response(corps === undefined ? null : JSON.stringify(corps), { status })

describe('lireReponse', () => {
  it('rend le corps d\'une réponse réussie', async () => {
    expect(await lireReponse(reponse(200, { id: 3 }), 'x')).toEqual({ id: 3 })
  })

  it('rend null pour un 204, sans corps à lire', async () => {
    expect(await lireReponse(reponse(204), 'x')).toBeNull()
  })

  it("lève l'explication du serveur", async () => {
    await expect(lireReponse(reponse(409, { detail: 'Acme est encore rattachée à : 2 machine(s).' }), 'x'))
      .rejects.toThrow('Acme est encore rattachée à : 2 machine(s).')
  })

  it('assemble les messages d\'une erreur de validation', async () => {
    await expect(lireReponse(reponse(422, { detail: [{ msg: 'champ requis' }, { msg: 'trop court' }] }), 'x'))
      .rejects.toThrow('champ requis · trop court')
  })

  it('retombe sur le repli, code compris, quand le serveur ne dit rien', async () => {
    await expect(lireReponse(reponse(500), 'Suppression refusée'))
      .rejects.toThrow('Suppression refusée (erreur 500)')
  })
})

// L'invariant, lu dans le code lui-même : toute écriture (POST, PATCH, PUT,
// DELETE) regarde si elle a réussi AVANT d'annoncer quoi que ce soit, et dit
// quelque chose quand elle échoue. Un `fetch` ne rejette que si le réseau
// tombe : sans ce contrôle, un refus du serveur s'affichait « supprimé »
// (quatre écrans le 25/09) ou ne s'affichait pas du tout (sept autres).
const sources = import.meta.glob('./*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

describe('toute écriture vérifie sa réponse', () => {
  const ecritures = Object.entries(sources).flatMap(([fichier, code]) =>
    [...code.matchAll(/fetch\(/g)].map(m => {
      const suite = code.slice(m.index! + 6)
      const prochain = suite.search(/fetch\(/)
      const chaine = code.slice(m.index!, m.index! + 6 + (prochain === -1 ? 900 : Math.min(prochain, 900)))
      const methode = /method:\s*'(\w+)'/.exec(chaine.slice(0, 400))?.[1] ?? 'GET'
      const ligne = code.slice(0, m.index!).split('\n').length
      return { ou: `${fichier}:${ligne}`, methode, chaine }
    }),
  ).filter(e => e.methode !== 'GET')

  it('trouve bien les écritures à contrôler', () => {
    expect(ecritures.length).toBeGreaterThan(30)
  })

  it.each(ecritures.map(e => [e.ou, e]))('%s', (_, e) => {
    const verifiee = /lireReponse[<(]/.test(e.chaine)
      || (/\.ok\b/.test(e.chaine) && /throw|toast\.error|Error\(/.test(e.chaine))
    expect(verifiee, `${e.methode} sans contrôle de la réponse`).toBe(true)
  })
})
