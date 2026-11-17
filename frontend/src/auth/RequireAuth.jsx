import { Navigate, Outlet, useLocation } from 'react-router'
import { useAuth } from './AuthContext'
import { Spinner } from '../components/ui'
import { homeFor } from '../utils/roles'

/** Route guard: only logged-in users with one of `roles` may see the nested routes. */
export default function RequireAuth({ roles }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <Spinner label="Checking your session" />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  if (roles && !roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />
  return <Outlet />
}
