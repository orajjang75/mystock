import { Select, Switch } from 'antd'
import type { Leaf } from './paramSchema'
import { PARAM_LABELS } from './paramLabels'
import { NumberField } from './NumberField'
import { PercentInput } from './PercentInput'

/** The input for one backend parameter, chosen by its schema type. Used inside a Form.Item. */
interface Props {
  leaf: Leaf
  /** Injected by Form.Item, so the label points at the input. */
  id?: string
  value?: unknown
  onChange?: (value: unknown) => void
}

export function ParamField({ leaf, id, value, onChange }: Props) {
  const meta = PARAM_LABELS[leaf.key]
  const min = leaf.min ?? leaf.exclusiveMin
  const max = leaf.max ?? leaf.exclusiveMax

  if (leaf.kind === 'boolean') {
    return <Switch id={id} checked={Boolean(value)} onChange={onChange} />
  }
  if (leaf.kind === 'enum') {
    return (
      <Select
        id={id}
        style={{ width: 200 }}
        value={value as string}
        onChange={onChange}
        options={leaf.options.map((option) => ({ value: option, label: meta?.options?.[option] ?? option }))}
      />
    )
  }
  if (meta?.percent) {
    return (
      <PercentInput id={id} value={value as number | undefined} onChange={onChange} min={min} max={max} step={0.01} />
    )
  }
  return (
    <NumberField
      id={id}
      value={value as number | undefined}
      min={min}
      max={max}
      step={leaf.kind === 'integer' ? 1 : 0.1}
      precision={leaf.kind === 'integer' ? 0 : undefined}
      unit={meta?.unit}
      onChange={onChange}
    />
  )
}
