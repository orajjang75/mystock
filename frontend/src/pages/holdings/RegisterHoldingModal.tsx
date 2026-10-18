import { App as AntdApp, Alert, AutoComplete, Form, InputNumber, Modal, Space } from 'antd'
import { useMemo, useState } from 'react'
import { errorMessage } from '../../api/client'
import { useCreateHolding, useResults, useWatchlist } from '../../api/queries'
import { thousands } from '../../lib/format'

interface Props {
  open: boolean
  onClose: () => void
  onCreated: (holdingId: number) => void
}

interface Values {
  code: string
  quantity: number
  avg_price: number
}

/** A-1: register a holding. Its quantity is also recorded as the 시작 수량. */
export function RegisterHoldingModal({ open, onClose, onCreated }: Props) {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<Values>()
  const create = useCreateHolding()
  const [error, setError] = useState<string | null>(null)
  const results = useResults()
  const watchlist = useWatchlist()

  // Stocks the app already knows by name (latest scan, watchlist) are offered as the user types.
  const options = useMemo(() => {
    const known = new Map<string, string>()
    for (const item of watchlist.data ?? []) known.set(item.code, item.name)
    for (const item of results.data?.items ?? []) known.set(item.code, item.name)
    return [...known].map(([code, name]) => ({ value: code, label: `${name} (${code})` }))
  }, [results.data, watchlist.data])

  const submit = (v: Values) => {
    setError(null)
    create.mutate(
      { code: v.code.trim(), quantity: v.quantity, avg_price: v.avg_price },
      {
        onSuccess: (holding) => {
          void message.success(`${holding.name}을(를) 등록했습니다 (시작 수량 ${holding.start_quantity}주)`)
          form.resetFields()
          onCreated(holding.id)
        },
        onError: (e) => setError(errorMessage(e)),
      },
    )
  }

  return (
    <Modal
      open={open}
      title="보유 종목 등록"
      okText="등록"
      cancelText="취소"
      confirmLoading={create.isPending}
      onOk={() => form.submit()}
      onCancel={() => {
        setError(null)
        onClose()
      }}
      destroyOnHidden
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {error && <Alert type="error" showIcon message={error} />}
        <Form<Values> form={form} layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item
            name="code"
            label="종목 코드"
            rules={[
              { required: true, message: '종목 코드를 입력하세요' },
              { pattern: /^[0-9A-Za-z]{6}$/, message: '종목 코드는 6자리입니다' },
            ]}
            extra="스캔 결과와 관심종목에 있는 종목은 이름으로 골라 넣을 수 있습니다."
          >
            <AutoComplete
              options={options}
              placeholder="예: 005930"
              filterOption={(input, option) => `${option?.label ?? ''}`.toLowerCase().includes(input.toLowerCase())}
              style={{ width: '100%' }}
            />
          </Form.Item>
          <Space size="middle" wrap align="start">
            <Form.Item name="quantity" label="수량 (주)" rules={[{ required: true, message: '수량을 입력하세요' }]}>
              <InputNumber min={1} precision={0} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="avg_price" label="평균단가 (원)" rules={[{ required: true, message: '평균단가를 입력하세요' }]}>
              <InputNumber min={1} precision={0} step={100} style={{ width: 180 }} {...thousands} />
            </Form.Item>
          </Space>
        </Form>
      </Space>
    </Modal>
  )
}
