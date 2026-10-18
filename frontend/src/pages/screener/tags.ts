// Color groups of the screener's condition tags (keys come from the API's TAG_LABELS). Not red or
// blue: those two mean price direction everywhere in the app.
const GROUPS: Record<string, string[]> = {
  gate: ['drawdown', 'disparity', 'bollinger_break'],
  reversal: ['rsi_cross_up', 'bullish_divergence', 'bollinger_reentry'],
  confirmation: ['macd_golden_cross', 'close_above_ma20', 'ma5_above_ma20', 'downwave_breakout', 'obv_turn_up'],
  volume: ['volume_2x', 'volume_3x'],
  flow: ['foreign_consecutive', 'institution_consecutive', 'net_buy_strength', 'net_buy_turnaround'],
}

const COLORS: Record<string, string> = {
  gate: 'default',
  reversal: 'purple',
  confirmation: 'cyan',
  volume: 'gold',
  flow: 'green',
}

export const FLOW_UNREFLECTED_KEY = 'flow_unreflected'

/** antd tag color for a condition tag key. '수급 미반영' stands out as a warning. */
export function tagColor(key: string): string {
  if (key === FLOW_UNREFLECTED_KEY) return 'warning'
  const group = Object.keys(GROUPS).find((name) => GROUPS[name].includes(key))
  return group ? COLORS[group] : 'default'
}
