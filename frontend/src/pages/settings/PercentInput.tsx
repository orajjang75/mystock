import { NumberField } from './NumberField'

interface Props {
  /** The stored fraction (0.0018). */
  value?: number | null
  onChange?: (value: number | null) => void
  min?: number
  max?: number
  step?: number
  id?: string
}

const round = (value: number) => Math.round(value * 1e8) / 1e8

/** An input that shows a fraction as percent: 0.0018 is typed and shown as 0.18. */
export function PercentInput({ value, onChange, min, max, step = 0.01, id }: Props) {
  return (
    <NumberField
      id={id}
      unit="%"
      value={value == null ? undefined : round(value * 100)}
      min={min === undefined ? undefined : round(min * 100)}
      max={max === undefined ? undefined : round(max * 100)}
      step={step}
      onChange={(shown) => onChange?.(shown === null ? null : round(Number(shown) / 100))}
    />
  )
}
