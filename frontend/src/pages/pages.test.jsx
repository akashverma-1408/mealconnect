/**
 * Component tests: render real pages with the API layer mocked, then interact
 * like a user would (type, click) and check what appears on screen.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiError, renderRoute } from '../test/utils'

const auth = vi.hoisted(() => ({ user: null, login: vi.fn(), register: vi.fn(), loading: false }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../api/endpoints', () => ({
  catalogueApi: { restaurants: vi.fn(), menu: vi.fn(), reviews: vi.fn() },
  cartApi: { get: vi.fn(), add: vi.fn(), clear: vi.fn(), update: vi.fn(), remove: vi.fn() },
  addressApi: { list: vi.fn() },
  orderApi: { place: vi.fn() },
}))

const { catalogueApi, cartApi, addressApi, orderApi } = await import('../api/endpoints')
const { default: HomePage } = await import('./public/HomePage')
const { default: LoginPage } = await import('./public/LoginPage')
const { default: RestaurantPage } = await import('./public/RestaurantPage')
const { default: CartPage } = await import('./customer/CartPage')
const { default: RequireAuth } = await import('../auth/RequireAuth')

const CUSTOMER = { id: 7, full_name: 'Asha Rao', role: 'customer', email: 'asha@example.com' }
const RESTAURANT = {
  id: 1, name: 'Spice Route', slug: 'spice-route', cuisine: 'North Indian', city: 'Pune',
  image_url: null, is_veg_only: false, is_open: true, delivery_fee: '30.00', min_order_amount: '100.00',
  avg_rating: '4.5', rating_count: 12, description: 'Tasty', address: '1 Main St', phone: null,
  opens_at: null, closes_at: null,
}
const page = (items) => ({ items, total: items.length, page: 1, size: 12, pages: 1 })
const EMPTY_CART = { restaurant: null, items: [], item_count: 0, subtotal: '0.00', delivery_fee: '0.00',
  tax: '0.00', total: '0.00', min_order_amount: '0.00', can_checkout: false, problems: ['Cart is empty'] }

beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(auth, { user: null, loading: false })
})

describe('HomePage', () => {
  it('lists restaurants returned by the API', async () => {
    catalogueApi.restaurants.mockResolvedValue(page([RESTAURANT]))
    renderRoute([{ path: '/', element: <HomePage /> }])
    expect(await screen.findByRole('heading', { name: 'Spice Route' })).toBeInTheDocument()
    expect(screen.getByText('1 restaurant')).toBeInTheDocument()
    expect(screen.getByLabelText('Rated 4.5 out of 5')).toBeInTheDocument()
  })

  it('puts filters in the URL and re-queries', async () => {
    catalogueApi.restaurants.mockResolvedValue(page([RESTAURANT]))
    const { router } = renderRoute([{ path: '/', element: <HomePage /> }])
    await screen.findByText('Spice Route')
    await userEvent.selectOptions(screen.getByLabelText('City'), 'Pune')
    await waitFor(() => expect(router.state.location.search).toBe('?city=Pune'))
    expect(catalogueApi.restaurants).toHaveBeenLastCalledWith(expect.objectContaining({ city: 'Pune', page: 1 }))
  })

  it('shows an empty state', async () => {
    catalogueApi.restaurants.mockResolvedValue(page([]))
    renderRoute([{ path: '/', element: <HomePage /> }])
    expect(await screen.findByText('No restaurants match')).toBeInTheDocument()
  })

  it('shows API errors with a retry button', async () => {
    catalogueApi.restaurants.mockRejectedValue(apiError(500, 'INTERNAL_ERROR', 'An unexpected error occurred'))
    renderRoute([{ path: '/', element: <HomePage /> }])
    expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('LoginPage', () => {
  it('logs in and sends each role to its home page', async () => {
    auth.login.mockResolvedValue({ role: 'restaurant_owner' })
    const { router } = renderRoute([
      { path: '/login', element: <LoginPage /> },
      { path: '/owner', element: <p>Owner home</p> },
    ], { path: '/login' })
    await userEvent.type(screen.getByLabelText('Email'), 'owner@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'Secret123')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(auth.login).toHaveBeenCalledWith('owner@example.com', 'Secret123')
    await waitFor(() => expect(router.state.location.pathname).toBe('/owner'))
  })

  it('shows the server error on bad credentials', async () => {
    auth.login.mockRejectedValue(apiError(401, 'INVALID_CREDENTIALS', 'Invalid email or password'))
    renderRoute([{ path: '/login', element: <LoginPage /> }], { path: '/login' })
    await userEvent.type(screen.getByLabelText('Email'), 'a@b.com')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Log in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
  })
})

describe('RequireAuth', () => {
  const routes = [
    { path: '/login', element: <p>Login screen</p> },
    { path: '/', element: <p>Home</p> },
    { element: <RequireAuth roles={['admin']} />, children: [{ path: '/admin', element: <p>Admin area</p> }] },
  ]
  it('redirects anonymous users to login', async () => {
    renderRoute(routes, { path: '/admin' })
    expect(await screen.findByText('Login screen')).toBeInTheDocument()
  })
  it('redirects users with the wrong role to their own home', async () => {
    auth.user = CUSTOMER
    renderRoute(routes, { path: '/admin' })
    expect(await screen.findByText('Home')).toBeInTheDocument()
  })
  it('lets the right role in', async () => {
    auth.user = { ...CUSTOMER, role: 'admin' }
    renderRoute(routes, { path: '/admin' })
    expect(await screen.findByText('Admin area')).toBeInTheDocument()
  })
})

describe('RestaurantPage', () => {
  const MENU = {
    restaurant: RESTAURANT,
    sections: [{
      category: { id: 3, name: 'Mains', sort_order: 0 },
      items: [
        { id: 11, name: 'Paneer Tikka', description: null, price: '249.00', is_veg: true, is_available: true, image_url: null, category_id: 3 },
        { id: 12, name: 'Butter Chicken', description: null, price: '349.00', is_veg: false, is_available: false, image_url: null, category_id: 3 },
      ],
    }],
  }
  beforeEach(() => {
    auth.user = CUSTOMER
    catalogueApi.menu.mockResolvedValue(MENU)
    catalogueApi.reviews.mockResolvedValue(page([]))
    cartApi.get.mockResolvedValue(EMPTY_CART)
  })
  const routes = [{ path: '/restaurants/:id', element: <RestaurantPage /> }]

  it('shows the menu with sold-out items disabled', async () => {
    renderRoute(routes, { path: '/restaurants/1' })
    expect(await screen.findByText('Paneer Tikka')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add Paneer Tikka to cart' })).toBeEnabled()
    expect(screen.getByText('Sold out')).toBeInTheDocument()
  })

  it('asks before replacing a cart from another restaurant', async () => {
    cartApi.add.mockRejectedValueOnce(apiError(409, 'CART_RESTAURANT_MISMATCH'))
    cartApi.clear.mockResolvedValue({})
    cartApi.add.mockResolvedValueOnce({ ...EMPTY_CART, item_count: 1 })
    renderRoute(routes, { path: '/restaurants/1' })
    await userEvent.click(await screen.findByRole('button', { name: 'Add Paneer Tikka to cart' }))
    const dialog = await screen.findByRole('dialog', { name: 'Start a new cart?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Clear cart & add' }))
    await waitFor(() => expect(cartApi.clear).toHaveBeenCalled())
    expect(cartApi.add).toHaveBeenLastCalledWith(11, 1)
  })
})

describe('CartPage', () => {
  const CART = {
    restaurant: { id: 1, name: 'Spice Route', slug: 'spice-route' },
    items: [{ menu_item_id: 11, name: 'Paneer Tikka', unit_price: '249.00', quantity: 2, line_total: '498.00', is_veg: true, is_available: true }],
    item_count: 2, subtotal: '498.00', delivery_fee: '30.00', tax: '24.90', total: '552.90',
    min_order_amount: '100.00', can_checkout: true, problems: [],
  }
  beforeEach(() => {
    auth.user = CUSTOMER
    cartApi.get.mockResolvedValue(CART)
    addressApi.list.mockResolvedValue([{ id: 5, label: 'Home', line1: '12 MG Road', city: 'Pune', is_default: true }])
  })

  it('shows totals and places the order to the default address', async () => {
    orderApi.place.mockResolvedValue({ id: 99 })
    const { router } = renderRoute([
      { path: '/cart', element: <CartPage /> },
      { path: '/orders/:id/pay', element: <p>Pay screen</p> },
    ], { path: '/cart' })
    expect(await screen.findByText('₹552.90')).toBeInTheDocument()
    await screen.findByRole('option', { name: /Home: 12 MG Road/ })
    await userEvent.click(screen.getByRole('button', { name: /Place order/ }))
    expect(orderApi.place).toHaveBeenCalledWith({ address_id: 5, notes: null })
    await waitFor(() => expect(router.state.location.pathname).toBe('/orders/99/pay'))
  })

  it('blocks checkout and explains why', async () => {
    cartApi.get.mockResolvedValue({ ...CART, can_checkout: false, problems: ['Restaurant is currently closed'] })
    renderRoute([{ path: '/cart', element: <CartPage /> }], { path: '/cart' })
    expect(await screen.findByText('Restaurant is currently closed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Place order/ })).toBeDisabled()
  })
})
