import { useState } from 'react'
import { Field } from '../../components/ui'

const EMPTY = {
  name: '', cuisine: '', city: '', address: '', phone: '', description: '',
  delivery_fee: '0', min_order_amount: '0', opens_at: '', closes_at: '', is_veg_only: false,
}

/** Shared by "register restaurant" and "settings". Sends only what the API expects. */
export function RestaurantForm({ initial, onSubmit, submitLabel = 'Save', pending }) {
  const [form, setForm] = useState(() => ({
    ...EMPTY,
    ...Object.fromEntries(Object.entries(initial || {}).map(([k, v]) => [k, v ?? ''])),
  }))
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  function handleSubmit(e) {
    e.preventDefault()
    onSubmit({
      name: form.name, cuisine: form.cuisine, city: form.city, address: form.address,
      phone: form.phone || null, description: form.description || null,
      delivery_fee: form.delivery_fee || '0', min_order_amount: form.min_order_amount || '0',
      opens_at: form.opens_at || null, closes_at: form.closes_at || null, is_veg_only: form.is_veg_only,
    })
  }

  return (
    <form className="form-grid form-grid--2" onSubmit={handleSubmit}>
      <Field label="Restaurant name" required minLength={2} value={form.name} onChange={set('name')} />
      <Field label="Cuisine" required placeholder="e.g. North Indian" value={form.cuisine} onChange={set('cuisine')} />
      <Field label="City" required value={form.city} onChange={set('city')} />
      <Field label="Phone" type="tel" value={form.phone} onChange={set('phone')} />
      <Field label="Address" required minLength={5} value={form.address} onChange={set('address')} />
      <Field label="Delivery fee (₹)" type="number" min="0" step="0.01" value={form.delivery_fee} onChange={set('delivery_fee')} />
      <Field label="Minimum order (₹)" type="number" min="0" step="0.01" value={form.min_order_amount} onChange={set('min_order_amount')} />
      <Field label="Opens at" type="time" value={(form.opens_at || '').slice(0, 5)} onChange={set('opens_at')} />
      <Field label="Closes at" type="time" value={(form.closes_at || '').slice(0, 5)} onChange={set('closes_at')} />
      <Field as="textarea" label="Description" maxLength={2000} value={form.description} onChange={set('description')} />
      <label className="checkbox"><input type="checkbox" checked={form.is_veg_only} onChange={set('is_veg_only')} /> Pure vegetarian</label>
      <div><button type="submit" className="btn btn--primary" disabled={pending}>{pending ? 'Saving…' : submitLabel}</button></div>
    </form>
  )
}
