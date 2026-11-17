/** Render a page inside the same providers the real app uses, at a given URL. */
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { ToastProvider } from '../components/Toast'

export function renderRoute(routes, { path = '/' } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  )
  return { ...utils, router, queryClient }
}

/** Build an axios-like error with the API's error body. */
export function apiError(status, code, message = code, details = null) {
  const err = new Error(message)
  err.response = { status, data: { error: { code, message, details, request_id: 'test' } } }
  return err
}
