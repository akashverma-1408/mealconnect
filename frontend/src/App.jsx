/**
 * App root: providers (server-state cache, auth, toasts) + the route table.
 *
 * Route groups are wrapped in <RequireAuth roles=[...]> so each role only reaches its
 * own pages. The backend enforces the same rules — the frontend guard is for UX only.
 */
import { lazy } from 'react'
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
// Code splitting: pages behind a login are separate JS chunks, downloaded only when
// visited. A customer never downloads the owner dashboard or the admin console.
const CartPage = lazy(() => import('./pages/customer/CartPage'))
const PaymentPage = lazy(() => import('./pages/customer/PaymentPage'))
const OrdersPage = lazy(() => import('./pages/customer/OrdersPage'))
const OrderDetailPage = lazy(() => import('./pages/customer/OrderDetailPage'))
const ComplaintsPage = lazy(() => import('./pages/customer/ComplaintsPage'))
const ProfilePage = lazy(() => import('./pages/customer/ProfilePage'))
const NotificationsPage = lazy(() => import('./pages/customer/NotificationsPage'))
const OwnerDashboard = lazy(() => import('./pages/owner/OwnerDashboard'))
const OwnerRestaurantPage = lazy(() => import('./pages/owner/OwnerRestaurantPage'))
const AdminPage = lazy(() => import('./pages/admin/AdminPage'))

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
