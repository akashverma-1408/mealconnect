import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router'
import { useAuth } from '../../auth/AuthContext'
import { homeFor } from '../../utils/roles'
import { ErrorBox, Field } from '../../components/ui'
import { errorMessage } from '../../utils/format'
import { validateRegistration } from '../../utils/validation'

export default function RegisterPage() {
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', password: '', role: 'customer' })
  const [errors, setErrors] = useState({})
  const [serverError, setServerError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to={homeFor(user.role)} replace />

  async function handleSubmit(e) {
    e.preventDefault()
    const found = validateRegistration(form)
    setErrors(found)
    if (Object.keys(found).length) return
    setSubmitting(true)
    setServerError(null)
    try {
      const me = await register({ ...form, phone: form.phone || null })
      navigate(homeFor(me.role), { replace: true })
    } catch (err) {
      setServerError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })

  return (
    <div className="card auth-card">
      <h1>Create your account</h1>
      <ErrorBox error={serverError} />
      <form className="form-grid" onSubmit={handleSubmit} noValidate>
        <fieldset className="row" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="sr-only">Account type</legend>
          <label className="checkbox"><input type="radio" name="role" value="customer" checked={form.role === 'customer'} onChange={set('role')} /> I want to order food</label>
          <label className="checkbox"><input type="radio" name="role" value="restaurant_owner" checked={form.role === 'restaurant_owner'} onChange={set('role')} /> I own a restaurant</label>
        </fieldset>
        <Field label="Full name" autoComplete="name" value={form.full_name} onChange={set('full_name')} error={errors.full_name} />
        <Field label="Email" type="email" autoComplete="email" value={form.email} onChange={set('email')} error={errors.email} />
        <Field label="Phone (optional)" type="tel" autoComplete="tel" value={form.phone} onChange={set('phone')} error={errors.phone} />
        <Field label="Password" type="password" autoComplete="new-password" value={form.password} onChange={set('password')}
          error={errors.password} hint="At least 8 characters with a letter and a digit" />
        <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
          {submitting ? 'Creating account…' : 'Create account'}
        </button>
      </form>
      <p className="muted" style={{ marginTop: 16 }}>Already registered? <Link to="/login">Log in</Link></p>
    </div>
  )
}
