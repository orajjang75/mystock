import type { ReactNode } from 'react'
import { directionColor } from '../theme/colors'

interface Props {
  /** Decides the color: positive is red, negative is blue, zero or missing is gray. */
  value: number | null | undefined
  children: ReactNode
}

/** Text colored by the sign of ``value``, following the Korean up-red / down-blue convention. */
export function Direction({ value, children }: Props) {
  return <span style={{ color: directionColor(value) }}>{children}</span>
}
