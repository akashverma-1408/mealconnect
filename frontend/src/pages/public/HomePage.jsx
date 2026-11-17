import { Link, useSearchParams } from 'react-router'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { catalogueApi } from '../../api/endpoints'
import { EmptyState, ErrorBox, Pagination, Rating, Spinner } from '../../components/ui'
import useDebounce from '../../hooks/useDebounce'
import { money } from '../../utils/format'

const CUISINE_EMOJI = {
  'North Indian': '🍛', 'South Indian': '🥞', Italian: '🍕', Chinese: '🥡', Biryani: '🍚',
  Healthy: '🥗', American: '🍔', Mexican: '🌮',
}

/** Browse page. Filters live in the URL (?city=Pune&page=2) so they survive reloads and can be shared. */
export default function HomePage() {
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get('q') || '')
  const debouncedQ = useDebounce(q)

  const filters = {
    q: debouncedQ || undefined,
    city: params.get('city') || undefined,
    cuisine: params.get('cuisine') || undefined,
    is_veg: params.get('is_veg') === 'true' || undefined,
    min_rating: params.get('min_rating') || undefined,
    open_now: params.get('open_now') === 'true' || undefined,
    sort: params.get('sort') || '-avg_rating',
    page: Number(params.get('page') || 1),
    size: 12,
  }

  const query = useQuery({
    queryKey: ['restaurants', filters],
    queryFn: () => catalogueApi.restaurants(filters),
    placeholderData: keepPreviousData, // keep showing old results while new ones load
  })

  function update(key, value) {
    const next = new URLSearchParams(params)
    if (value === '' || value === false || value == null) next.delete(key)
    else next.set(key, value)
    if (key !== 'page') next.delete('page')
    setParams(next)
  }

  return (
    <>
      <section className="hero">
        <h1>Hungry? Your next meal is a few taps away.</h1>
        <p>Order from the best local restaurants, track your food live, pay securely.</p>
        <form className="search" role="search" onSubmit={(e) => e.preventDefault()}>
          <label htmlFor="search" className="sr-only">Search restaurants or cuisines</label>
          <input id="search" type="search" placeholder="Search restaurants or cuisines…"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </form>
      </section>

      <div className="filters">
        <select aria-label="City" value={params.get('city') || ''} onChange={(e) => update('city', e.target.value)}>
          <option value="">All cities</option>
          {['Pune', 'Mumbai', 'Bengaluru'].map((c) => <option key={c}>{c}</option>)}
        </select>
        <select aria-label="Cuisine" value={params.get('cuisine') || ''} onChange={(e) => update('cuisine', e.target.value)}>
          <option value="">All cuisines</option>
          {Object.keys(CUISINE_EMOJI).map((c) => <option key={c}>{c}</option>)}
        </select>
        <select aria-label="Minimum rating" value={params.get('min_rating') || ''} onChange={(e) => update('min_rating', e.target.value)}>
          <option value="">Any rating</option>
          <option value="4">4.0+</option>
          <option value="3.5">3.5+</option>
        </select>
        <select aria-label="Sort by" value={filters.sort} onChange={(e) => update('sort', e.target.value)}>
          <option value="-avg_rating">Top rated</option>
          <option value="delivery_fee">Lowest delivery fee</option>
          <option value="-created_at">Newest</option>
          <option value="name">Name A–Z</option>
        </select>
        <div className="row">
          <label className="checkbox">
            <input type="checkbox" checked={filters.is_veg === true} onChange={(e) => update('is_veg', e.target.checked)} /> Pure veg
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={filters.open_now === true} onChange={(e) => update('open_now', e.target.checked)} /> Open now
          </label>
        </div>
      </div>

      {query.isPending ? (
        <Spinner label="Finding restaurants" />
      ) : query.isError ? (
        <ErrorBox error={query.error} onRetry={query.refetch} />
      ) : query.data.items.length === 0 ? (
        <EmptyState title="No restaurants match">Try removing a filter or searching for something else.</EmptyState>
      ) : (
        <>
          <p className="muted">{query.data.total} restaurant{query.data.total === 1 ? '' : 's'}</p>
          <div className="grid grid--3">
            {query.data.items.map((r) => <RestaurantCard key={r.id} r={r} />)}
          </div>
          <Pagination page={query.data.page} pages={query.data.pages} onChange={(p) => update('page', p)} />
        </>
      )}
    </>
  )
}

function RestaurantCard({ r }) {
  return (
    <Link to={`/restaurants/${r.id}`} className="card card--flush restaurant-card">
      <div className="restaurant-card__img" aria-hidden="true">{CUISINE_EMOJI[r.cuisine] || '🍽️'}</div>
      <div className="restaurant-card__body">
        <div className="row row--between">
          <h3>{r.name}</h3>
          <Rating value={r.avg_rating} count={r.rating_count} />
        </div>
        <span className="muted">{r.cuisine} · {r.city}</span>
        <span className="muted">
          Delivery {Number(r.delivery_fee) ? money(r.delivery_fee) : 'free'} · Min {money(r.min_order_amount)}
        </span>
        <div className="row">
          {r.is_veg_only && <span className="tag">Pure veg</span>}
          {!r.is_open && <span className="closed">Closed now</span>}
        </div>
      </div>
    </Link>
  )
}
