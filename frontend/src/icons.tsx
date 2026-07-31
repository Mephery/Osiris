// SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
// Copyright (c) 2026 Coline Derycke. See LICENSE.

type IProps = { cls?: string }

const S = ({ p, cls = 'w-3.5 h-3.5' }: { p: string; cls?: string }) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round"
    className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <path d={p} />
  </svg>
)

export const IcoOsiris    = ({ cls = 'w-5 h-5' }: IProps) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <circle cx="8" cy="8" r="6" />
    <circle cx="8" cy="8" r="1.5" fill="currentColor" stroke="none" />
  </svg>
)
export const IcoDownload  = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M8 2v8m0 0L5 7m3 3 3-3M2 13h12" />
export const IcoRefresh   = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M14 8A6 6 0 1 1 8 2.5M14 2v4h-4" />
export const IcoSearch    = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M7 12A5 5 0 1 0 7 2a5 5 0 0 0 0 10zm7 2-3-3" />
export const IcoPower     = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M8 2v5M5 4A5 5 0 1 0 11 4" />
export const IcoPencil    = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M11 2l3 3-9 9H2v-3z" />
export const IcoX         = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M3 3l10 10M13 3 3 13" />
export const IcoCheck     = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M2 8l4 4 8-8" />
export const IcoChevDown  = ({ cls = 'w-3 h-3' }: IProps) => <S cls={cls} p="M3 5l5 5 5-5" />
export const IcoChevUp    = ({ cls = 'w-3 h-3' }: IProps) => <S cls={cls} p="M3 11l5-5 5 5" />
export const IcoChevRight = ({ cls = 'w-3 h-3' }: IProps) => <S cls={cls} p="M5 3l5 5-5 5" />
export const IcoGear      = ({ cls = 'w-4 h-4' }: IProps) => <S cls={cls} p="M8 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM1.5 8a6.5 6.5 0 1 1 13 0 6.5 6.5 0 0 1-13 0z" />
export const IcoTerminal  = ({ cls = 'w-3.5 h-3.5' }: IProps) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round"
    className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <rect x="1" y="2" width="14" height="11" rx="1.5" />
    <path d="M4 6.5l2.5 2-2.5 2M8.5 10.5h3.5" />
  </svg>
)
export const IcoCamera    = ({ cls = 'w-3.5 h-3.5' }: IProps) => <S cls={cls} p="M1 5h2l1.5-2h7L13 5h2v8H1zM8 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z" />

export const IcoSun = ({ cls = 'w-3.5 h-3.5' }: IProps) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <circle cx="8" cy="8" r="3" />
    <path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M13 3l-1 1M4 12l-1 1" />
  </svg>
)

export const IcoMoon = ({ cls = 'w-3.5 h-3.5' }: IProps) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round"
    className={`inline-block shrink-0 ${cls}`} aria-hidden="true">
    <path d="M13.5 9.5A5.8 5.8 0 0 1 6.5 2.5a5.8 5.8 0 1 0 7 7Z" />
  </svg>
)
