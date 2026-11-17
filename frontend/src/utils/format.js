/** Formatting helpers. Money arrives from the API as strings like "249.00". */

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' })

export function money(value) {
  const n = Number(value)
  return Number.isFinite(n) ? inr.format(n) : '—'
}

export function dateTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

export function shortDate(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

export const STATUS_LABELS = {
  PENDING_PAYMENT: 'Awaiting payment',
  PLACED: 'Placed',
  ACCEPTED: 'Accepted',
  REJECTED: 'Rejected',
  PREPARING: 'Preparing',
  OUT_FOR_DELIVERY: 'Out for delivery',
  DELIVERED: 'Delivered',
  CANCELLED: 'Cancelled',
}

export const statusLabel = (s) => STATUS_LABELS[s] || s.replaceAll('_', ' ')

/** The happy path, used to draw the tracking progress bar. */
export const ORDER_FLOW = ['PLACED', 'ACCEPTED', 'PREPARING', 'OUT_FOR_DELIVERY', 'DELIVERED']

/** Next status an owner can move an order to (mirrors the backend state machine). */
export const OWNER_NEXT = {
  ACCEPTED: 'PREPARING',
  PREPARING: 'OUT_FOR_DELIVERY',
  OUT_FOR_DELIVERY: 'DELIVERED',
}

/** Turn an axios error into a message for the user, using the API's error format. */
export function errorMessage(err, fallback = 'Something went wrong. Please try again.') {
  const apiError = err?.response?.data?.error
  if (apiError) {
    if (apiError.code === 'VALIDATION_ERROR' && Array.isArray(apiError.details)) {
      return apiError.details.map((d) => `${d.field || 'input'}: ${d.message}`).join(' · ')
    }
    return apiError.message
  }
  if (err?.code === 'ERR_NETWORK') return 'Cannot reach the server. Is the API running?'
  return fallback
}

export const errorCode = (err) => err?.response?.data?.error?.code
