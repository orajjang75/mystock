import {
  App as AntdApp,
  Alert,
  Button,
  Card,
  Form,
  Input,
  List,
  Popconfirm,
  Radio,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from 'antd'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { errorMessage } from '../../api/client'
import {
  useDeletePreset,
  useHealth,
  useLoadPreset,
  useSavePreset,
  useSaveSettings,
  useSendTestAlert,
  useSettings,
} from '../../api/queries'
import type { SettingsDocument, SettingsResponse } from '../../api/types'
import { PageHeader } from '../../components/PageHeader'
import { deepEqual } from './deepEqual'
import { toDocument } from './settingsDocument'
import { PARAM_LABELS, inDisplayOrder } from './paramLabels'
import { defaultSignalParams, signalParamLeaves } from './paramSchema'
import { NumberField } from './NumberField'
import { ParamCollapse } from './ParamCollapse'
import { ParamField } from './ParamField'
import { RefreshControl } from './RefreshControl'

const REQUIRED = [{ required: true, message: '값을 입력하세요' }]

const BAR_LENGTH_OPTIONS = [
  { value: '30m', label: '30분봉' },
  { value: '60m', label: '60분봉' },
  { value: '1d', label: '일봉' },
]

export function SettingsPage() {
  const { data, isPending, isError, error, refetch } = useSettings()

  if (isPending) {
    return (
      <div className="centered-screen">
        <Spin />
      </div>
    )
  }
  if (isError || !data) {
    return (
      <Alert
        type="error"
        showIcon
        message="설정을 불러오지 못했습니다"
        description={errorMessage(error)}
        action={<Button onClick={() => void refetch()}>다시 시도</Button>}
      />
    )
  }
  return <SettingsForm settings={data} />
}

function SettingsForm({ settings }: { settings: SettingsResponse }) {
  const { message } = AntdApp.useApp()
  const [form] = Form.useForm<SettingsDocument>()
  const [baseline, setBaseline] = useState<SettingsDocument>(() => toDocument(settings))
  const [dirty, setDirty] = useState(false)
  const [presetName, setPresetName] = useState('')

  const health = useHealth()
  const save = useSaveSettings()
  const savePreset = useSavePreset()
  const loadPreset = useLoadPreset()
  const deletePreset = useDeletePreset()
  const testAlert = useSendTestAlert()

  const leaves = useMemo(() => inDisplayOrder(signalParamLeaves()), [])

  const reset = (document: SettingsDocument) => {
    form.setFieldsValue(document)
    setBaseline(document)
    setDirty(false)
  }

  // Pick up the server's version, unless the user is in the middle of editing.
  useEffect(() => {
    if (!dirty) reset(toDocument(settings))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings])

  const refreshDirty = () => setDirty(!deepEqual(form.getFieldsValue(true), baseline))

  const onSave = async () => {
    try {
      await form.validateFields()
    } catch {
      void message.error('비어 있는 항목이 있습니다. 값을 입력하세요.')
      return
    }
    const values = form.getFieldsValue(true) as SettingsDocument
    save.mutate(values, {
      onSuccess: (saved) => {
        reset(toDocument(saved))
        void message.success('설정을 저장했습니다')
      },
      onError: (e) => void message.error(errorMessage(e)),
    })
  }

  const onLoadPreset = (name: string) =>
    loadPreset.mutate(name, {
      onSuccess: (loaded) => {
        reset(toDocument(loaded))
        void message.success(`프리셋 "${name}"을 불러왔습니다`)
      },
      onError: (e) => void message.error(errorMessage(e)),
    })

  const onSavePreset = () => {
    const name = presetName.trim()
    if (!name) return
    if (dirty) {
      void message.warning('저장하지 않은 변경은 프리셋에 담기지 않습니다. 먼저 설정을 저장하세요.')
      return
    }
    savePreset.mutate(name, {
      onSuccess: () => {
        setPresetName('')
        void message.success(`프리셋 "${name}"을 저장했습니다`)
      },
      onError: (e) => void message.error(errorMessage(e)),
    })
  }

  const onTest = () =>
    testAlert.mutate(undefined, {
      onSuccess: ({ channels }) => {
        for (const result of channels) {
          if (result.status === 'sent') void message.success(`${result.channel}: 시험 알림을 보냈습니다`)
          else void message.error(`${result.channel}: 보내지 못했습니다 (${result.error ?? '알 수 없는 오류'})`)
        }
      },
      onError: (e) => void message.warning(errorMessage(e)),
    })

  const telegram = health.data?.channels.telegram

  const resetParamsToDefaults = () => {
    form.setFieldValue('signal_params', defaultSignalParams())
    refreshDirty()
  }

  return (
    <>
      <PageHeader title="설정" description="지표 파라미터, 신호 봉 길이, 요율, 갱신 주기, 알림을 바꾸고 프리셋으로 보관합니다." />
      <Form<SettingsDocument>
        form={form}
        layout="horizontal"
        labelCol={{ flex: '220px' }}
        wrapperCol={{ flex: 1 }}
        labelWrap
        initialValues={toDocument(settings)}
        onValuesChange={refreshDirty}
        className="settings-form"
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Card title="신호 봉 길이" size="small">
            <Form.Item name="signal_bar_length" label="매도·재매수 신호에 쓰는 봉" extra="일봉 방향 필터(A-6)는 어떤 봉을 고르든 항상 함께 쓰입니다.">
              <Radio.Group optionType="button" buttonStyle="solid" options={BAR_LENGTH_OPTIONS} />
            </Form.Item>
          </Card>

          <Card title="수수료·거래세율" size="small">
            {leaves
              .filter((leaf) => PARAM_LABELS[leaf.key]?.card === 'fees')
              .map((leaf) => (
                <Form.Item
                  key={leaf.key}
                  label={PARAM_LABELS[leaf.key].label}
                  name={['signal_params', leaf.group, leaf.field]}
                  rules={REQUIRED}
                >
                  <ParamField leaf={leaf} />
                </Form.Item>
              ))}
            <Typography.Text type="secondary">
              기본값은 임시입니다. 증권사와 거래소의 현재 요율로 확인해서 입력하세요. 재매수 목표가와 수량 증가분 계산에 쓰입니다.
            </Typography.Text>
          </Card>

          <Card title="갱신 주기" size="small">
            <Form.Item name="refresh_seconds" label="화면 자동 갱신" extra="끄면 상단의 새로고침 버튼으로 직접 조회합니다. 기본 60초.">
              <RefreshControl />
            </Form.Item>
          </Card>

          <Card title="알림" size="small">
            <Form.Item name="alert_cooldown_bars" label="알림 쿨다운" rules={REQUIRED} extra="같은 종목의 같은 신호는 이 봉 수 동안 다시 알리지 않습니다.">
              <NumberField id="alert_cooldown_bars" min={0} max={500} precision={0} unit="봉" />
            </Form.Item>
            <Form.Item label="텔레그램">
              <Space wrap>
                <Form.Item name={['channels', 'telegram']} valuePropName="checked" noStyle>
                  <Switch checkedChildren="켜짐" unCheckedChildren="꺼짐" aria-label="텔레그램 알림" />
                </Form.Item>
                {telegram && (
                  <Tag color={telegram.configured ? 'success' : 'warning'}>
                    {telegram.configured ? '서버에 연결 정보가 있음' : '서버에 토큰이 설정되지 않음'}
                  </Tag>
                )}
                <Button size="small" loading={testAlert.isPending} onClick={onTest}>
                  시험 알림 보내기
                </Button>
              </Space>
            </Form.Item>
          </Card>

          <Card title="프리셋" size="small">
            <Space.Compact style={{ width: '100%', maxWidth: 420, marginBottom: 12 }}>
              <Input
                placeholder="프리셋 이름"
                value={presetName}
                maxLength={40}
                onChange={(e) => setPresetName(e.target.value)}
                onPressEnter={onSavePreset}
              />
              <Button type="primary" loading={savePreset.isPending} disabled={!presetName.trim()} onClick={onSavePreset}>
                현재 설정 저장
              </Button>
            </Space.Compact>
            <List
              size="small"
              locale={{ emptyText: '저장한 프리셋이 없습니다' }}
              dataSource={settings.presets}
              renderItem={(preset) => (
                <List.Item
                  actions={[
                    <Popconfirm
                      key="load"
                      title="저장하지 않은 변경이 사라집니다. 불러올까요?"
                      disabled={!dirty}
                      onConfirm={() => onLoadPreset(preset.name)}
                    >
                      <Button size="small" onClick={() => !dirty && onLoadPreset(preset.name)}>
                        불러오기
                      </Button>
                    </Popconfirm>,
                    <Popconfirm key="delete" title="이 프리셋을 삭제할까요?" onConfirm={() => deletePreset.mutate(preset.name)}>
                      <Button size="small" danger>
                        삭제
                      </Button>
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta title={preset.name} description={dayjs(preset.updated_at).format('YYYY-MM-DD HH:mm')} />
                </List.Item>
              )}
            />
            <Typography.Text type="secondary">
              프리셋에는 지표 파라미터, 신호 봉 길이, 알림 쿨다운이 담깁니다. 알림 채널과 갱신 주기는 포함되지 않습니다.
            </Typography.Text>
          </Card>

          <ParamCollapse leaves={leaves} prefix={['signal_params']} />
        </Space>
      </Form>

      <div className="settings-actions">
        <Space>
          <Button type="primary" disabled={!dirty} loading={save.isPending} onClick={() => void onSave()}>
            저장
          </Button>
          <Button disabled={!dirty} onClick={() => reset(baseline)}>
            되돌리기
          </Button>
          <Popconfirm title="지표 파라미터를 PRD 기본값으로 되돌릴까요? (저장 전까지 적용되지 않습니다)" onConfirm={resetParamsToDefaults}>
            <Button>파라미터 기본값</Button>
          </Popconfirm>
          {dirty && <Tag color="processing">저장하지 않은 변경 있음</Tag>}
        </Space>
      </div>
    </>
  )
}
