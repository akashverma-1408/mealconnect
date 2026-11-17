import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { cartApi, catalogueApi } from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { ErrorBox, Modal, Pagination, QueryState, Rating, VegMark } from '../../components/ui'
import { dateTime, errorCode, errorMessage, money } from '../../utils/format'

export default function RestaurantPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [vegOnly, setVegOnly] = useState(false)
  const [conflict, setConflict] = useState(null) // item waiting while we ask to clear the cart

  const menu = useQuery({ queryKey: ['menu', id], queryFn: () => catalogueApi.menu(id) })
  const cart = useQuery({ queryKey: ['cart'], queryFn: cartApi.get, enabled: user?.role === 'customer' })

  const addItem = useMutation({
    mutationFn: (item) => cartApi.add(item.id, 1),
    onSuccess: (newCart, item) => {
      queryClient.setQueryData(['cart'], newCart) // update the cache with the server's answer
      toast.success(`${item.name} added to cart`)
    },
    onError: (err, item) => {
      if (errorCode(err) === 'CART_RESTAURANT_MISMATCH') setConflict(item)
      else toast.error(errorMessage(err))
    },
  })

  const replaceCart = useMutation({
    mutationFn: async (item) => {
      await cartApi.clear()
      return cartApi.add(item.id, 1)
    },
    onSuccess: (newCart) => {
      queryClient.setQueryData(['cart'], newCart)
      setConflict(null)
      toast.success('Cart replaced')
    },
    onError: (err) => toast.error(errorMessage(err)),
  })

  function handleAdd(item) {
    if (!user) return navigate('/login', { state: { from: `/restaurants/${id}` } })
    if (user.role !== 'customer') return toast.info('Only customer accounts can order food.')
    addItem.mutate(item)
  }

  const inCart = Object.fromEntries((cart.data?.items || []).map((l) => [l.menu_item_id, l.quantity]))
  const cartHere = cart.data?.restaurant?.id === Number(id) && cart.data.item_count > 0

  return (
    <QueryState query={menu} loadingLabel="Loading menu">
      {({ restaurant, sections }) => (
        <div className="layout-side">
          <div className="stack">
            <header className="card">
              <div className="row row--between">
                <h1>{restaurant.name}</h1>
                <Rating value={restaurant.avg_rating} count={restaurant.rating_count} />
              </div>
              <p className="muted">{restaurant.cuisine} · {restaurant.address}</p>
              {restaurant.description && <p>{restaurant.description}</p>}
              <div className="row muted">
                <span>Delivery {Number(restaurant.delivery_fee) ? money(restaurant.delivery_fee) : 'free'}</span>
                <span>· Minimum order {money(restaurant.min_order_amount)}</span>
                {restaurant.opens_at && <span>· {restaurant.opens_at.slice(0, 5)}–{restaurant.closes_at.slice(0, 5)}</span>}
              </div>
              {!restaurant.is_open && <div className="alert alert--warn">This restaurant is closed right now. You can browse, but not order.</div>}
            </header>

            <label className="checkbox"><input type="checkbox" checked={vegOnly} onChange={(e) => setVegOnly(e.target.checked)} /> Veg only</label>

            {sections.map((section) => {
              const items = section.items.filter((i) => !vegOnly || i.is_veg)
              if (!items.length) return null
              return (
                <section key={section.category?.id ?? 'other'} className="card" aria-labelledby={`cat-${section.category?.id ?? 'other'}`}>
                  <h2 id={`cat-${section.category?.id ?? 'other'}`}>{section.category?.name ?? 'More dishes'}</h2>
                  <ul className="list">
                    {items.map((item) => (
                      <li key={item.id} className={`menu-item ${item.is_available ? '' : 'menu-item--off'}`}>
                        <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                          <VegMark veg={item.is_veg} />
                          <div>
                            <strong>{item.name}</strong>
                            <div className="menu-item__price">{money(item.price)}</div>
                            {item.description && <small className="muted">{item.description}</small>}
                          </div>
                        </div>
                        {item.is_available ? (
                          <button type="button" className="btn btn--small" disabled={!restaurant.is_open || addItem.isPending}
                            onClick={() => handleAdd(item)} aria-label={`Add ${item.name} to cart`}>
                            {inCart[item.id] ? `Add · ${inCart[item.id]} in cart` : 'Add'}
                          </button>
                        ) : (
                          <span className="muted">Sold out</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )
            })}
            <Reviews restaurantId={id} />
          </div>

          <aside className="card">
            <h2>Your cart</h2>
            {cartHere ? (
              <>
                <p>{cart.data.item_count} item(s) · {money(cart.data.subtotal)}</p>
                <Link to="/cart" className="btn btn--primary btn--block">View cart & checkout</Link>
              </>
            ) : (
              <p className="muted">{user?.role === 'customer' ? 'Add dishes to start an order.' : 'Log in as a customer to order.'}</p>
            )}
          </aside>

          <Modal open={!!conflict} title="Start a new cart?" onClose={() => setConflict(null)}>
            <p>Your cart has dishes from another restaurant. A cart can only hold items from one restaurant.</p>
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn--ghost" onClick={() => setConflict(null)}>Keep current cart</button>
              <button type="button" className="btn btn--primary" disabled={replaceCart.isPending}
                onClick={() => replaceCart.mutate(conflict)}>Clear cart & add</button>
            </div>
          </Modal>
        </div>
      )}
    </QueryState>
  )
}

function Reviews({ restaurantId }) {
  const [page, setPage] = useState(1)
  const reviews = useQuery({
    queryKey: ['reviews', restaurantId, page],
    queryFn: () => catalogueApi.reviews(restaurantId, { page, size: 5 }),
  })
  return (
    <section className="card">
      <h2>Reviews</h2>
      {reviews.isError && <ErrorBox error={reviews.error} />}
      {reviews.data?.items.length === 0 && <p className="muted">No reviews yet.</p>}
      <ul className="list">
        {reviews.data?.items.map((r) => (
          <li key={r.id}>
            <div className="row row--between">
              <strong>{r.author_name}</strong>
              <span className="rating">{'★'.repeat(r.rating)}<span className="muted">{'★'.repeat(5 - r.rating)}</span></span>
            </div>
            {r.comment && <p>{r.comment}</p>}
            <small className="muted">{dateTime(r.created_at)}</small>
          </li>
        ))}
      </ul>
      <Pagination page={page} pages={reviews.data?.pages} onChange={setPage} />
    </section>
  )
}
