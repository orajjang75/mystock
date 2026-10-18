import { App as AntdApp, Alert, Checkbox, Form, InputNumber, Modal, Segmented, Space, Typography } from 'antd'
import { useState } from 'react'
import { errorMessage } from '../../api/client'
import { useMarkAlertRead, useRecordFill } from '../../api/queries'
import type { AlertOut, FillResponse, HoldingOut } from '../../api/types'
import { Direction } from '../../components/Direction'
import type { FillSide } from '../../features/alertTargets'
import { formatNumber, thousands } from '../../lib/format'
import type { FillDraft } from './fillDefaults'

interface Props {
  holding: HoldingOut
  draft: FillDraft
  /** The alert the fill answers; it is marked read once the fill is recorded. */
  alert?: AlertOut
  /** Shares of the sale this rebuy answers, for the preview of 수량 증가분. */
  soldQuantity: number | null
  onClose: () => void
}

interface Values {
  side: FillSide
  price: number | null
  quantity: number | null
  forced: boolean
}

const SIDE_LABEL: Record<FillSide, string> = { sell: '매도', rebuy: '재매수' }

/** The message after a fill: what the user needs to know next. */
function outcome(side: FillSide, result: FillResponse): string {
  if (side === 'sell') {
    return result.cycle.forced
      ? '강제 매도를 기록했습니다. 사이클이 종료되었습니다.'
      : `매도 체결을 기록했습니다. 재매수 목표가는 ${formatNumber(result.cycle.rebuy_target_price)}원입니다.`
  }
  const gain = result.cycle.quantity_increase
  return gain === null
    ? '재매수 체결을 기록했습니다.'
    : `재매수 체결을 기록했습니다. 수량 증가분은 ${gain > 0 ? '+' : ''}${gain}주입니다.`
}

/**
 * 체결 기록: the user sold or bought at the broker; this records it, which moves the holding's
 * state. Opened from an alert it is already filled in, so recording takes one more click. The
 * form starts from ``draft`` when it opens; mount it only while it should be shown.
 */
export function FillModal({ holding, draft, alert, soldQuantity, onClose }: Props) {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<Values>()
  const record = useRecordFill()
  const markRead = useMarkAlertRead()
  const [error, setError] = useState<string | null>(null)
  const values = Form.useWatch([], form) as Values | undefined
  const side = values?.side ?? draft.side

  const submit = (v: Values) => {
    if (v.price === null || v.quantity === null) return
    setError(null)
    record.mutate(
      { holdingId: holding.id, body: { side: v.side, price: v.price, quantity: v.quantity, forced: v.side === 'sell' && v.forced } },
      {
        onSuccess: (result) => {
          if (alert && !alert.is_read) markRead.mutate(alert.id)
          void message.success(outcome(v.side, result))
          onClose()
        },
        onError: (e) => setError(errorMessage(e)),
      },
    )
  }

  const increase = side === 'rebuy' && soldQuantity !== null && values?.quantity ? values.quantity - soldQuantity : null

  return (
    <Modal
      open
      title={`${SIDE_LABEL[side]} 체결 기록 · ${holding.name}`}
      okText="기록"
      cancelText="취소"
      confirmLoading={record.isPending}
      onOk={() => form.submit()}
      onCancel={onClose}
      destroyOnHidden
      maskClosable={false}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          {alert
            ? '알림의 제안 수량과 가격을 채워 두었습니다. 증권사에서 실제로 체결한 값과 다르면 고쳐 주세요.'
            : '증권사 앱에서 체결한 뒤 그 값을 기록하면 보유 종목의 상태가 바뀝니다. 앱은 주문하지 않습니다.'}
        </Typography.Text>
        {error && <Alert type="error" showIcon message={error} />}
        <Form<Values>
          form={form}
          layout="vertical"
          onFinish={submit}
          requiredMark={false}
          initialValues={{ side: draft.side, price: draft.price, quantity: draft.quantity, forced: draft.forced }}
        >
          <Form.Item name="side" label="구분">
            <Segmented
              options={[
                { value: 'sell', label: '매도' },
                { value: 'rebuy', label: '재매수' },
              ]}
            />
          </Form.Item>
          <Space size="middle" align="start" wrap>
            <Form.Item name="price" label="체결가 (원)" rules={[{ required: true, message: '체결가를 입력하세요' }]}>
              <InputNumber min={1} step={100} style={{ width: 160 }} precision={0} {...thousands} />
            </Form.Item>
            <Form.Item name="quantity" label="수량 (주)" rules={[{ required: true, message: '수량을 입력하세요' }]}>
              <InputNumber min={1} step={1} style={{ width: 120 }} precision={0} />
            </Form.Item>
          </Space>
          {side === 'sell' && (
            <Form.Item name="forced" valuePropName="checked">
              <Checkbox>5일선 이탈 강제 매도 (전량 매도, 사이클 종료)</Checkbox>
            </Form.Item>
          )}
        </Form>
        {increase !== null && (
          <Typography.Text>
            예상 수량 증가분{' '}
            <Direction value={increase}>
              <strong>
                {increase > 0 ? '+' : ''}
                {increase}주
              </strong>
            </Direction>{' '}
            <Typography.Text type="secondary">(매도 {soldQuantity}주 대비)</Typography.Text>
          </Typography.Text>
        )}
        <Typography.Text type="secondary">수수료와 거래세는 설정의 요율로 자동 계산됩니다.</Typography.Text>
      </Space>
    </Modal>
  )
}
