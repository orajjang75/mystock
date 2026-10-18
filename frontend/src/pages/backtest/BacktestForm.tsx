import { PlayCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Checkbox, Col, DatePicker, Form, Input, InputNumber, Radio, Row, Select, Space, Switch, Typography } from 'antd'
import { useMemo, useState } from 'react'
import type { BacktestRequest, SettingsResponse } from '../../api/types'
import { GROUP_TITLES, PARAM_LABELS, inDisplayOrder } from '../settings/paramLabels'
import { signalParamLeaves } from '../settings/paramSchema'
import { ParamCollapse } from '../settings/ParamCollapse'
import { METRIC_LABELS } from './chartOptions'
import {
  CYCLE_METRICS,
  FormError,
  SLIPPAGE_OPTIONS,
  SQ_METRICS,
  buildRequest,
  defaultValues,
  parseNumbers,
  suggestValues,
  type BacktestFormValues,
  type Target,
} from './requestForm'

const BAR_OPTIONS = [
  { value: '30m', label: '30분봉' },
  { value: '60m', label: '60분봉' },
  { value: '1d', label: '일봉' },
]
const HORIZONS = [1, 3, 5, 10, 20, 40, 60]
const TARGET_OPTIONS = [
  { value: 'cycle', label: '사이클 (수량 늘리기)' },
  { value: 'signal_quality', label: '신호 품질 (스크리너 후보)' },
]

interface Props {
  settings: SettingsResponse
  submitting: boolean
  onSubmit: (request: BacktestRequest) => void
}

const metricOptions = (target: Target) =>
  (target === 'cycle' ? CYCLE_METRICS : SQ_METRICS).map((m) => ({ value: m, label: METRIC_LABELS[m] ?? m }))

/** 기간과 파라미터 폼: what to run, on which data, with which signal parameters. */
export function BacktestForm({ settings, submitting, onSubmit }: Props) {
  const [form] = Form.useForm<BacktestFormValues>()
  const [error, setError] = useState<string | null>(null)
  const initial = useMemo(() => defaultValues(settings), [settings])
  const leaves = useMemo(() => inDisplayOrder(signalParamLeaves()), [])
  const numeric = useMemo(() => leaves.filter((l) => l.kind === 'integer' || l.kind === 'number'), [leaves])
  const pathOptions = useMemo(
    () =>
      numeric.map((leaf) => ({
        value: leaf.key,
        label: `${GROUP_TITLES[leaf.group] ?? leaf.group} · ${PARAM_LABELS[leaf.key]?.label ?? leaf.key}`,
      })),
    [numeric],
  )
  const values = Form.useWatch([], form) as BacktestFormValues | undefined
  const current = values ?? initial
  const runs = current.run
  const cycleOn = runs.includes('cycle')
  const quality = runs.includes('signal_quality')

  const fillAround = (pathField: 'sens_x' | 'sens_y' | 'wf_param', valuesField: 'sens_x_values' | 'sens_y_values' | 'wf_values') => {
    const key = form.getFieldValue(pathField) as string | undefined
    const leaf = numeric.find((l) => l.key === key)
    if (!leaf) return
    const [group, field] = leaf.key.split('.')
    const params = form.getFieldValue('params') as Record<string, Record<string, number>>
    const base = params?.[group]?.[field] ?? Number(leaf.default)
    form.setFieldValue(valuesField, suggestValues(base, leaf.kind).join(', '))
  }

  const submit = (v: BacktestFormValues) => {
    setError(null)
    try {
      onSubmit(buildRequest({ ...initial, ...form.getFieldsValue(true), ...v }))
    } catch (e) {
      if (e instanceof FormError) setError(e.message)
      else throw e
    }
  }

  const axisRow = (
    pathField: 'sens_x' | 'sens_y' | 'wf_param',
    valuesField: 'sens_x_values' | 'sens_y_values' | 'wf_values',
    label: string,
    optional = false,
  ) => (
    <Row gutter={12}>
      <Col xs={24} md={12}>
        <Form.Item name={pathField} label={label}>
          <Select allowClear={optional} showSearch optionFilterProp="label" options={pathOptions} placeholder="파라미터" aria-label={label} />
        </Form.Item>
      </Col>
      <Col xs={24} md={12}>
        <Form.Item
          name={valuesField}
          label={`${label} 값`}
          extra={
            <Button type="link" size="small" style={{ padding: 0 }} onClick={() => fillAround(pathField, valuesField)}>
              현재 값 주변으로 채우기
            </Button>
          }
          rules={[
            {
              validator: async (_, text: string) => {
                if (!text && optional) return
                const parsed = parseNumbers(text ?? '')
                if (!parsed || parsed.length < 2) throw new Error('숫자를 두 개 이상 쉼표로 구분해 입력하세요')
              },
            },
          ]}
        >
          <Input placeholder="예: 0.005, 0.01, 0.015" aria-label={`${label} 값`} />
        </Form.Item>
      </Col>
    </Row>
  )

  return (
    <Form<BacktestFormValues> form={form} layout="vertical" initialValues={initial} onFinish={submit} requiredMark={false}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Card size="small" title="기간과 데이터">
          <Row gutter={16}>
            <Col xs={24} md={8}>
              <Form.Item name="name" label="이름 (선택)">
                <Input maxLength={80} placeholder="예: 목표이득 1.5% 시험" />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="range" label="기간" extra="비우면 저장된 데이터 전체(지표 준비 기간 이후)">
                <DatePicker.RangePicker style={{ width: '100%' }} allowEmpty={[true, true]} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="bar_length" label="사이클 신호 봉" extra="분봉은 저장된 구간에서만 돌릴 수 있습니다">
                <Radio.Group optionType="button" buttonStyle="solid" options={BAR_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
          <Space size="large" wrap>
            <Form.Item name="point_in_time" valuePropName="checked" style={{ marginBottom: 0 }}>
              <Switch checkedChildren="시점별 시가총액 순위" unCheckedChildren="오늘 순위로 고정" aria-label="시점별 시가총액 순위" />
            </Form.Item>
            <Form.Item name="include_delisted" valuePropName="checked" style={{ marginBottom: 0 }}>
              <Switch checkedChildren="상장폐지 종목 포함" unCheckedChildren="생존 종목만" aria-label="상장폐지 종목 포함" />
            </Form.Item>
            <Typography.Text type="secondary">수정주가는 항상 사용합니다 (시세 어댑터가 수정주가를 전달).</Typography.Text>
          </Space>
        </Card>

        <Card size="small" title="실행 항목">
          <Form.Item name="run" style={{ marginBottom: 8 }}>
            <Checkbox.Group
              options={[
                { value: 'signal_quality', label: '신호 품질 (후보 선정 후 수익률)' },
                { value: 'cycle', label: '사이클 시뮬레이션 (보유 → 매도 → 재매수/만료)' },
              ]}
            />
          </Form.Item>
          <Form.Item name="compare_bar_lengths" valuePropName="checked" style={{ marginBottom: 0 }}>
            <Checkbox disabled={!cycleOn}>30분·60분·일봉을 같은 기간에 비교</Checkbox>
          </Form.Item>
        </Card>

        {quality && (
          <Card size="small" title="신호 품질 옵션">
            <Row gutter={16}>
              <Col xs={24} md={8}>
                <Form.Item name="horizons" label="보유 기간 (거래일)">
                  <Select mode="multiple" options={HORIZONS.map((h) => ({ value: h, label: `${h}일` }))} />
                </Form.Item>
              </Col>
              <Col xs={12} md={4}>
                <Form.Item name="primary_horizon" label="기준 보유 기간">
                  <Select options={HORIZONS.map((h) => ({ value: h, label: `${h}일` }))} />
                </Form.Item>
              </Col>
              <Col xs={12} md={4}>
                <Form.Item name="random_trials" label="무작위 시행">
                  <InputNumber min={1} max={200} precision={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={4}>
                <Form.Item name="min_sample_dates" label="최소 표본 (신호일)">
                  <InputNumber min={1} precision={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
          </Card>
        )}

        {(quality || cycleOn) && (
          <Card size="small" title="체결 가정">
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item name="slippages" label="슬리피지 민감도 수준" extra="신호 다음 봉 시가에 체결하고, 매수·매도 모두 불리한 쪽으로 이만큼 어긋난다고 봅니다">
                  <Select
                    mode="multiple"
                    options={SLIPPAGE_OPTIONS.map((s) => ({ value: s, label: `${(s * 100).toFixed(1)}%` }))}
                    aria-label="슬리피지 수준"
                  />
                </Form.Item>
              </Col>
              {cycleOn && (
                <Col xs={12} md={6}>
                  <Form.Item name="slippage" label="사이클 기준 슬리피지">
                    <Select options={SLIPPAGE_OPTIONS.map((s) => ({ value: s, label: `${(s * 100).toFixed(1)}%` }))} />
                  </Form.Item>
                </Col>
              )}
            </Row>
          </Card>
        )}

        {cycleOn && (
          <Card size="small" title="사이클 옵션">
            <Row gutter={16}>
              <Col xs={12} md={6}>
                <Form.Item name="max_stocks" label="보유 종목 수">
                  <InputNumber min={1} max={300} precision={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={12} md={6}>
                <Form.Item name="initial_value" label="종목당 시작 금액 (원)">
                  <InputNumber min={100000} step={1000000} precision={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={12} md={6}>
                <Form.Item name="on_expiry" label="재매수 대기가 만료되면">
                  <Radio.Group
                    options={[
                      { value: 'abandon', label: '사이클 포기' },
                      { value: 'retry', label: '재매수 시도' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col xs={12} md={6}>
                <Form.Item name="min_sample_cycles" label="최소 표본 (끝난 사이클)">
                  <InputNumber min={1} precision={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
          </Card>
        )}

        <Card
          size="small"
          title="파라미터 민감도 히트맵"
          extra={
            <Form.Item name="sensitivity" valuePropName="checked" noStyle>
              <Switch aria-label="파라미터 민감도" />
            </Form.Item>
          }
        >
          {current.sensitivity ? (
            <>
              <Row gutter={12}>
                <Col xs={24} md={12}>
                  <Form.Item name="sens_target" label="무엇으로 평가할까">
                    <Select options={TARGET_OPTIONS} onChange={(t: Target) => form.setFieldValue('sens_metric', metricOptions(t)[0].value)} aria-label="민감도 평가 대상" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="sens_metric" label="지표">
                    <Select options={metricOptions(current.sens_target)} aria-label="민감도 지표" />
                  </Form.Item>
                </Col>
              </Row>
              {axisRow('sens_x', 'sens_x_values', '가로축')}
              {axisRow('sens_y', 'sens_y_values', '세로축 (선택)', true)}
            </>
          ) : (
            <Typography.Text type="secondary">켜면 파라미터를 바꿔 가며 같은 평가를 반복해 칸마다 결과를 보여 줍니다. 최고점 하나가 아니라 주변까지 고르게 좋은 구간을 고르는 데 씁니다.</Typography.Text>
          )}
        </Card>

        <Card
          size="small"
          title="롤링(walk-forward) 검증"
          extra={
            <Form.Item name="walk_forward" valuePropName="checked" noStyle>
              <Switch aria-label="롤링 검증" />
            </Form.Item>
          }
        >
          {current.walk_forward ? (
            <>
              <Row gutter={12}>
                <Col xs={24} md={12}>
                  <Form.Item name="wf_target" label="무엇으로 평가할까">
                    <Select options={TARGET_OPTIONS} onChange={(t: Target) => form.setFieldValue('wf_metric', metricOptions(t)[0].value)} aria-label="롤링 평가 대상" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="wf_metric" label="지표">
                    <Select options={metricOptions(current.wf_target)} aria-label="롤링 지표" />
                  </Form.Item>
                </Col>
              </Row>
              {axisRow('wf_param', 'wf_values', '고를 파라미터')}
              <Row gutter={12}>
                <Col xs={12} md={6}>
                  <Form.Item name="wf_train" label="학습 (거래일)">
                    <InputNumber min={20} precision={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="wf_test" label="검증 (거래일)">
                    <InputNumber min={5} precision={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="wf_step" label="이동 (거래일)">
                    <InputNumber min={5} precision={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="wf_min_samples" label="학습 최소 표본">
                    <InputNumber min={1} precision={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
            </>
          ) : (
            <Typography.Text type="secondary">켜면 기간을 학습 창과 검증 창으로 나눠 굴려 가며, 학습에서 고른 값이 보지 못한 검증 구간에서도 통하는지 봅니다.</Typography.Text>
          )}
        </Card>

        <Card size="small" title="신호 파라미터 (이번 실행에만 적용)">
          <Typography.Paragraph type="secondary">
            시작값은 설정 화면의 현재 값입니다. 여기서 바꿔도 설정은 바뀌지 않습니다. 결과가 마음에 들면 결과 화면에서 프리셋으로 저장하세요.
          </Typography.Paragraph>
          <ParamCollapse leaves={leaves} prefix={['params']} />
        </Card>

        {error && <Alert type="error" showIcon message={error} />}
        <Button type="primary" htmlType="submit" size="large" icon={<PlayCircleOutlined />} loading={submitting}>
          백테스트 실행
        </Button>
      </Space>
    </Form>
  )
}
