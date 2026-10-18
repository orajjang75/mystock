import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { errorMessage, isUnauthorized } from '../api/client'
import { useLogin, useMe } from '../api/queries'
import { Disclaimer } from '../components/Disclaimer'

interface LoginValues {
  username: string
  password: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { data: user } = useMe()
  const login = useLogin()
  const from = (location.state as { from?: string } | null)?.from ?? '/'

  if (user) return <Navigate to={from} replace />

  return (
    <div className="centered-screen login-screen">
      <Card className="login-card">
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          KOSPI 턴어라운드 알림
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          후보 종목과 보유 종목의 매도·재매수 시점을 알려 주는 알림 전용 앱입니다.
        </Typography.Paragraph>
        {login.isError && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={
              isUnauthorized(login.error) ? '아이디 또는 비밀번호가 올바르지 않습니다' : errorMessage(login.error)
            }
          />
        )}
        <Form<LoginValues>
          layout="vertical"
          requiredMark={false}
          onFinish={(values) =>
            login.mutate(values, { onSuccess: () => navigate(from, { replace: true }) })
          }
        >
          <Form.Item label="아이디" name="username" rules={[{ required: true, message: '아이디를 입력하세요' }]}>
            <Input prefix={<UserOutlined />} autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item label="비밀번호" name="password" rules={[{ required: true, message: '비밀번호를 입력하세요' }]}>
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={login.isPending}>
            로그인
          </Button>
        </Form>
      </Card>
      <Disclaimer />
    </div>
  )
}
