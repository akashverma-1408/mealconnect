import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { complaintApi, orderApi } from '../../api/endpoints'
import { useToast } from '../../components/Toast'
import { ErrorBox, Field, Modal, QueryState, StatusBadge } from '../../components/ui'
import { dateTime, errorMessage, money, ORDER_FLOW, statusLabel } from '../../utils/format'

const ACTIVE = ['PLACED', 'ACCEPTED', 'PREPARING', 'OUT_FOR_DELIVERY']

export default function OrderDetailPage() {
  const { id } = useParams()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [reviewOpen, setReviewOpen] = useState(false)
  const [complaintOpen, setComplaintOpen] = useState(false)

  const order = useQuery({
    queryKey: ['order', id],
    queryFn: () => orderApi.get(id),
    // Live tracking: poll every 10 s while the order is moving, stop when it is final.
    refetchInterval: (q) => (ACTIVE.includes(q.state.data?.status) ? 10_000 : false),
  })

  const cancel = useMutation({
    mutationFn: () => orderApi.cancel(id, 'Cancelled by customer'),
    onSuccess: (data) => {
      queryClient.setQueryData(['order', id], data)
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      toast.success(data.payment_status === 'refunded' ? 'Order cancelled and refunded' : 'Order cancelled')
    },
    onError: (err) => toast.error(errorMessage(err)),
  })

  return (
    <QueryState query={order} loadingLabel="Loading order">
      {(o) => {
        const reached = new Set(o.history.map((h) => h.to_status))
        const canCancel = ['PENDING_PAYMENT', 'PLACED'].includes(o.status)
        return (
          <div className="layout-side">
            <div className="stack">
              <section className="card">
                <div className="row row--between">
                  <h1>Order #{o.id}</h1>
                  <StatusBadge status={o.status} />
                </div>
                <p className="muted">
                  <Link to={`/restaurants/${o.restaurant.id}`}>{o.restaurant.name}</Link> · {dateTime(o.created_at)}
                </p>
                {!['REJECTED', 'CANCELLED', 'PENDING_PAYMENT'].includes(o.status) && (
                  <div className="tracker" aria-label="Order progress">
                    {ORDER_FLOW.map((s) => (
                      <div key={s} className={`tracker__step ${reached.has(s) ? 'is-done' : ''}`}>{statusLabel(s)}</div>
                    ))}
                  </div>
                )}
                {o.status === 'PENDING_PAYMENT' && (
                  <div className="alert alert--warn">
                    Waiting for payment. <Link to={`/orders/${o.id}/pay`} className="btn btn--primary btn--small">Pay now</Link>
                  </div>
                )}
                {o.status === 'REJECTED' && (
                  <div className="alert alert--error">Rejected by the restaurant: {o.rejection_reason}</div>
                )}
                {o.payment_status === 'refunded' && <div className="alert alert--info">Your payment has been refunded.</div>}
                {ACTIVE.includes(o.status) && <small className="muted">This page updates automatically.</small>}
              </section>

              <section className="card">
                <h2>Items</h2>
                <ul className="list">
                  {o.items.map((i) => (
                    <li key={i.menu_item_id} className="row row--between">
                      <span>{i.quantity} × {i.item_name}</span>
                      <span>{money(i.line_total)}</span>
                    </li>
                  ))}
                </ul>
                <div className="summary-line"><span>Subtotal</span><span>{money(o.subtotal)}</span></div>
                <div className="summary-line"><span>Delivery</span><span>{money(o.delivery_fee)}</span></div>
                <div className="summary-line"><span>Taxes</span><span>{money(o.tax)}</span></div>
                <div className="summary-line summary-line--total"><span>Total</span><span>{money(o.total)}</span></div>
              </section>
            </div>

            <aside className="stack">
              <section className="card">
                <h2>Delivery</h2>
                <p>{o.delivery_address.line1}{o.delivery_address.line2 ? `, ${o.delivery_address.line2}` : ''}<br />
                  {o.delivery_address.city}, {o.delivery_address.state} {o.delivery_address.postal_code}</p>
                {o.notes && <p className="muted">Note: {o.notes}</p>}
              </section>
              <section className="card">
                <h2>Timeline</h2>
                <ol className="timeline">
                  {o.history.map((h, i) => (
                    <li key={i}>
                      <strong>{statusLabel(h.to_status)}</strong>
                      <div className="muted"><small>{dateTime(h.created_at)}{h.note ? ` · ${h.note}` : ''}</small></div>
                    </li>
                  ))}
                </ol>
              </section>
              <section className="card stack">
                {canCancel && (
                  <button type="button" className="btn btn--ghost" disabled={cancel.isPending}
                    onClick={() => window.confirm('Cancel this order?') && cancel.mutate()}>Cancel order</button>
                )}
                {o.status === 'DELIVERED' && (
                  <button type="button" className="btn btn--primary" onClick={() => setReviewOpen(true)}>Rate this order</button>
                )}
                <button type="button" className="btn btn--ghost" onClick={() => setComplaintOpen(true)}>Report a problem</button>
              </section>
            </aside>

            <ReviewModal open={reviewOpen} orderId={o.id} onClose={() => setReviewOpen(false)} />
            <ComplaintModal open={complaintOpen} orderId={o.id} onClose={() => setComplaintOpen(false)} />
          </div>
        )
      }}
    </QueryState>
  )
}

function ReviewModal({ open, orderId, onClose }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [rating, setRating] = useState(5)
  const [comment, setComment] = useState('')
  const submit = useMutation({
    mutationFn: () => orderApi.review(orderId, { rating, comment: comment || null }),
    onSuccess: (review) => {
      queryClient.invalidateQueries({ queryKey: ['reviews', String(review.restaurant_id)] })
      queryClient.invalidateQueries({ queryKey: ['menu', String(review.restaurant_id)] })
      toast.success('Thanks for your review!')
      onClose()
    },
  })
  return (
    <Modal open={open} title="Rate your order" onClose={onClose}>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); submit.mutate() }}>
        <fieldset className="row" style={{ border: 0, padding: 0 }}>
          <legend>Rating</legend>
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" className={`btn btn--small ${n <= rating ? 'btn--primary' : ''}`}
              aria-pressed={n === rating} aria-label={`${n} star${n > 1 ? 's' : ''}`} onClick={() => setRating(n)}>★</button>
          ))}
        </fieldset>
        <Field as="textarea" label="Comment (optional)" maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />
        <ErrorBox error={submit.error} />
        <button type="submit" className="btn btn--primary" disabled={submit.isPending}>Submit review</button>
      </form>
    </Modal>
  )
}

export function ComplaintModal({ open, orderId, onClose }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ subject: '', description: '' })
  const submit = useMutation({
    mutationFn: () => complaintApi.create({ order_id: orderId ?? null, ...form }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['complaints'] })
      toast.success('Complaint submitted — our team will get back to you.')
      setForm({ subject: '', description: '' })
      onClose()
    },
  })
  return (
    <Modal open={open} title={orderId ? `Report a problem with order #${orderId}` : 'Contact support'} onClose={onClose}>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); submit.mutate() }}>
        <Field label="Subject" minLength={5} maxLength={150} required value={form.subject}
          onChange={(e) => setForm({ ...form, subject: e.target.value })} />
        <Field as="textarea" label="What happened?" minLength={10} maxLength={2000} required value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <ErrorBox error={submit.error} />
        <button type="submit" className="btn btn--primary" disabled={submit.isPending}>Submit</button>
      </form>
    </Modal>
  )
}
