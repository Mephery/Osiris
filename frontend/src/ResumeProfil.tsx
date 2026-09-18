// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import type { ResumeProfil as Resume } from './types'

const TON = {
  ok: 'text-emerald-400',
  attention: 'text-amber-400',
  neutre: 'text-slate-400',
} as const

/** Ce que fait un profil, sous son nom : compte, accès, domaine.
 *
 *  Deux profils Debian identiques à l'œil, dont un seul donnait un accès : le
 *  second a enfermé dehors, et OSIRIS a écrit « réussi ». Un profil doit dire ce
 *  qu'il fait au moment où on le choisit, pas après le déploiement. */
export function ResumeProfil({ resume, physique = false }: {
  resume?: Resume
  /** Machine physique : son installeur pose un mot de passe, affiché une fois à la
   *  création. L'alerte, qui ne vaut que pour une VM, y serait du bruit — et un
   *  rouge qu'on apprend à ignorer ne protège plus rien. */
  physique?: boolean
}) {
  if (!resume) return null
  return (
    <div className="mt-1 space-y-0.5">
      {resume.alerte && !physique && (
        <p className="text-[10px] text-red-400 font-semibold">⛔ {resume.alerte}</p>
      )}
      <p className="text-[10px] leading-relaxed">
        {resume.lignes.map((l, i) => (
          <span key={l.sujet}>
            {i > 0 && <span className="text-slate-700"> · </span>}
            <span className="text-slate-600">{l.sujet} </span>
            <span className={TON[l.ton]}>{l.texte}</span>
          </span>
        ))}
      </p>
    </div>
  )
}
