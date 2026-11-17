import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '../../api/endpoints'
import { useToast } from '../../components/Toast'
import { BarChart, EmptyState, Field, Modal, Pagination, QueryState, Stat, StatusBadge } from '../../components/ui'
import useDebounce from '../../hooks/useDebounce'
import { dateTime, errorMessage, money, statusLabel } from '../../utils/format'

const TABS = { overview: 'Overview', restaurants: 'Restaurants', users: 'Users', orders: 'Orders', complaints: 'Complaints', audit: 'Audit log' }

export default function AdminPage() {
  const [params, setParams] = useSearchParams()
  const tab = TABS[params.get('tab')] ? params.get('tab') : 'overview'
  return (
    <>
      <div className="page-header"><h1>Admin console</h1></div>
      <div className="tabs" role="tablist">
        {Object.entries(TABS).map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setParams({ tab: key })}>{label}</button>
        ))}
      </div>
      {tab === 'overview' && <Overview />}
      {tab === 'restaurants' && <Restaurants />}
      {tab === 'users' && <Users />}
      {tab === 'orders' && <Orders />}
      {tab === 'complaints' && <Complaints />}
      {tab === 'audit' && <Audit />}
    </>
  )
}

/** Small helper: a paginated admin list with its own page state. */
function usePaged(key, fn, filters) {
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: ['admin', key, filters, page],
    queryFn: () => fn({ ...filters, page, size: 15 }),
    placeholderData: keepPreviousData,
  })
  return { query, page, setPage }
}

function Overview() {
  const analytics = useQuery({ queryKey: ['admin', 'analytics'], queryFn: () => adminApi.analytics() })
  return (
    <QueryState query={analytics}>
      {(a) => (
        <div className="stack">
          <div className="grid grid--4">
            <Stat label="GMV (30 days)" value={money(a.gmv)} />
            <Stat label="Paid orders" value={a.order_count} />
            <Stat label="Avg order value" value={money(a.average_order_value)} />
            <Stat label="New users" value={a.new_users} />
          </div>
          <section className="card"><h2>Daily GMV</h2><BarChart points={a.daily} format={money} label="Daily GMV" /></section>
          <div className="grid grid--3">
            <section className="card"><h3>Users by role</h3>{Object.entries(a.users_by_role).map(([k, v]) => <div key={k} className="summary-line"><span>{k.replace('_', ' ')}</span><strong>{v}</strong></div>)}</section>
            <section className="card"><h3>Restaurants</h3>{Object.entries(a.restaurants_by_status).map(([k, v]) => <div key={k} className="summary-line"><span>{k}</span><strong>{v}</strong></div>)}</section>
            <section className="card"><h3>Complaints</h3>{Object.keys(a.complaints_by_status).length === 0 && <p className="muted">None</p>}{Object.entries(a.complaints_by_status).map(([k, v]) => <div key={k} className="summary-line"><span>{k.replace('_', ' ')}</span><strong>{v}</strong></div>)}</section>
          </div>
          <section className="card">
            <h2>Top restaurants</h2>
            <table><thead><tr><th>Restaurant</th><th>Orders</th><th>Revenue</th></tr></thead>
              <tbody>{a.top_restaurants.map((r) => <tr key={r.restaurant_id}><td>{r.name}</td><td>{r.orders}</td><td>{money(r.revenue)}</td></tr>)}</tbody></table>
          </section>
        </div>
      )}
    </QueryState>
  )
}

/** Modal asking for an optional/required reason before a moderation action. */
function ReasonModal({ action, onClose, onConfirm, pending }) {
  const [reason, setReason] = useState('')
  if (!action) return null
  return (
    <Modal open title={action.title} onClose={onClose}>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); onConfirm(reason.trim() || null) }}>
        <Field as="textarea" label={action.reasonRequired ? 'Reason (required)' : 'Reason (optional)'} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="submit" className={`btn ${action.danger ? 'btn--danger' : 'btn--primary'}`} disabled={pending || (action.reasonRequired && !reason.trim())}>Confirm</button>
      </form>
    </Modal>
  )
}

function Restaurants() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [status, setStatus] = useState('pending')
  const [action, setAction] = useState(null)
  const { query, page, setPage } = usePaged('restaurants', adminApi.restaurants, { status: status || undefined })
  const mutate = useMutation({
    mutationFn: ({ id, next, reason }) => adminApi.setRestaurantStatus(id, { status: next, reason }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['admin'] })
      queryClient.invalidateQueries({ queryKey: ['restaurants'] })
      toast.success(`${r.name} is now ${r.status}`)
      setAction(null)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const ask = (r, next) => setAction({ r, next, title: `${next[0].toUpperCase() + next.slice(1)} ${r.name}?`,
    reasonRequired: next !== 'approved', danger: next !== 'approved' })

  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        {['pending', 'approved', 'suspended', 'rejected', ''].map((s) => (
          <button key={s || 'all'} type="button" className={`btn btn--small ${status === s ? 'btn--primary' : 'btn--ghost'}`} onClick={() => { setStatus(s); setPage(1) }}>{s || 'All'}</button>
        ))}
      </div>
      <QueryState query={query}>
        {(data) => data.items.length === 0 ? <EmptyState title="Nothing to review" /> : (
          <div className="card card--flush table-wrap">
            <table>
              <thead><tr><th>Restaurant</th><th>City</th><th>Owner</th><th>Registered</th><th>Status</th><th /></tr></thead>
              <tbody>{data.items.map((r) => (
                <tr key={r.id}>
                  <td><strong>{r.name}</strong><div className="muted">{r.cuisine}</div></td>
                  <td>{r.city}</td><td>#{r.owner_id}</td><td>{dateTime(r.created_at)}</td>
                  <td><StatusBadge status={r.status.toUpperCase()} /></td>
                  <td className="right"><div className="row" style={{ justifyContent: 'flex-end' }}>
                    {r.status !== 'approved' && <button type="button" className="btn btn--small btn--success" onClick={() => ask(r, 'approved')}>Approve</button>}
                    {r.status === 'pending' && <button type="button" className="btn btn--small btn--ghost" onClick={() => ask(r, 'rejected')}>Reject</button>}
                    {r.status === 'approved' && <button type="button" className="btn btn--small btn--danger" onClick={() => ask(r, 'suspended')}>Suspend</button>}
                  </div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </QueryState>
      <Pagination page={page} pages={query.data?.pages} onChange={setPage} />
      <ReasonModal action={action} pending={mutate.isPending} onClose={() => setAction(null)}
        onConfirm={(reason) => mutate.mutate({ id: action.r.id, next: action.next, reason })} />
    </>
  )
}

function Users() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('')
  const [action, setAction] = useState(null)
  const debouncedQ = useDebounce(q)
  const { query, page, setPage } = usePaged('users', adminApi.users, { q: debouncedQ || undefined, role: role || undefined })
  const mutate = useMutation({
    mutationFn: ({ id, status, reason }) => adminApi.setUserStatus(id, { status, reason }),
    onSuccess: (u) => { queryClient.invalidateQueries({ queryKey: ['admin', 'users'] }); toast.success(`${u.email} is now ${u.status}`); setAction(null) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <label htmlFor="user-q" className="sr-only">Search users</label>
        <input id="user-q" placeholder="Search name or email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} style={{ maxWidth: 280 }} />
        <select aria-label="Role" value={role} onChange={(e) => { setRole(e.target.value); setPage(1) }} style={{ maxWidth: 200 }}>
          <option value="">All roles</option><option value="customer">Customers</option><option value="restaurant_owner">Owners</option><option value="admin">Admins</option>
        </select>
      </div>
      <QueryState query={query}>
        {(data) => (
          <div className="card card--flush table-wrap">
            <table>
              <thead><tr><th>User</th><th>Role</th><th>Joined</th><th>Status</th><th /></tr></thead>
              <tbody>{data.items.map((u) => (
                <tr key={u.id}>
                  <td><strong>{u.full_name}</strong><div className="muted">{u.email}</div></td>
                  <td>{u.role.replace('_', ' ')}</td><td>{dateTime(u.created_at)}</td>
                  <td><StatusBadge status={u.status.toUpperCase()} /></td>
                  <td className="right">{u.role !== 'admin' && (u.status === 'active'
                    ? <button type="button" className="btn btn--small btn--danger" onClick={() => setAction({ u, status: 'suspended', title: `Suspend ${u.email}?`, reasonRequired: true, danger: true })}>Suspend</button>
                    : <button type="button" className="btn btn--small btn--success" onClick={() => mutate.mutate({ id: u.id, status: 'active', reason: null })}>Reactivate</button>)}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </QueryState>
      <Pagination page={page} pages={query.data?.pages} onChange={setPage} />
      <ReasonModal action={action} pending={mutate.isPending} onClose={() => setAction(null)}
        onConfirm={(reason) => mutate.mutate({ id: action.u.id, status: action.status, reason })} />
    </>
  )
}

function Orders() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [status, setStatus] = useState('')
  const [action, setAction] = useState(null)
  const { query, page, setPage } = usePaged('orders', adminApi.orders, { status: status || undefined })
  const cancel = useMutation({
    mutationFn: ({ id, reason }) => adminApi.cancelOrder(id, reason),
    onSuccess: (o) => { queryClient.invalidateQueries({ queryKey: ['admin', 'orders'] }); toast.success(`Order #${o.id} cancelled`); setAction(null) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const FINAL = ['DELIVERED', 'REJECTED', 'CANCELLED']
  return (
    <>
      <select aria-label="Order status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} style={{ maxWidth: 240, marginBottom: 12 }}>
        <option value="">All statuses</option>
        {['PENDING_PAYMENT', 'PLACED', 'ACCEPTED', 'PREPARING', 'OUT_FOR_DELIVERY', 'DELIVERED', 'REJECTED', 'CANCELLED'].map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
      </select>
      <QueryState query={query}>
        {(data) => (
          <div className="card card--flush table-wrap">
            <table>
              <thead><tr><th>Order</th><th>Restaurant</th><th>Placed</th><th>Total</th><th>Status</th><th /></tr></thead>
              <tbody>{data.items.map((o) => (
                <tr key={o.id}>
                  <td>#{o.id}</td><td>{o.restaurant.name}</td><td>{dateTime(o.created_at)}</td><td>{money(o.total)}</td>
                  <td><StatusBadge status={o.status} /></td>
                  <td className="right">{!FINAL.includes(o.status) && (
                    <button type="button" className="btn btn--small btn--danger" onClick={() => setAction({ o, title: `Force-cancel order #${o.id}?`, danger: true })}>Cancel</button>)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </QueryState>
      <Pagination page={page} pages={query.data?.pages} onChange={setPage} />
      <ReasonModal action={action} pending={cancel.isPending} onClose={() => setAction(null)}
        onConfirm={(reason) => cancel.mutate({ id: action.o.id, reason })} />
    </>
  )
}

function Complaints() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [status, setStatus] = useState('open')
  const [resolving, setResolving] = useState(null)
  const [note, setNote] = useState('')
  const { query, page, setPage } = usePaged('complaints', adminApi.complaints, { status: status || undefined })
  const update = useMutation({
    mutationFn: ({ id, body }) => adminApi.updateComplaint(id, body),
    onSuccess: (c) => { queryClient.invalidateQueries({ queryKey: ['admin'] }); toast.success(`Complaint #${c.id}: ${c.status.replace('_', ' ')}`); setResolving(null); setNote('') },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        {['open', 'in_progress', 'resolved', 'rejected', ''].map((s) => (
          <button key={s || 'all'} type="button" className={`btn btn--small ${status === s ? 'btn--primary' : 'btn--ghost'}`} onClick={() => { setStatus(s); setPage(1) }}>{s ? s.replace('_', ' ') : 'All'}</button>
        ))}
      </div>
      <QueryState query={query}>
        {(data) => data.items.length === 0 ? <EmptyState title="No complaints here" /> : (
          <div className="stack">{data.items.map((c) => (
            <article key={c.id} className="card">
              <div className="row row--between"><h3>#{c.id} · {c.subject}</h3><StatusBadge status={c.status.toUpperCase()} /></div>
              <p>{c.description}</p>
              <small className="muted">User #{c.raised_by}{c.order_id && ` · Order #${c.order_id}`} · {dateTime(c.created_at)}</small>
              {c.resolution_note && <div className="alert alert--info" style={{ marginTop: 8 }}>{c.resolution_note}</div>}
              {['open', 'in_progress'].includes(c.status) && (
                <div className="row" style={{ marginTop: 10 }}>
                  {c.status === 'open' && <button type="button" className="btn btn--small" onClick={() => update.mutate({ id: c.id, body: { status: 'in_progress' } })}>Start working</button>}
                  <button type="button" className="btn btn--small btn--success" onClick={() => setResolving({ c, next: 'resolved' })}>Resolve</button>
                  <button type="button" className="btn btn--small btn--ghost" onClick={() => setResolving({ c, next: 'rejected' })}>Reject</button>
                </div>
              )}
            </article>
          ))}</div>
        )}
      </QueryState>
      <Pagination page={page} pages={query.data?.pages} onChange={setPage} />
      <Modal open={!!resolving} title={`${resolving?.next === 'resolved' ? 'Resolve' : 'Reject'} complaint #${resolving?.c.id}`} onClose={() => setResolving(null)}>
        <form className="form-grid" onSubmit={(e) => { e.preventDefault(); update.mutate({ id: resolving.c.id, body: { status: resolving.next, resolution_note: note.trim() } }) }}>
          <Field as="textarea" label="Resolution note (sent to the customer)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="submit" className="btn btn--primary" disabled={update.isPending || note.trim().length < 3}>Save</button>
        </form>
      </Modal>
    </>
  )
}

function Audit() {
  const { query, page, setPage } = usePaged('audit', adminApi.auditLogs, {})
  return (
    <>
      <QueryState query={query}>
        {(data) => data.items.length === 0 ? <EmptyState title="No admin actions yet" /> : (
          <div className="card card--flush table-wrap">
            <table>
              <thead><tr><th>When</th><th>Admin</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
              <tbody>{data.items.map((l) => (
                <tr key={l.id}>
                  <td>{dateTime(l.created_at)}</td><td>#{l.actor_id}</td><td><code>{l.action}</code></td>
                  <td>{l.entity_type} #{l.entity_id}</td>
                  <td className="muted"><small>{l.details ? Object.entries(l.details).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join(' · ') : ''}</small></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </QueryState>
      <Pagination page={page} pages={query.data?.pages} onChange={setPage} />
    </>
  )
}
