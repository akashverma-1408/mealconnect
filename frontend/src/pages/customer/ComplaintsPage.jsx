import { useState } from 'react'
import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { complaintApi } from '../../api/endpoints'
import { EmptyState, Pagination, QueryState, StatusBadge } from '../../components/ui'
import { dateTime } from '../../utils/format'
import { ComplaintModal } from './OrderDetailPage'

export default function ComplaintsPage() {
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(false)
  const complaints = useQuery({ queryKey: ['complaints', page], queryFn: () => complaintApi.list({ page, size: 10 }) })

  return (
    <>
      <div className="page-header">
        <div><h1>Help & complaints</h1><p className="muted">Problems with an order? Open it and choose “Report a problem”.</p></div>
        <button type="button" className="btn btn--primary" onClick={() => setOpen(true)}>Contact support</button>
      </div>
      <QueryState query={complaints}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title="No complaints">We hope it stays that way!</EmptyState>
          ) : (
            <div className="stack">
              {data.items.map((c) => (
                <article key={c.id} className="card">
                  <div className="row row--between">
                    <h3>{c.subject}</h3>
                    <StatusBadge status={c.status.toUpperCase()} />
                  </div>
                  <p>{c.description}</p>
                  <small className="muted">
                    {dateTime(c.created_at)}
                    {c.order_id && <> · <Link to={`/orders/${c.order_id}`}>Order #{c.order_id}</Link></>}
                  </small>
                  {c.resolution_note && <div className="alert alert--info" style={{ marginTop: 10 }}>Response: {c.resolution_note}</div>}
                </article>
              ))}
              <Pagination page={data.page} pages={data.pages} onChange={setPage} />
            </div>
          )
        }
      </QueryState>
      <ComplaintModal open={open} onClose={() => setOpen(false)} />
    </>
  )
}
