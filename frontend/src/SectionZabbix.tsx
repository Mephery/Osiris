// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import { LIBELLES_CHOIX, choixPossible, type ChoixZabbix, type EtatZabbix } from './zabbixRetrait'

/** Dans la fenêtre de suppression : que devient l'hôte Zabbix de la machine ?
 *
 *  Muette quand il n'y a rien à décider (Zabbix non configuré, hôte absent). Un
 *  hôte du même nom rangé HORS du groupe d'OSIRIS est montré mais pas proposé :
 *  un nom ne prouve pas que c'est le nôtre. */
export function SectionZabbix({ etat, hostname, choix, onChoix }: {
  etat: EtatZabbix | null
  hostname: string
  choix: ChoixZabbix
  onChoix: (c: ChoixZabbix) => void
}) {
  if (!etat || !etat.configure) return null
  if (etat.erreur) {
    return <p className="text-[11px] text-slate-500">Zabbix injoignable : son hôte ne sera pas modifié.</p>
  }
  if (!etat.existe) return null
  if (!choixPossible(etat)) {
    return (
      <p className="text-[11px] text-slate-500 leading-relaxed">
        Un hôte Zabbix <span className="font-mono">{hostname}</span> existe, mais hors du groupe
        d'OSIRIS ({(etat.groupes ?? []).join(', ') || 'aucun groupe'}) : il n'est pas géré par OSIRIS
        et restera intact.
      </p>
    )
  }
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-[11px] text-slate-400 mb-1">
        Supervision Zabbix — hôte <span className="font-mono text-slate-300">{hostname}</span>{' '}
        <span className={etat.actif ? 'text-emerald-400' : 'text-slate-500'}>
          {etat.actif ? '● actif' : '○ désactivé'}
        </span>
      </legend>
      {(Object.keys(LIBELLES_CHOIX) as ChoixZabbix[]).map(c => (
        <label key={c} className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
          <input type="radio" name="zabbix-retrait" checked={choix === c}
                 onChange={() => onChoix(c)} className="accent-red-500" />
          {LIBELLES_CHOIX[c].titre}
          <span className="text-slate-600">({LIBELLES_CHOIX[c].detail})</span>
        </label>
      ))}
    </fieldset>
  )
}
