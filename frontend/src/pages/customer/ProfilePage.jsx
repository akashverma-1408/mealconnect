import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addressApi, authApi } from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { ErrorBox, Field, QueryState } from '../../components/ui'
import { errorMessage } from '../../utils/format'

export default function ProfilePage() {
  const { user } = useAuth()
  return (
    <div className="stack" style={{ maxWidth: 720 }}>
      <h1>Your profile</h1>
      <ProfileForm key={user.id} />
      {user.role === 'customer' && <Addresses />}
      <PasswordForm />
    </div>
  )
}

function ProfileForm() {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const [form, setForm] = useState({ full_name: user.full_name, phone: user.phone || '' })
  const save = useMutation({
    mutationFn: () => authApi.updateMe({ full_name: form.full_name, phone: form.phone || null }),
    onSuccess: (me) => {
      setUser(me)
      toast.success('Profile saved')
    },
  })
  return (
    <section className="card">
      <h2>Details</h2>
      <p className="muted">{user.email} · {user.role.replace('_', ' ')}</p>
      <form className="form-grid form-grid--2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <Field label="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        <Field label="Phone" type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
        <ErrorBox error={save.error} />
        <div><button type="submit" className="btn btn--primary" disabled={save.isPending}>Save</button></div>
      </form>
    </section>
  )
}

function Addresses() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const addresses = useQuery({ queryKey: ['addresses'], queryFn: addressApi.list })
  const [adding, setAdding] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['addresses'] })
  const makeDefault = useMutation({
    mutationFn: (id) => addressApi.update(id, { is_default: true }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id) => addressApi.remove(id),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <section className="card">
      <div className="row row--between">
        <h2>Delivery addresses</h2>
        <button type="button" className="btn btn--ghost btn--small" onClick={() => setAdding((v) => !v)}>
          {adding ? 'Cancel' : '+ Add address'}
        </button>
      </div>
      {adding && <AddressForm onSaved={() => setAdding(false)} />}
      <QueryState query={addresses}>
        {(list) => (
          <ul className="list">
            {list.length === 0 && <li className="muted">No addresses yet.</li>}
            {list.map((a) => (
              <li key={a.id} className="row row--between">
                <div>
                  <strong>{a.label || 'Address'}</strong> {a.is_default && <span className="tag">Default</span>}
                  <div className="muted">{a.line1}{a.line2 ? `, ${a.line2}` : ''}, {a.city}, {a.state} {a.postal_code}</div>
                </div>
                <div className="row">
                  {!a.is_default && <button type="button" className="btn btn--small btn--ghost" onClick={() => makeDefault.mutate(a.id)}>Make default</button>}
                  <button type="button" className="btn btn--small btn--ghost" onClick={() => window.confirm('Delete this address?') && remove.mutate(a.id)}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </section>
  )
}

/** Reused by the cart page to add an address during checkout. */
export function AddressForm({ onSaved }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ label: 'Home', line1: '', line2: '', city: '', state: '', postal_code: '' })
  const save = useMutation({
    mutationFn: () => addressApi.create({ ...form, line2: form.line2 || null }),
    onSuccess: (address) => {
      queryClient.invalidateQueries({ queryKey: ['addresses'] })
      onSaved?.(address)
    },
  })
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })
  return (
    <form className="form-grid form-grid--2" onSubmit={(e) => { e.preventDefault(); save.mutate() }} style={{ margin: '12px 0' }}>
      <Field label="Label" value={form.label} onChange={set('label')} maxLength={30} />
      <Field label="Address line 1" required value={form.line1} onChange={set('line1')} />
      <Field label="Address line 2" value={form.line2} onChange={set('line2')} />
      <Field label="City" required value={form.city} onChange={set('city')} />
      <Field label="State" required value={form.state} onChange={set('state')} />
      <Field label="PIN code" required value={form.postal_code} onChange={set('postal_code')} />
      <ErrorBox error={save.error} />
      <div><button type="submit" className="btn btn--primary btn--small" disabled={save.isPending}>Save address</button></div>
    </form>
  )
}

function PasswordForm() {
  const toast = useToast()
  const [form, setForm] = useState({ current_password: '', new_password: '' })
  const save = useMutation({
    mutationFn: () => authApi.changePassword(form),
    onSuccess: () => {
      setForm({ current_password: '', new_password: '' })
      toast.success('Password changed. Other devices have been signed out.')
    },
  })
  return (
    <section className="card">
      <h2>Change password</h2>
      <form className="form-grid form-grid--2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <Field label="Current password" type="password" autoComplete="current-password" value={form.current_password}
          onChange={(e) => setForm({ ...form, current_password: e.target.value })} />
        <Field label="New password" type="password" autoComplete="new-password" value={form.new_password}
          onChange={(e) => setForm({ ...form, new_password: e.target.value })} hint="8+ characters, a letter and a digit" />
        <ErrorBox error={save.error} />
        <div><button type="submit" className="btn btn--primary" disabled={save.isPending || !form.current_password || !form.new_password}>Update password</button></div>
      </form>
    </section>
  )
}
