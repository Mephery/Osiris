// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.

/** Le corps d'une réponse réussie, ou l'explication du serveur en cas d'échec.
 *
 *  Un `fetch` ne rejette QUE si le réseau tombe : un 409, un 422 ou un 500 sont
 *  des réponses comme les autres. Enchaîner `.then(() => toast.success(…))` sans
 *  regarder `r.ok` annonçait donc « supprimé » sur un refus — trois fois
 *  constaté le 25/09 (organisation, VM, utilisateur…). Et un « Erreur » nu, là
 *  où le serveur dit POURQUOI, laisse l'opérateur réessayer à l'aveugle.
 *
 *  Toute écriture passe par ici ; un test parcourt le code pour le vérifier. */
export const lireReponse = async <T = unknown>(r: Response, repli: string): Promise<T> => {
  if (r.ok) return (r.status === 204 ? null : await r.json().catch(() => null)) as T
  const corps = await r.json().catch(() => ({}))
  // FastAPI : une chaîne pour nos HTTPException, une liste pour une validation
  const detail = typeof corps.detail === 'string'
    ? corps.detail
    : Array.isArray(corps.detail)
      ? corps.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(' · ')
      : ''
  throw new Error(detail || `${repli} (erreur ${r.status})`)
}
