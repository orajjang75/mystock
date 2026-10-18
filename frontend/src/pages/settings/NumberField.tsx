import { InputNumber, Space } from 'antd'
import type { ComponentProps } from 'react'

type Props = ComponentProps<typeof InputNumber> & { unit?: string }

/** An antd number input followed by its unit ("%", "봉", "원"). */
export function NumberField({ unit, style, ...rest }: Props) {
  return (
    <Space size={6}>
      <InputNumber style={{ width: 150, ...style }} {...rest} />
      {unit && <span aria-hidden>{unit}</span>}
    </Space>
  )
}
