import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { addressApi, cartApi, orderApi } from '../../api/endpoints'
import { useToast } from '../../components/Toast'
import { EmptyState, ErrorBox, Field, QueryState } from '../../components/ui'
import { errorMessage, money } from '../../utils/format'
import { AddressForm } from './ProfilePage'

export default function CartPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const cart = useQuery({ queryKey: ['cart'], queryFn: cartApi.get })
  const addresses = useQuery({ queryKey: ['addresses'], queryFn: addressApi.list })
  const [addressId, setAddressId] = useState(null)
  const [notes, setNotes] = useState('')
  const [addingAddress, setAddingAddress] = useState(false)

  const setCart = (data) => queryClient.setQueryData(['cart'], data)
  const onError = (err) => toast.error(errorMessage(err))
  const changeQty = useMutation({
    mutationFn: ({ id, quantity }) => (quantity < 1 ? cartApi.remove(id) : cartApi.update(id, quantity)),
    onSuccess: setCart,
    onError,
  })
  const clear = useMutation({
    mutationFn: () => cartApi.clear(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cart'] }),
    onError,
  })
  const placeOrder = useMutation({
    mutationFn: (body) => orderApi.place(body),
    onSuccess: (order) => {
      queryClient.invalidateQueries({ queryKey: ['cart'] })
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      navigate(`/orders/${order.id}/pay`)
    },
  })

  const defaultAddress = addresses.data?.find((a) => a.is_default) ?? addresses.data?.[0]
  const selectedAddress = addressId ?? defaultAddress?.id

  return (
    <QueryState query={cart} loadingLabel="Loading your cart">
      {(c) =>
        c.items.length === 0 ? (
          <EmptyState title="Your cart is empty" action={<Link to="/" className="btn btn--primary">Browse restaurants</Link>}>
            Add some dishes and they will show up here.
          </EmptyState>
        ) : (
          <div className="layout-side">
            <section className="card">
              <div className="row row--between">
                <h1>Cart</h1>
                <button type="button" className="btn btn--ghost btn--small" onClick={() => clear.mutate()}>Clear cart</button>
              </div>
              <p className="muted">From <Link to={`/restaurants/${c.restaurant.id}`}>{c.restaurant.name}</Link></p>
              <ul className="list">
                {c.items.map((line) => (
                  <li key={line.menu_item_id} className={`menu-item ${line.is_available ? '' : 'menu-item--off'}`}>
                    <div>
                      <strong>{line.name}</strong>
                      <div className="muted">{money(line.unit_price)} each{!line.is_available && ' · no longer available'}</div>
                    </div>
                    <div className="row">
                      <div className="qty" aria-label={`Quantity of ${line.name}`}>
                        <button type="button" aria-label={`Remove one ${line.name}`} disabled={changeQty.isPending}
                          onClick={() => changeQty.mutate({ id: line.menu_item_id, quantity: line.quantity - 1 })}>−</button>
                        <span>{line.quantity}</span>
                        <button type="button" aria-label={`Add one ${line.name}`} disabled={changeQty.isPending || line.quantity >= 50}
                          onClick={() => changeQty.mutate({ id: line.menu_item_id, quantity: line.quantity + 1 })}>+</button>
                      </div>
                      <strong style={{ minWidth: 80, textAlign: 'right' }}>{money(line.line_total)}</strong>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            <aside className="card stack">
              <h2>Checkout</h2>
              <div>
                <div className="summary-line"><span>Subtotal</span><span>{money(c.subtotal)}</span></div>
                <div className="summary-line"><span>Delivery fee</span><span>{money(c.delivery_fee)}</span></div>
                <div className="summary-line"><span>Taxes (5%)</span><span>{money(c.tax)}</span></div>
                <div className="summary-line summary-line--total"><span>Total</span><span>{money(c.total)}</span></div>
              </div>

              {c.problems.map((p) => <div key={p} className="alert alert--warn">{p}</div>)}

              {addresses.data?.length ? (
                <Field as="select" label="Deliver to" value={selectedAddress ?? ''} onChange={(e) => setAddressId(Number(e.target.value))}>
                  {addresses.data.map((a) => (
                    <option key={a.id} value={a.id}>{a.label ? `${a.label}: ` : ''}{a.line1}, {a.city}</option>
                  ))}
                </Field>
              ) : (
                <p className="muted">Add a delivery address to continue.</p>
              )}
              <button type="button" className="btn btn--ghost btn--small" onClick={() => setAddingAddress((v) => !v)}>
                {addingAddress ? 'Cancel' : '+ New address'}
              </button>
              {addingAddress && (
                <AddressForm onSaved={(a) => { setAddressId(a.id); setAddingAddress(false) }} />
              )}

              <Field as="textarea" label="Notes for the restaurant (optional)" maxLength={500} value={notes}
                onChange={(e) => setNotes(e.target.value)} placeholder="e.g. less spicy, no onions" />
              <ErrorBox error={placeOrder.error} />
              <button type="button" className="btn btn--primary btn--block"
                disabled={!c.can_checkout || !selectedAddress || placeOrder.isPending}
                onClick={() => placeOrder.mutate({ address_id: selectedAddress, notes: notes || null })}>
                {placeOrder.isPending ? 'Placing order…' : `Place order · ${money(c.total)}`}
              </button>
            </aside>
          </div>
        )
      }
    </QueryState>
  )
}
