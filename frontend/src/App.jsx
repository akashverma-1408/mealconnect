/**
 * App root: providers (server-state cache, auth, toasts) + the route table.
 *
 * Route groups are wrapped in <RequireAuth roles=[...]> so each role only reaches its
 * own pages. The backend enforces the same rules — the frontend guard is for UX only.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { AuthProvider } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'
import Layout from './components/Layout'
import { ToastProvider } from './components/Toast'
import HomePage from './pages/public/HomePage'
import RestaurantPage from './pages/public/RestaurantPage'
import LoginPage from './pages/public/LoginPage'
import RegisterPage from './pages/public/RegisterPage'
import NotFoundPage from './pages/public/NotFoundPage'
import CartPage from './pages/customer/CartPage'
import PaymentPage from './pages/customer/PaymentPage'
import OrdersPage from './pages/customer/OrdersPage'
import OrderDetailPage from './pages/customer/OrderDetailPage'
import ComplaintsPage from './pages/customer/ComplaintsPage'
import ProfilePage from './pages/customer/ProfilePage'
import NotificationsPage from './pages/customer/NotificationsPage'
import OwnerDashboard from './pages/owner/OwnerDashboard'
import OwnerRestaurantPage from './pages/owner/OwnerRestaurantPage'
import AdminPage from './pages/admin/AdminPage'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000, // reuse fetched data for 30 s before refetching
        retry: (count, error) => count < 2 && !(error?.response?.status < 500),
        refetchOnWindowFocus: false,
      },
    },
  })
}

export const routes = [
  {
    element: <Layout />,
    children: [
      { path: '/', element: <HomePage /> },
      { path: '/restaurants/:id', element: <RestaurantPage /> },
      { path: '/login', element: <LoginPage /> },
      { path: '/register', element: <RegisterPage /> },
      {
        element: <RequireAuth />,
        children: [
          { path: '/profile', element: <ProfilePage /> },
          { path: '/notifications', element: <NotificationsPage /> },
        ],
      },
      {
        element: <RequireAuth roles={['customer']} />,
        children: [
          { path: '/cart', element: <CartPage /> },
          { path: '/orders', element: <OrdersPage /> },
          { path: '/orders/:id', element: <OrderDetailPage /> },
          { path: '/orders/:id/pay', element: <PaymentPage /> },
          { path: '/complaints', element: <ComplaintsPage /> },
        ],
      },
      {
        element: <RequireAuth roles={['restaurant_owner']} />,
        children: [
          { path: '/owner', element: <OwnerDashboard /> },
          { path: '/owner/restaurants/:id', element: <OwnerRestaurantPage /> },
        ],
      },
      {
        element: <RequireAuth roles={['admin']} />,
        children: [{ path: '/admin', element: <AdminPage /> }],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]

const router = createBrowserRouter(routes)
const queryClient = createQueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  )
}
