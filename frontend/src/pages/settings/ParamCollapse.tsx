import { Collapse, Form } from 'antd'
import { GROUP_ORDER, GROUP_TITLES, PARAM_LABELS } from './paramLabels'
import type { Leaf } from './paramSchema'
import { ParamField } from './ParamField'

const REQUIRED = [{ required: true, message: '값을 입력하세요' }]

interface Props {
  /** Every parameter, in display order (``inDisplayOrder(signalParamLeaves())``). */
  leaves: Leaf[]
  /** Where the parameters live in the form, e.g. ``['signal_params']``. */
  prefix: string[]
}

/** The parameters of the signals, one collapsible group each; shared by 설정 and 백테스트. */
export function ParamCollapse({ leaves, prefix }: Props) {
  return (
    <Collapse
      items={GROUP_ORDER.map((group) => ({
        key: group,
        label: GROUP_TITLES[group] ?? group,
        children: leaves
          .filter((leaf) => leaf.group === group && !PARAM_LABELS[leaf.key]?.card)
          .map((leaf) => (
            <Form.Item
              key={leaf.key}
              label={PARAM_LABELS[leaf.key]?.label ?? leaf.key}
              extra={PARAM_LABELS[leaf.key]?.help}
              name={[...prefix, leaf.group, leaf.field]}
              rules={leaf.kind === 'boolean' ? undefined : REQUIRED}
              valuePropName={leaf.kind === 'boolean' ? 'checked' : 'value'}
            >
              <ParamField leaf={leaf} />
            </Form.Item>
          )),
      }))}
    />
  )
}
