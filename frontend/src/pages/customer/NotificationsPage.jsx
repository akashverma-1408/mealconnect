import { useState } from 'react'
import { Link } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { notificationApi } from '../../api/endpoints'
import { useAuth } from '../../auth/AuthContext'
import { EmptyState, Pagination, QueryState } from '../../components/ui'
import { dateTime } from '../../utils/format'

export default function NotificationsPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const list = useQuery({ queryKey: ['notifications', 'list', page], queryFn: () => notificationApi.list({ page, size: 15 }) })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['notifications'] })
  const readOne = useMutation({ mutationFn: (id) => notificationApi.read(id), onSuccess: refresh })
  const readAll = useMutation({ mutationFn: () => notificationApi.readAll(), onSuccess: refresh })

  const linkFor = (n) => {
    const orderId = n.data?.order_id
    if (!orderId) return null
    return user.role === 'customer' ? `/orders/${orderId}` : null
  }

  return (
    <>
      <div className="page-header">
        <h1>Notifications</h1>
        <button type="button" className="btn btn--ghost btn--small" onClick={() => readAll.mutate()}>Mark all as read</button>
      </div>
      <QueryState query={list}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState title="You're all caught up" />
          ) : (
            <section className="card">
              <ul className="list">
                {data.items.map((n) => (
                  <li key={n.id} className="row row--between" style={{ opacity: n.is_read ? 0.65 : 1 }}>
                    <div>
                      <strong>{n.title}</strong>
                      <div>{n.body}</div>
                      <small className="muted">{dateTime(n.created_at)}</small>
                    </div>
                    <div className="row">
                      {linkFor(n) && <Link to={linkFor(n)} className="btn btn--small btn--ghost">Open</Link>}
                      {!n.is_read && <button type="button" className="btn btn--small" onClick={() => readOne.mutate(n.id)}>Mark read</button>}
                    </div>
                  </li>
                ))}
              </ul>
              <Pagination page={data.page} pages={data.pages} onChange={setPage} />
            </section>
          )
        }
      </QueryState>
    </>
  )
}
