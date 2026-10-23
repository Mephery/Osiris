// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { Site } from './types'
import { authHeader } from './types'
import { lireReponse } from './api'
import { depuis, ligneConf, presentationEtat, taille } from './sitesEtat'

const API_URL = import.meta.env.VITE_API_URL ?? ''

/** Infrastructure → Sites distants.
 *
 *  Un site distant a un cache qui sert sur place l'image, WinPE et les pilotes,
 *  et les recopie chaque nuit depuis OSIRIS. Ce qu'on vient chercher ici : « le
 *  cache de Paris est-il à jour ? ». Chaque site se lit donc en une ligne : son
 *  état, sa dernière copie réussie, et la phrase qui dit quoi faire.
 *
 *  Le jeton du cache n'est montré qu'une fois (OSIRIS n'en garde que
 *  l'empreinte) : le panneau qui l'affiche reste ouvert tant qu'on n'a pas dit
 *  l'avoir copié, pour qu'un clic distrait ne le perde pas. */
export function SitesSection({ token }: { token: string }) {
  const [sites, setSites] = useState<Site[] | null>(null)
  const [nouveauNom, setNouveauNom] = useState('')
  const [envoi, setEnvoi] = useState(false)
  // Le jeton à recopier dans la conf du cache, et pour quel site
  const [jetonMontre, setJetonMontre] = useState<{ nom: string; jeton: string } | null>(null)
  const [ouvert, setOuvert] = useState<number | null>(null)

  const charger = useCallback(() => {
    fetch(`${API_URL}/sites`, { headers: authHeader(token) })
      .then(r => lireReponse<Site[]>(r, 'Lecture des sites refusée'))
      .then(setSites)
      .catch((e: Error) => toast.error(e.message))
  }, [token])

  useEffect(() => { charger() }, [charger])

  const creer = (e: React.FormEvent) => {
    e.preventDefault()
    setEnvoi(true)
    fetch(`${API_URL}/sites`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeader(token) },
      body: JSON.stringify({ nom: nouveauNom.trim() }),
    })
      .then(r => lireReponse<Site>(r, 'Création refusée'))
      .then(s => {
        setNouveauNom('')
        if (s.jeton) setJetonMontre({ nom: s.nom, jeton: s.jeton })
        charger()
      })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setEnvoi(false))
  }

  const renouveler = (s: Site) => {
    if (!window.confirm(
      `Nouveau jeton pour « ${s.nom} » ?\n\nL'ancien cesse de valoir tout de suite : le cache ne pourra plus ` +
      `rendre compte tant que sa configuration n'aura pas reçu le nouveau.`)) return
    fetch(`${API_URL}/sites/${s.id}/jeton`, { method: 'POST', headers: authHeader(token) })
      .then(r => lireReponse<{ jeton: string }>(r, 'Renouvellement refusé'))
      .then(({ jeton }) => setJetonMontre({ nom: s.nom, jeton }))
      .catch((e: Error) => toast.error(e.message))
  }

  const supprimer = (s: Site) => {
    if (!window.confirm(
      `Retirer le site « ${s.nom} » d'OSIRIS ?\n\nSon cache n'est pas touché, mais il ne pourra plus rendre ` +
      `compte. Pour lui couper aussi la copie, retirer sa clé du compte osiris-cache.`)) return
    fetch(`${API_URL}/sites/${s.id}`, { method: 'DELETE', headers: authHeader(token) })
      .then(r => lireReponse(r, 'Suppression refusée'))
      .then(() => { toast.success(`${s.nom} retiré`); setOuvert(null); charger() })
      .catch((e: Error) => toast.error(e.message))
  }

  const copier = (texte: string) => {
    navigator.clipboard?.writeText(texte)
      .then(() => toast.success('Copié'))
      .catch(() => toast.error('Copie impossible : sélectionner le texte à la main'))
  }

  const titre = 'text-xs font-bold uppercase tracking-widest text-slate-500'

  return (
    <div className="space-y-4 max-w-4xl">
      {jetonMontre && (
        <div className="border border-amber-500/50 bg-amber-500/5 rounded p-4 space-y-2">
          <p className="text-sm text-amber-200 font-medium">Jeton du site « {jetonMontre.nom} » — affiché une seule fois</p>
          <p className="text-[11px] text-slate-400">
            À recopier dans <span className="font-mono">/etc/osiris-cache/cache.conf</span> sur le cache de ce site.
            OSIRIS n'en garde qu'une empreinte : s'il est perdu, il faudra en générer un nouveau.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 min-w-0 break-all font-mono text-xs text-white bg-slate-900 border border-slate-700 rounded px-2 py-1.5 select-all">
              {ligneConf(jetonMontre.jeton)}
            </code>
            <button type="button" onClick={() => copier(ligneConf(jetonMontre.jeton))} className="osiris-btn text-xs px-3 flex-shrink-0">Copier</button>
          </div>
          <div className="flex justify-end">
            <button type="button" onClick={() => setJetonMontre(null)} className="osiris-btn-ghost text-xs px-3 border border-slate-700 rounded">J'ai copié le jeton</button>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_280px] items-start">
        {/* ── Ce qui existe ─────────────────────────────────────────────── */}
        <div className="osiris-table-wrap p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className={titre}>Sites distants{sites ? ` (${sites.length})` : ''}</h2>
            <button type="button" onClick={charger} className="text-[10px] text-slate-500 hover:text-slate-300">Actualiser</button>
          </div>
          {sites === null && <p className="text-slate-600 text-xs">Chargement…</p>}
          {sites?.length === 0 && (
            <p className="text-slate-500 text-xs leading-relaxed">
              Aucun site distant. Un site en a besoin quand son lien vers OSIRIS est trop lent pour faire passer
              une image Windows : un cache y sert l'image sur place. Voir <span className="font-mono">deploy/cache/README.md</span>.
            </p>
          )}
          <ul className="space-y-2">
            {sites?.map(s => {
              const p = presentationEtat(s.etat.code)
              const detail = ouvert === s.id
              return (
                <li key={s.id} className="border-b border-slate-800/50 pb-2 space-y-1">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 flex items-center gap-2">
                      <span className="text-sm text-white font-medium">{s.nom}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${p.classe}`}>{p.libelle}</span>
                    </div>
                    <button type="button" onClick={() => setOuvert(detail ? null : s.id)}
                      className="text-[10px] text-slate-500 hover:text-slate-300 flex-shrink-0">
                      {detail ? 'Masquer' : 'Détails'}
                    </button>
                  </div>
                  <p className="text-[11px] text-slate-300 leading-relaxed">{s.etat.message}</p>
                  <p className="text-[10px] text-slate-500">
                    Dernière copie réussie : {depuis(s.copie_reussie_le)}
                    {s.rapport_le && s.rapport_le !== s.copie_reussie_le && <> · dernier compte rendu : {depuis(s.rapport_le)}</>}
                  </p>
                  {s.etat.ecarts.length > 0 && (
                    <ul className="text-[10px] space-y-0.5 pl-3">
                      {s.etat.ecarts.map(e => (
                        <li key={e.nom} className={e.attendue_cette_nuit ? 'text-slate-500' : 'text-red-300'}>
                          <span className="font-mono">{e.nom}</span> : {e.probleme}
                          {e.attendue_cette_nuit && ' — arrivera avec la copie de cette nuit'}
                        </li>
                      ))}
                    </ul>
                  )}
                  {detail && (
                    <div className="pt-1 space-y-1">
                      <p className="text-[10px] text-slate-500">
                        {/* Une copie coupée en route ne donne pas ses chiffres : on
                            n'affiche pas un volume qui serait faux. */}
                        {s.erreur
                          ? <>Dernière tentative : {s.duree_s} s, volume reçu inconnu (copie interrompue)</>
                          : <>Dernière copie : {s.duree_s} s, {taille(s.octets_recus)} reçus</>}
                        {' '}· site créé {depuis(s.cree_le)}
                      </p>
                      <div className="flex items-center gap-3">
                        <button type="button" onClick={() => renouveler(s)} className="text-[10px] text-slate-400 hover:text-white">Nouveau jeton…</button>
                        <button type="button" onClick={() => supprimer(s)} className="text-[10px] text-red-400 hover:text-red-300">Retirer le site…</button>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </div>

        {/* ── Ce que j'ajoute ───────────────────────────────────────────── */}
        <form onSubmit={creer} className="border border-dashed border-slate-700 rounded p-5 space-y-3">
          <h2 className={titre}>+ Nouveau site</h2>
          <label className="block text-[10px] text-slate-500 space-y-0.5">Nom du site
            <input required value={nouveauNom} placeholder="ex : Paris"
              onChange={e => setNouveauNom(e.target.value)} className="osiris-input text-xs w-full" />
          </label>
          <p className="text-[10px] text-slate-600 leading-relaxed">
            OSIRIS affichera le jeton du cache, une seule fois. L'installation du cache est décrite
            dans <span className="font-mono">deploy/cache/README.md</span>.
          </p>
          <button type="submit" disabled={envoi || !nouveauNom.trim()} className="osiris-btn text-xs w-full disabled:opacity-50">Créer le site</button>
        </form>
      </div>
    </div>
  )
}
