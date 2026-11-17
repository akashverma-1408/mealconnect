import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { useAuth } from '../../auth/AuthContext'
import { homeFor } from '../../utils/roles'
import { ErrorBox, Field } from '../../components/ui'
import { errorMessage } from '../../utils/format'

export default function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to={homeFor(user.role)} replace />

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const me = await login(form.email, form.password)
      const from = location.state?.from
      navigate(from && me.role === 'customer' ? from : homeFor(me.role), { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  return (
    <div className="card auth-card">
      <h1>Welcome back</h1>
      <p className="muted">Log in to order food or manage your restaurant.</p>
      <ErrorBox error={error} />
      <form className="form-grid" onSubmit={handleSubmit} noValidate>
        <Field label="Email" type="email" autoComplete="email" required value={form.email} onChange={set('email')} />
        <Field label="Password" type="password" autoComplete="current-password" required value={form.password} onChange={set('password')} />
        <button type="submit" className="btn btn--primary btn--block" disabled={submitting || !form.email || !form.password}>
          {submitting ? 'Logging in…' : 'Log in'}
        </button>
      </form>
      <p className="muted" style={{ marginTop: 16 }}>
        New here? <Link to="/register">Create an account</Link>
      </p>
      {import.meta.env.DEV && (
        <details className="demo-accounts">
          <summary>Demo accounts (development)</summary>
          <p>Password for all: <code>DemoPass123</code></p>
          <p><code>asha@example.com</code> customer · <code>owner.spice@example.com</code> owner · <code>admin@example.com</code> admin</p>
        </details>
      )}
    </div>
  )
}
