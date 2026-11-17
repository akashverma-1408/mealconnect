/**
 * Payment screen.
 * - provider "razorpay" (test mode): opens Razorpay Checkout; Razorpay then calls our
 *   webhook, and we poll the order until the webhook has marked it PLACED.
 * - provider "mock" (default sandbox): two buttons ask the backend to send itself a
 *   correctly signed webhook, which goes through exactly the same verification.
 * The browser never decides that an order is paid — only a verified webhook does.
 */
import { Link, useNavigate, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { orderApi, paymentApi } from '../../api/endpoints'
import { useToast } from '../../components/Toast'
import { ErrorBox, QueryState } from '../../components/ui'
import { errorMessage, money } from '../../utils/format'
import { loadScript } from '../../utils/loadScript'

const RAZORPAY_SCRIPT = 'https://checkout.razorpay.com/v1/checkout.js'

export default function PaymentPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const queryClient = useQueryClient()
  const order = useQuery({ queryKey: ['order', id], queryFn: () => orderApi.get(id) })

  // Start (or restart) a checkout session as soon as the page opens.
  const session = useQuery({
    queryKey: ['checkout', id],
    queryFn: () => paymentApi.checkout(id),
    enabled: order.data?.status === 'PENDING_PAYMENT',
    staleTime: Infinity,
    retry: false,
  })

  const pay = useMutation({
    mutationFn: (outcome) => paymentApi.sandboxPay(id, outcome),
    onSuccess: async (_res, outcome) => {
      await queryClient.invalidateQueries({ queryKey: ['order', id] })
      queryClient.invalidateQueries({ queryKey: ['orders'] })
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
      if (outcome === 'success') {
        toast.success('Payment received! The restaurant has your order.')
        navigate(`/orders/${id}`, { replace: true })
      } else {
        toast.error('Payment was declined. You can try again.')
        queryClient.removeQueries({ queryKey: ['checkout', id] })
        session.refetch()
      }
    },
    onError: (err) => toast.error(errorMessage(err)),
  })

  async function payWithRazorpay() {
    const c = session.data.checkout
    try {
      await loadScript(RAZORPAY_SCRIPT)
      const rzp = new window.Razorpay({
        key: c.key_id,
        order_id: c.order_id,
        amount: c.amount,
        currency: c.currency,
        name: c.name,
        description: c.description,
        theme: { color: '#e8590c' },
        handler: () => {
          // Payment done on Razorpay's side; our order flips to PLACED when the webhook lands.
          toast.success('Payment received — confirming your order…')
          navigate(`/orders/${id}`, { replace: true })
        },
        modal: { ondismiss: () => toast.info('Payment window closed') },
      })
      rzp.on('payment.failed', () => toast.error('Payment failed. You can try again.'))
      rzp.open()
    } catch (err) {
      toast.error(errorMessage(err, 'Could not open the payment window'))
    }
  }

  const isMock = session.data?.provider === 'mock'

  return (
    <QueryState query={order} loadingLabel="Loading order">
      {(o) =>
        o.status !== 'PENDING_PAYMENT' ? (
          <div className="card auth-card">
            <h1>Nothing to pay</h1>
            <p>This order is already {o.status.toLowerCase().replaceAll('_', ' ')}.</p>
            <Link to={`/orders/${id}`} className="btn btn--primary">View order</Link>
          </div>
        ) : (
          <div className="card auth-card stack">
            <h1>Pay for order #{o.id}</h1>
            <div className="summary-line summary-line--total"><span>Amount</span><span>{money(o.total)}</span></div>
            <div className="alert alert--info">
              {isMock
                ? 'Sandbox mode — no real money moves. Choose an outcome to simulate the payment gateway.'
                : 'Test mode — use Razorpay test cards; no real money moves.'}
            </div>
            <ErrorBox error={session.error} />
            {session.data && (
              <p className="muted">Payment reference <code>{session.data.provider_payment_id}</code></p>
            )}
            {session.data && !isMock && (
              <button type="button" className="btn btn--success btn--block" onClick={payWithRazorpay}>
                Pay {money(o.total)} with Razorpay
              </button>
            )}
            {(!session.data || isMock) && (
              <>
                <button type="button" className="btn btn--success btn--block" disabled={!session.data || pay.isPending}
                  onClick={() => pay.mutate('success')}>
                  {pay.isPending ? 'Processing…' : `Pay ${money(o.total)} (test card 4111 1111 1111 1111)`}
                </button>
                <button type="button" className="btn btn--ghost btn--block" disabled={!session.data || pay.isPending}
                  onClick={() => pay.mutate('failure')}>Simulate a declined card</button>
              </>
            )}
            <Link to={`/orders/${id}`} className="muted">Pay later — view order</Link>
          </div>
        )
      }
    </QueryState>
  )
}
