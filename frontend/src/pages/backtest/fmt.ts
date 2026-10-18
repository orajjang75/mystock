import { formatNumber, formatPercent } from '../../lib/format'

/** A fraction as a signed percent: 0.0123 -> "+1.23%". */
export const signedFraction = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined ? '-' : formatPercent(value * 100, digits)

/** A fraction as a plain percent: 0.456 -> "45.6%". */
export const plainFraction = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined ? '-' : `${(value * 100).toFixed(digits)}%`

export const decimal = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined ? '-' : value.toFixed(digits)

export const won = (value: number | null | undefined): string =>
  value === null || value === undefined ? '-' : `${formatNumber(Math.round(value))}원`

export const shares = (value: number | null | undefined): string =>
  value === null || value === undefined ? '-' : `${value > 0 ? '+' : ''}${formatNumber(value)}주`
