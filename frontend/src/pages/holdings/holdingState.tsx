import { Tag } from 'antd'
import type { CycleOut, HoldingState } from '../../api/types'
import { CYCLE_STATE, HOLDING_STATE } from './holdingStateMeta'

export function HoldingStateTag({ state }: { state: HoldingState }) {
  const { label, color } = HOLDING_STATE[state]
  return <Tag color={color}>{label}</Tag>
}

export function CycleStateTag({ state }: { state: CycleOut['state'] }) {
  const { label, color } = CYCLE_STATE[state]
  return <Tag color={color}>{label}</Tag>
}
