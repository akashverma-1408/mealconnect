/** Small reusable building blocks used by every page. */
import { useEffect, useId, useRef } from 'react'
import { errorMessage, statusLabel } from '../utils/format'

export function Spinner({ label = 'Loading' }) {
  return (
    <div className="spinner" role="status" aria-live="polite">
      <span className="spinner__dot" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  )
}

export function ErrorBox({ error, onRetry }) {
  if (!error) return null
  const message = typeof error === 'string' ? error : errorMessage(error)
  return (
    <div className="alert alert--error" role="alert">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="btn btn--small btn--ghost" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="empty">
      <div className="empty__icon" aria-hidden="true">🍽️</div>
      <h3>{title}</h3>
      {children && <p className="muted">{children}</p>}
      {action}
    </div>
  )
}

/** Renders a react-query result: spinner, error with retry, or children(data). */
export function QueryState({ query, children, loadingLabel }) {
  if (query.isPending) return <Spinner label={loadingLabel} />
  if (query.isError) return <ErrorBox error={query.error} onRetry={() => query.refetch()} />
  return children(query.data)
}

export function Pagination({ page, pages, onChange }) {
  if (!pages || pages <= 1) return null
  return (
    <nav className="pagination" aria-label="Pagination">
      <button type="button" className="btn btn--ghost btn--small" disabled={page <= 1}
        onClick={() => onChange(page - 1)}>← Previous</button>
      <span className="muted">Page {page} of {pages}</span>
      <button type="button" className="btn btn--ghost btn--small" disabled={page >= pages}
        onClick={() => onChange(page + 1)}>Next →</button>
    </nav>
  )
}

export function StatusBadge({ status }) {
  return <span className={`badge badge--${status.toLowerCase()}`}>{statusLabel(status)}</span>
}

export function VegMark({ veg }) {
  return (
    <span className={`veg-mark ${veg ? 'veg-mark--veg' : 'veg-mark--nonveg'}`}
      title={veg ? 'Vegetarian' : 'Non-vegetarian'} aria-label={veg ? 'Vegetarian' : 'Non-vegetarian'} />
  )
}

export function Rating({ value, count }) {
  const n = Number(value)
  return (
    <span className="rating" aria-label={`Rated ${n.toFixed(1)} out of 5`}>
      ★ {count ? n.toFixed(1) : 'New'}
      {count ? <span className="muted"> ({count})</span> : null}
    </span>
  )
}

/** Label + input + error message, wired together for accessibility. */
export function Field({ label, error, hint, as = 'input', children, ...props }) {
  const id = useId()
  const Tag = as
  return (
    <div className={`field ${error ? 'field--error' : ''}`}>
      <label htmlFor={id}>{label}</label>
      {as === 'select' ? (
        <select id={id} aria-invalid={!!error} {...props}>{children}</select>
      ) : (
        <Tag id={id} aria-invalid={!!error} {...props} />
      )}
      {hint && !error && <small className="muted">{hint}</small>}
      {error && <small className="field__error">{error}</small>}
    </div>
  )
}

/** Modal dialog: overlay, role="dialog", closes on Esc or backdrop click. */
export function Modal({ open, title, onClose, children }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    ref.current?.querySelector('input, select, textarea, button')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal__header">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Stat({ label, value, sub }) {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {sub && <div className="stat__sub muted">{sub}</div>}
    </div>
  )
}

/** Tiny dependency-free bar chart for daily series. */
export function BarChart({ points, valueKey = 'revenue', format = (v) => v, label }) {
  const max = Math.max(1, ...points.map((p) => Number(p[valueKey])))
  return (
    <figure className="chart" aria-label={label}>
      <div className="chart__bars">
        {points.map((p) => {
          const v = Number(p[valueKey])
          return (
            <div key={p.date} className="chart__col" title={`${p.date}: ${format(v)}`}>
              <div className="chart__bar" style={{ height: `${(v / max) * 100}%` }} />
            </div>
          )
        })}
      </div>
      <figcaption className="chart__axis muted">
        <span>{points[0]?.date}</span>
        <span>{points.at(-1)?.date}</span>
      </figcaption>
    </figure>
  )
}
