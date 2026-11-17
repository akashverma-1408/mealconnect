import { useState } from 'react'
import { Link } from 'react-router'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { orderApi } from '../../api/endpoints'
import { EmptyState, Pagination, QueryState, StatusBadge } from '../../components/ui'
import { dateTime, money } from '../../utils/format'

export default function OrdersPage() {
  const [page, setPage] = useState(1)
  const orders = useQuery({
    queryKey: ['orders', page],
    queryFn: () => orderApi.list({ page, size: 10 }),
    placeholderData: keepPreviousData,
  })

  return (
    <>
      <div className="page-header"><h1>My orders</h1></div>
      <QueryState query={orders} loadingLabel="Loading orders">
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title="No orders yet" action={<Link to="/" className="btn btn--primary">Find something tasty</Link>} />
          ) : (
            <>
              <div className="stack">
                {data.items.map((o) => (
                  <Link key={o.id} to={`/orders/${o.id}`} className="card row row--between" style={{ textDecoration: 'none', color: 'inherit' }}>
                    <div>
                      <strong>{o.restaurant.name}</strong>
                      <div className="muted">#{o.id} · {o.item_count} item(s) · {dateTime(o.created_at)}</div>
                    </div>
                    <div className="row">
                      <strong>{money(o.total)}</strong>
                      <StatusBadge status={o.status} />
                    </div>
                  </Link>
                ))}
              </div>
              <Pagination page={data.page} pages={data.pages} onChange={setPage} />
            </>
          )
        }
      </QueryState>
    </>
  )
}
