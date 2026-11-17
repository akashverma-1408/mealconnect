import { useState } from 'react'
import { Link } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ownerApi } from '../../api/endpoints'
import { useToast } from '../../components/Toast'
import { EmptyState, ErrorBox, Modal, QueryState, Rating, StatusBadge } from '../../components/ui'
import { RestaurantForm } from './RestaurantForm'

export default function OwnerDashboard() {
  const [creating, setCreating] = useState(false)
  const restaurants = useQuery({ queryKey: ['owner', 'restaurants'], queryFn: ownerApi.restaurants })

  return (
    <>
      <div className="page-header">
        <div><h1>My restaurants</h1><p className="muted">Manage menus, incoming orders and sales.</p></div>
        <button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>+ Register a restaurant</button>
      </div>
      <QueryState query={restaurants} loadingLabel="Loading your restaurants">
        {(list) =>
          list.length === 0 ? (
            <EmptyState title="No restaurants yet" action={<button type="button" className="btn btn--primary" onClick={() => setCreating(true)}>Register your first restaurant</button>}>
              Register a restaurant; an admin reviews it before customers can see it.
            </EmptyState>
          ) : (
            <div className="grid grid--3">
              {list.map((r) => (
                <Link key={r.id} to={`/owner/restaurants/${r.id}`} className="card" style={{ textDecoration: 'none', color: 'inherit' }}>
                  <div className="row row--between">
                    <h3>{r.name}</h3>
                    <StatusBadge status={r.status.toUpperCase()} />
                  </div>
                  <p className="muted">{r.cuisine} · {r.city}</p>
                  <div className="row row--between">
                    <Rating value={r.avg_rating} count={r.rating_count} />
                    <span className={r.is_open ? 'tag' : 'muted'}>{r.is_open ? 'Open' : 'Closed'}</span>
                  </div>
                  {r.status !== 'approved' && r.status_reason && <p className="muted"><small>Reason: {r.status_reason}</small></p>}
                </Link>
              ))}
            </div>
          )
        }
      </QueryState>
      <CreateRestaurantModal open={creating} onClose={() => setCreating(false)} />
    </>
  )
}

function CreateRestaurantModal({ open, onClose }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const create = useMutation({
    mutationFn: (body) => ownerApi.createRestaurant(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['owner', 'restaurants'] })
      toast.success('Restaurant submitted for approval')
      onClose()
    },
  })
  return (
    <Modal open={open} title="Register a restaurant" onClose={onClose}>
      <ErrorBox error={create.error} />
      <RestaurantForm submitLabel="Submit for approval" pending={create.isPending} onSubmit={(body) => create.mutate(body)} />
    </Modal>
  )
}
