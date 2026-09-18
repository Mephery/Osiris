// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.
import type { ReactNode } from 'react'

export function SkeletonBar({ cls = 'h-4 w-full' }: { cls?: string }) {
  return <div className={`animate-pulse rounded bg-slate-800/60 ${cls}`} />
}

// Lignes de tableau fantômes, pendant le chargement d'une liste.
export function SkeletonRows({ count = 5, cols = 4 }: { count?: number; cols?: number }) {
  return (
    <div>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-3 border-b border-slate-800/50 last:border-0">
          {Array.from({ length: cols }).map((_, j) => (
            <SkeletonBar key={j} cls={`h-3 ${j === 0 ? 'w-32' : 'w-20'}`} />
          ))}
        </div>
      ))}
    </div>
  )
}

// Cartes de statistiques fantômes (tableau de bord).
export function SkeletonStatCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-slate-900 border border-slate-800/60 rounded p-4 text-center space-y-2">
          <SkeletonBar cls="h-8 w-16 mx-auto" />
          <SkeletonBar cls="h-2 w-20 mx-auto" />
        </div>
      ))}
    </div>
  )
}

// Rond qui tourne : un chargement qui ne bouge pas ressemble à un écran planté.
// Le texte seul (« Lecture… ») ne suffit pas — c'est le mouvement qui prouve
// que quelque chose se passe. `label` est lu par les lecteurs d'écran.
export function Spinner({ cls = 'w-3.5 h-3.5', label = 'Chargement' }: { cls?: string; label?: string }) {
  return (
    <svg className={`animate-spin text-blue-400 ${cls}`} viewBox="0 0 24 24" fill="none" role="status" aria-label={label}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

// Un menu déroulant qui attend l'hyperviseur : le rond tourne DANS le champ, là
// où le regard attend la réponse, à la place de la flèche du menu.
export function ChampEnCours({ enCours, cls = '', children }: { enCours: boolean; cls?: string; children: ReactNode }) {
  return (
    <div className={`relative ${cls}`}>
      {children}
      {enCours && (
        <span className="pointer-events-none absolute inset-y-0 right-7 flex items-center">
          <Spinner />
        </span>
      )}
    </div>
  )
}
