import { Spin } from 'antd'
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useMe } from '../api/queries'

/** Route guard: a signed-out visitor is sent to /login and returns here after signing in. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { data: user, isPending, isError } = useMe()

  if (isPending) {
    return (
      <div className="centered-screen">
        <Spin size="large" />
      </div>
    )
  }
  if (isError || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}
