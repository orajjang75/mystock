import type { CycleOut, HoldingState } from '../../api/types'

// Gold and orange (not red or blue): red and blue mean up and down on this app's screens.
export const HOLDING_STATE: Record<HoldingState, { label: string; color: string }> = {
  holding: { label: '보유', color: 'green' },
  rebuy_wait: { label: '재매수 대기', color: 'gold' },
  expired: { label: '만료', color: 'orange' },
}

export const CYCLE_STATE: Record<CycleOut['state'], { label: string; color: string }> = {
  rebuy_wait: { label: '재매수 대기', color: 'gold' },
  expired: { label: '만료', color: 'orange' },
  rebuy_done: { label: '재매수 완료', color: 'green' },
  abandoned: { label: '포기', color: 'default' },
  force_closed: { label: '강제 매도 종료', color: 'purple' },
}
