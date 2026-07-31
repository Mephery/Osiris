// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.

/** Thème de l'interface. Le rendu réel est entièrement porté par App.css. */
export type Theme = 'dark' | 'light'

const KEY = 'osiris_theme'

/** Choix mémorisé, à défaut celui du système, à défaut le thème sombre. */
export function preferredTheme(): Theme {
  const stored = localStorage.getItem(KEY)
  if (stored === 'dark' || stored === 'light') return stored
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  localStorage.setItem(KEY, theme)
}

/** Appelé au démarrage, avant le rendu, pour ne pas afficher le mauvais fond. */
export function applyStoredTheme(): Theme {
  const theme = preferredTheme()
  document.documentElement.dataset.theme = theme
  return theme
}
