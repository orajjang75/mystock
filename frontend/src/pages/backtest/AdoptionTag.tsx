import { Tag, Tooltip } from 'antd'
import type { Adoption } from '../../features/backtest/result'

/** 채택 가능 / 표본 부족: a result under the minimum sample size is never to be adopted. */
export function AdoptionTag({ adoption }: { adoption: Adoption }) {
  if (adoption.adoptable) return <Tag color="green">표본 기준 충족</Tag>
  return (
    <Tooltip title={adoption.reasons.join(' / ')}>
      <Tag color="orange">표본 부족 · 채택 불가</Tag>
    </Tooltip>
  )
}
