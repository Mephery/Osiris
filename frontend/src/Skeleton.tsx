// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.

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
