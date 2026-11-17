/**
 * Component tests for the payment, tracking, owner and admin screens.
 * Each test checks a success path and the matching failure/guard path.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderRoute } from '../test/utils'

const auth = vi.hoisted(() => ({ user: { id: 1, role: 'customer', full_name: 'Asha Rao' }, loading: false }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../utils/loadScript', () => ({ loadScript: vi.fn(() => Promise.resolve()) }))
vi.mock('../api/endpoints', () => ({
  orderApi: { get: vi.fn(), cancel: vi.fn(), review: vi.fn() },
  paymentApi: { checkout: vi.fn(), sandboxPay: vi.fn() },
  complaintApi: { create: vi.fn() },
  ownerApi: { restaurant: vi.fn(), orders: vi.fn(), order: vi.fn(), accept: vi.fn(), reject: vi.fn(), setStatus: vi.fn() },
  adminApi: { users: vi.fn(), setUserStatus: vi.fn() },
}))

const { orderApi, paymentApi, ownerApi, adminApi } = await import('../api/endpoints')
const { loadScript } = await import('../utils/loadScript')
const { default: PaymentPage } = await import('./customer/PaymentPage')
const { default: OrderDetailPage } = await import('./customer/OrderDetailPage')
const { default: OwnerRestaurantPage } = await import('./owner/OwnerRestaurantPage')
const { default: AdminPage } = await import('./admin/AdminPage')

const ORDER = {
  id: 19, status: 'PENDING_PAYMENT', customer_id: 1, restaurant: { id: 1, name: 'Spice Route', slug: 'spice-route' },
  items: [{ menu_item_id: 11, item_name: 'Paneer Tikka', unit_price: '249.00', quantity: 2, line_total: '498.00' }],
  subtotal: '498.00', delivery_fee: '30.00', tax: '24.90', total: '552.90',
  delivery_address: { line1: '12 MG Road', line2: null, city: 'Pune', state: 'MH', postal_code: '411001' },
  notes: null, rejection_reason: null, payment_status: null,
  history: [{ from_status: null, to_status: 'PENDING_PAYMENT', note: null, created_at: '2026-11-17T10:00:00Z' }],
  created_at: '2026-11-17T10:00:00Z', updated_at: '2026-11-17T10:00:00Z',
}
const page = (items) => ({ items, total: items.length, page: 1, size: 15, pages: 1 })

beforeEach(() => {
  vi.clearAllMocks()
  auth.user = { id: 1, role: 'customer', full_name: 'Asha Rao' }
})
afterEach(() => {
  delete window.Razorpay
})

describe('PaymentPage', () => {
  const routes = [
    { path: '/orders/:id/pay', element: <PaymentPage /> },
    { path: '/orders/:id', element: <p>Order page</p> },
  ]

  it('sandbox: paying sends the success outcome and opens the order', async () => {
    orderApi.get.mockResolvedValue(ORDER)
    paymentApi.checkout.mockResolvedValue({ provider: 'mock', provider_payment_id: 'mock_pay_1', checkout: {} })
    paymentApi.sandboxPay.mockResolvedValue({ status: 'processed' })
    const { router } = renderRoute(routes, { path: '/orders/19/pay' })
    await userEvent.click(await screen.findByRole('button', { name: /Pay ₹552.90/ }))
    expect(paymentApi.sandboxPay).toHaveBeenCalledWith('19', 'success')
    await waitFor(() => expect(router.state.location.pathname).toBe('/orders/19'))
  })

  it('razorpay: opens Razorpay Checkout with the server-created order, never the secret', async () => {
    orderApi.get.mockResolvedValue(ORDER)
    paymentApi.checkout.mockResolvedValue({
      provider: 'razorpay', provider_payment_id: 'order_abc',
      checkout: { key_id: 'rzp_test_key', order_id: 'order_abc', amount: 55290, currency: 'INR', name: 'MealConnect', description: 'order #19' },
    })
    const open = vi.fn()
    window.Razorpay = vi.fn(function Razorpay(options) {
      this.options = options
      this.open = open
      this.on = vi.fn()
    })
    renderRoute(routes, { path: '/orders/19/pay' })
    await userEvent.click(await screen.findByRole('button', { name: /with Razorpay/ }))
    await waitFor(() => expect(open).toHaveBeenCalled())
    expect(loadScript).toHaveBeenCalledWith('https://checkout.razorpay.com/v1/checkout.js')
    expect(window.Razorpay).toHaveBeenCalledWith(expect.objectContaining({ key: 'rzp_test_key', order_id: 'order_abc', amount: 55290 }))
    expect(screen.queryByRole('button', { name: /declined/ })).not.toBeInTheDocument() // no sandbox buttons
  })

  it('does not offer payment for an order that is already paid', async () => {
    orderApi.get.mockResolvedValue({ ...ORDER, status: 'PLACED' })
    renderRoute(routes, { path: '/orders/19/pay' })
    expect(await screen.findByText('Nothing to pay')).toBeInTheDocument()
    expect(paymentApi.checkout).not.toHaveBeenCalled()
  })
})

describe('OrderDetailPage', () => {
  const routes = [{ path: '/orders/:id', element: <OrderDetailPage /> }]

  it('shows progress and allows cancelling a placed order', async () => {
    orderApi.get.mockResolvedValue({
      ...ORDER, status: 'PLACED',
      history: [...ORDER.history, { from_status: 'PENDING_PAYMENT', to_status: 'PLACED', note: 'Payment received', created_at: '2026-11-17T10:01:00Z' }],
    })
    renderRoute(routes, { path: '/orders/19' })
    const tracker = await screen.findByLabelText('Order progress')
    expect(within(tracker).getByText('Placed')).toHaveClass('is-done')
    expect(within(tracker).getByText('Accepted')).not.toHaveClass('is-done')
    expect(screen.getByRole('button', { name: 'Cancel order' })).toBeInTheDocument()
  })

  it('hides cancel once the restaurant accepted, and shows the rejection reason', async () => {
    orderApi.get.mockResolvedValue({ ...ORDER, status: 'REJECTED', rejection_reason: 'Out of stock', payment_status: 'refunded' })
    renderRoute(routes, { path: '/orders/19' })
    expect(await screen.findByText(/Rejected by the restaurant: Out of stock/)).toBeInTheDocument()
    expect(screen.getByText('Your payment has been refunded.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel order' })).not.toBeInTheDocument()
  })
})

describe('Owner order handling', () => {
  beforeEach(() => {
    auth.user = { id: 2, role: 'restaurant_owner', full_name: 'Meera Kapoor' }
    ownerApi.restaurant.mockResolvedValue({ id: 1, name: 'Spice Route', status: 'approved', is_open: true, status_reason: null })
    ownerApi.orders.mockResolvedValue(page([{ id: 19, status: 'PLACED', restaurant: ORDER.restaurant, total: '552.90', item_count: 2, created_at: ORDER.created_at }]))
    ownerApi.order.mockResolvedValue({ ...ORDER, status: 'PLACED' })
  })
  const routes = [{ path: '/owner/restaurants/:id', element: <OwnerRestaurantPage /> }]

  it('requires a reason before rejecting, and can accept', async () => {
    ownerApi.accept.mockResolvedValue({ ...ORDER, status: 'ACCEPTED' })
    renderRoute(routes, { path: '/owner/restaurants/1?tab=orders' })
    await userEvent.click(await screen.findByRole('button', { name: 'Manage' }))
    const dialog = await screen.findByRole('dialog', { name: 'Order #19' })
    const reject = await within(dialog).findByRole('button', { name: /Reject & refund/ })
    expect(reject).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Reason for rejecting'), 'No')
    expect(reject).toBeDisabled() // still too short (min 3 characters, same as the API)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Accept order' }))
    await waitFor(() => expect(ownerApi.accept).toHaveBeenCalledWith(19))
    expect(await within(dialog).findByRole('button', { name: /Mark as preparing/ })).toBeInTheDocument()
  })
})

describe('Admin moderation', () => {
  beforeEach(() => {
    auth.user = { id: 3, role: 'admin', full_name: 'Platform Admin' }
    adminApi.users.mockResolvedValue(page([
      { id: 7, full_name: 'Ravi Kumar', email: 'ravi@example.com', role: 'customer', status: 'active', created_at: ORDER.created_at },
    ]))
  })

  it('suspending a user requires a reason', async () => {
    adminApi.setUserStatus.mockResolvedValue({ id: 7, email: 'ravi@example.com', status: 'suspended' })
    renderRoute([{ path: '/admin', element: <AdminPage /> }], { path: '/admin?tab=users' })
    await userEvent.click(await screen.findByRole('button', { name: 'Suspend' }))
    const dialog = await screen.findByRole('dialog', { name: 'Suspend ravi@example.com?' })
    const confirm = within(dialog).getByRole('button', { name: 'Confirm' })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('Reason (required)'), 'Chargeback fraud')
    await userEvent.click(confirm)
    await waitFor(() =>
      expect(adminApi.setUserStatus).toHaveBeenCalledWith(7, { status: 'suspended', reason: 'Chargeback fraud' }),
    )
  })
})
