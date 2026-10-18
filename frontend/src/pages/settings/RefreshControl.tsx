import { Space, Switch } from 'antd'
import { useState } from 'react'
import { DEFAULT_REFRESH_SECONDS } from '../../api/queries'
import { NumberField } from './NumberField'

interface Props {
  /** Seconds between polls; 0 means polling is off. */
  value?: number
  onChange?: (value: number) => void
}

/** Polling switch plus period. Off is stored as 0; switching back on restores the last period. */
export function RefreshControl({ value = DEFAULT_REFRESH_SECONDS, onChange }: Props) {
  const [last, setLast] = useState(value > 0 ? value : DEFAULT_REFRESH_SECONDS)
  // Remember the last on-period; setting state while rendering is React's way to derive it.
  if (value > 0 && value !== last) setLast(value)

  return (
    <Space>
      <Switch
        checked={value > 0}
        checkedChildren="자동"
        unCheckedChildren="수동"
        aria-label="자동 갱신"
        onChange={(on) => onChange?.(on ? last : 0)}
      />
      <NumberField
        aria-label="갱신 주기"
        min={10}
        max={3600}
        precision={0}
        disabled={value === 0}
        value={value === 0 ? last : value}
        unit="초"
        onChange={(seconds) => seconds !== null && onChange?.(Number(seconds))}
      />
    </Space>
  )
}
