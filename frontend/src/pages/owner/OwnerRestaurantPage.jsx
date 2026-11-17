import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ownerApi } from '../../api/endpoints'
import { useToast } from '../../components/Toast'
import {
  BarChart, EmptyState, ErrorBox, Field, Modal, Pagination, QueryState, Stat, StatusBadge, VegMark,
} from '../../components/ui'
import { dateTime, errorMessage, money, OWNER_NEXT, statusLabel } from '../../utils/format'
import { RestaurantForm } from './RestaurantForm'

const TABS = ['orders', 'menu', 'settings', 'analytics']

export default function OwnerRestaurantPage() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const tab = TABS.includes(params.get('tab')) ? params.get('tab') : 'orders'
  const restaurant = useQuery({ queryKey: ['owner', 'restaurant', id], queryFn: () => ownerApi.restaurant(id) })

  return (
    <QueryState query={restaurant}>
      {(r) => (
        <>
          <div className="page-header">
            <div>
              <Link to="/owner" className="muted">← My restaurants</Link>
              <h1>{r.name}</h1>
              <div className="row"><StatusBadge status={r.status.toUpperCase()} /><OpenToggle restaurant={r} /></div>
            </div>
          </div>
          {r.status !== 'approved' && (
            <div className="alert alert--warn">
              {r.status === 'pending' ? 'Waiting for admin approval — customers cannot see this restaurant yet.' : `Status: ${r.status}. ${r.status_reason || ''}`}
            </div>
          )}
          <div className="tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setParams({ tab: t })}>
                {t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
          {tab === 'orders' && <OrdersTab rid={id} />}
          {tab === 'menu' && <MenuTab rid={id} />}
          {tab === 'settings' && <SettingsTab restaurant={r} />}
          {tab === 'analytics' && <AnalyticsTab rid={id} />}
        </>
      )}
    </QueryState>
  )
}

function OpenToggle({ restaurant }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const toggle = useMutation({
    mutationFn: () => ownerApi.updateRestaurant(restaurant.id, { is_open: !restaurant.is_open }),
    onSuccess: (r) => {
      queryClient.setQueryData(['owner', 'restaurant', String(r.id)], r)
      queryClient.invalidateQueries({ queryKey: ['owner', 'restaurants'] })
      toast.success(r.is_open ? 'Now accepting orders' : 'Marked as closed')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <button type="button" className={`btn btn--small ${restaurant.is_open ? 'btn--success' : ''}`} disabled={toggle.isPending} onClick={() => toggle.mutate()}>
      {restaurant.is_open ? '● Open — click to close' : '○ Closed — click to open'}
    </button>
  )
}

// ================================================================== orders
const ORDER_FILTERS = ['', 'PLACED', 'ACCEPTED', 'PREPARING', 'OUT_FOR_DELIVERY', 'DELIVERED', 'REJECTED', 'CANCELLED']

function OrdersTab({ rid }) {
  const [status, setStatus] = useState('PLACED')
  const [page, setPage] = useState(1)
  const [openId, setOpenId] = useState(null)
  const orders = useQuery({
    queryKey: ['owner', 'orders', rid, status, page],
    queryFn: () => ownerApi.orders(rid, { status: status || undefined, page, size: 15 }),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000, // new orders appear without reloading
  })
  return (
    <>
      <div className="row" style={{ marginBottom: 14 }}>
        {ORDER_FILTERS.map((s) => (
          <button key={s || 'all'} type="button" className={`btn btn--small ${status === s ? 'btn--primary' : 'btn--ghost'}`}
            onClick={() => { setStatus(s); setPage(1) }}>{s ? statusLabel(s) : 'All'}</button>
        ))}
      </div>
      <QueryState query={orders}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title="No orders here">{status === 'PLACED' ? 'New paid orders will appear here automatically.' : null}</EmptyState>
          ) : (
            <div className="card card--flush table-wrap">
              <table>
                <thead><tr><th>Order</th><th>Placed</th><th>Items</th><th>Total</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {data.items.map((o) => (
                    <tr key={o.id}>
                      <td>#{o.id}</td>
                      <td>{dateTime(o.created_at)}</td>
                      <td>{o.item_count}</td>
                      <td>{money(o.total)}</td>
                      <td><StatusBadge status={o.status} /></td>
                      <td className="right"><button type="button" className="btn btn--small" onClick={() => setOpenId(o.id)}>Manage</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </QueryState>
      <Pagination page={orders.data?.page} pages={orders.data?.pages} onChange={setPage} />
      {openId && <OwnerOrderModal orderId={openId} onClose={() => setOpenId(null)} />}
    </>
  )
}

function OwnerOrderModal({ orderId, onClose }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [reason, setReason] = useState('')
  const order = useQuery({ queryKey: ['owner', 'order', orderId], queryFn: () => ownerApi.order(orderId) })
  const act = useMutation({
    mutationFn: ({ action, value }) =>
      action === 'accept' ? ownerApi.accept(orderId)
        : action === 'reject' ? ownerApi.reject(orderId, value)
          : ownerApi.setStatus(orderId, value),
    onSuccess: (o) => {
      queryClient.setQueryData(['owner', 'order', orderId], o)
      queryClient.invalidateQueries({ queryKey: ['owner', 'orders'] })
      toast.success(`Order #${o.id}: ${statusLabel(o.status)}`)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <Modal open title={`Order #${orderId}`} onClose={onClose}>
      <QueryState query={order}>
        {(o) => (
          <div className="stack">
            <div className="row row--between"><StatusBadge status={o.status} /><strong>{money(o.total)}</strong></div>
            <ul className="list">
              {o.items.map((i) => <li key={i.menu_item_id}>{i.quantity} × {i.item_name}</li>)}
            </ul>
            <p className="muted">Deliver to: {o.delivery_address.line1}, {o.delivery_address.city} {o.delivery_address.postal_code}</p>
            {o.notes && <div className="alert alert--info">Customer note: {o.notes}</div>}
            {o.status === 'PLACED' && (
              <>
                <button type="button" className="btn btn--success" disabled={act.isPending} onClick={() => act.mutate({ action: 'accept' })}>Accept order</button>
                <Field label="Reason for rejecting" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Item out of stock" />
                <button type="button" className="btn btn--danger" disabled={act.isPending || reason.trim().length < 3}
                  onClick={() => act.mutate({ action: 'reject', value: reason.trim() })}>Reject & refund</button>
              </>
            )}
            {OWNER_NEXT[o.status] && (
              <button type="button" className="btn btn--primary" disabled={act.isPending}
                onClick={() => act.mutate({ action: 'status', value: OWNER_NEXT[o.status] })}>
                Mark as {statusLabel(OWNER_NEXT[o.status]).toLowerCase()}
              </button>
            )}
          </div>
        )}
      </QueryState>
    </Modal>
  )
}

// ================================================================== menu
function MenuTab({ rid }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const menu = useQuery({ queryKey: ['owner', 'menu', rid], queryFn: () => ownerApi.menu(rid) })
  const [editing, setEditing] = useState(null) // null | {} (new) | item
  const [category, setCategory] = useState('')
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['owner', 'menu', rid] })
  const onError = (e) => toast.error(errorMessage(e))

  const addCategory = useMutation({
    mutationFn: () => ownerApi.createCategory(rid, { name: category.trim() }),
    onSuccess: () => { setCategory(''); refresh() },
    onError,
  })
  const deleteCategory = useMutation({ mutationFn: (cid) => ownerApi.deleteCategory(rid, cid), onSuccess: refresh, onError })
  const toggle = useMutation({
    mutationFn: (item) => ownerApi.setAvailability(rid, item.id, !item.is_available),
    onSuccess: (item) => { refresh(); toast.success(`${item.name} is now ${item.is_available ? 'available' : 'sold out'}`) },
    onError,
  })
  const remove = useMutation({ mutationFn: (item) => ownerApi.deleteItem(rid, item.id), onSuccess: refresh, onError })

  return (
    <QueryState query={menu}>
      {({ sections }) => {
        const categories = sections.filter((s) => s.category).map((s) => s.category)
        return (
          <div className="stack">
            <div className="row">
              <button type="button" className="btn btn--primary" onClick={() => setEditing({})}>+ Add dish</button>
              <form className="row" onSubmit={(e) => { e.preventDefault(); if (category.trim().length >= 2) addCategory.mutate() }}>
                <label htmlFor="new-cat" className="sr-only">New category name</label>
                <input id="new-cat" placeholder="New category" value={category} onChange={(e) => setCategory(e.target.value)} style={{ width: 180 }} />
                <button type="submit" className="btn btn--ghost" disabled={category.trim().length < 2}>Add category</button>
              </form>
            </div>
            {sections.length === 0 && <EmptyState title="Your menu is empty">Add categories and dishes to start selling.</EmptyState>}
            {sections.map((s) => (
              <section key={s.category?.id ?? 'none'} className="card">
                <div className="row row--between">
                  <h2>{s.category?.name ?? 'Uncategorized'}</h2>
                  {s.category && (
                    <button type="button" className="btn btn--ghost btn--small"
                      onClick={() => window.confirm(`Delete category "${s.category.name}"? Its dishes are kept.`) && deleteCategory.mutate(s.category.id)}>
                      Delete category
                    </button>
                  )}
                </div>
                {s.items.length === 0 && <p className="muted">No dishes in this category.</p>}
                <ul className="list">
                  {s.items.map((item) => (
                    <li key={item.id} className={`menu-item ${item.is_available ? '' : 'menu-item--off'}`}>
                      <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                        <VegMark veg={item.is_veg} />
                        <div><strong>{item.name}</strong><div>{money(item.price)}</div></div>
                      </div>
                      <div className="row">
                        <label className="checkbox">
                          <input type="checkbox" checked={item.is_available} onChange={() => toggle.mutate(item)} /> Available
                        </label>
                        <button type="button" className="btn btn--small btn--ghost" onClick={() => setEditing(item)}>Edit</button>
                        <button type="button" className="btn btn--small btn--ghost"
                          onClick={() => window.confirm(`Delete ${item.name}?`) && remove.mutate(item)}>Delete</button>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
            {editing && <ItemModal rid={rid} item={editing} categories={categories} onClose={() => setEditing(null)} onSaved={refresh} />}
          </div>
        )
      }}
    </QueryState>
  )
}

function ItemModal({ rid, item, categories, onClose, onSaved }) {
  const toast = useToast()
  const isNew = !item.id
  const [form, setForm] = useState({
    name: item.name || '', price: item.price || '', description: item.description || '',
    is_veg: item.is_veg ?? true, category_id: item.category_id ?? '',
  })
  const save = useMutation({
    mutationFn: () => {
      const body = { ...form, description: form.description || null, category_id: form.category_id ? Number(form.category_id) : null }
      return isNew ? ownerApi.createItem(rid, body) : ownerApi.updateItem(rid, item.id, body)
    },
    onSuccess: (saved) => { onSaved(); toast.success(`${saved.name} saved`); onClose() },
  })
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  return (
    <Modal open title={isNew ? 'Add dish' : `Edit ${item.name}`} onClose={onClose}>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <Field label="Name" required minLength={2} value={form.name} onChange={set('name')} />
        <Field label="Price (₹)" type="number" min="0.01" step="0.01" required value={form.price} onChange={set('price')} />
        <Field as="select" label="Category" value={form.category_id} onChange={set('category_id')}>
          <option value="">Uncategorized</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Field>
        <Field as="textarea" label="Description" maxLength={1000} value={form.description} onChange={set('description')} />
        <label className="checkbox"><input type="checkbox" checked={form.is_veg} onChange={set('is_veg')} /> Vegetarian</label>
        <ErrorBox error={save.error} />
        <button type="submit" className="btn btn--primary" disabled={save.isPending}>Save dish</button>
      </form>
    </Modal>
  )
}

// ================================================================== settings
function SettingsTab({ restaurant }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const save = useMutation({
    mutationFn: (body) => ownerApi.updateRestaurant(restaurant.id, body),
    onSuccess: (r) => {
      queryClient.setQueryData(['owner', 'restaurant', String(r.id)], r)
      queryClient.invalidateQueries({ queryKey: ['owner', 'restaurants'] })
      toast.success('Restaurant updated')
    },
  })
  return (
    <section className="card">
      <ErrorBox error={save.error} />
      <RestaurantForm initial={restaurant} pending={save.isPending} onSubmit={(body) => save.mutate(body)} />
    </section>
  )
}

// ================================================================== analytics
function AnalyticsTab({ rid }) {
  const [range, setRange] = useState({ date_from: '', date_to: '' })
  const analytics = useQuery({
    queryKey: ['owner', 'analytics', rid, range],
    queryFn: () => ownerApi.analytics(rid, { date_from: range.date_from || undefined, date_to: range.date_to || undefined }),
  })
  return (
    <div className="stack">
      <div className="row">
        <Field label="From" type="date" value={range.date_from} onChange={(e) => setRange({ ...range, date_from: e.target.value })} />
        <Field label="To" type="date" value={range.date_to} onChange={(e) => setRange({ ...range, date_to: e.target.value })} />
      </div>
      <QueryState query={analytics}>
        {(a) => (
          <>
            <div className="grid grid--4">
              <Stat label="Revenue" value={money(a.revenue)} sub={`${a.date_from} → ${a.date_to}`} />
              <Stat label="Paid orders" value={a.order_count} />
              <Stat label="Avg order value" value={money(a.average_order_value)} />
              <Stat label="Rejected / cancelled" value={(a.orders_by_status.REJECTED || 0) + (a.orders_by_status.CANCELLED || 0)} />
            </div>
            <section className="card">
              <h2>Daily revenue</h2>
              <BarChart points={a.daily} format={money} label="Daily revenue" />
            </section>
            <section className="card">
              <h2>Top dishes</h2>
              {a.top_items.length === 0 ? <p className="muted">No sales in this period.</p> : (
                <table>
                  <thead><tr><th>Dish</th><th>Sold</th><th>Revenue</th></tr></thead>
                  <tbody>{a.top_items.map((t) => <tr key={t.menu_item_id}><td>{t.name}</td><td>{t.quantity}</td><td>{money(t.revenue)}</td></tr>)}</tbody>
                </table>
              )}
            </section>
          </>
        )}
      </QueryState>
    </div>
  )
}
