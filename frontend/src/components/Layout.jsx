import { Suspense, useState, useSyncExternalStore } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import { cartApi, notificationApi } from '../api/endpoints'
import { serverWaking } from '../api/client'
import { Spinner } from './ui'

const LINKS = {
  guest: [{ to: '/', label: 'Restaurants', end: true }],
  customer: [
    { to: '/', label: 'Restaurants', end: true },
    { to: '/orders', label: 'My orders' },
    { to: '/complaints', label: 'Help' },
  ],
  restaurant_owner: [{ to: '/owner', label: 'My restaurants' }],
  admin: [{ to: '/admin', label: 'Admin console' }],
}

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const isCustomer = user?.role === 'customer'
  const waking = useSyncExternalStore(serverWaking.subscribe, serverWaking.getSnapshot)

  // Shared react-query keys: any page that changes the cart invalidates ['cart'].
  const cart = useQuery({ queryKey: ['cart'], queryFn: cartApi.get, enabled: isCustomer })
  const unread = useQuery({
    queryKey: ['notifications', 'unread-count'],
    queryFn: () => notificationApi.list({ is_read: false, size: 1 }),
    enabled: !!user,
    refetchInterval: 30000, // poll every 30 s (WebSockets would be the next step)
  })

  const links = LINKS[user?.role || 'guest']
  const close = () => setMenuOpen(false)

  async function handleLogout() {
    close()
    // Leave protected pages first; otherwise the route guard sees "no user" and
    // redirects to /login before we get the chance to go home.
    navigate('/')
    await logout()
  }

  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      {waking && (
        <div className="server-waking" role="status">
          Waking up the server — the free demo host sleeps when idle. This can take up to a minute…
        </div>
      )}
      <header className="navbar">
        <div className="container navbar__inner">
          <Link to="/" className="brand" onClick={close}>
            <span className="brand__logo" aria-hidden="true">🍲</span> MealConnect
          </Link>
          <button type="button" className="icon-btn navbar__toggle" aria-label="Menu"
            aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>☰</button>
          <nav className={`navbar__links ${menuOpen ? 'is-open' : ''}`} aria-label="Main">
            {links.map((l) => (
              <NavLink key={l.to} to={l.to} end={l.end} onClick={close}>{l.label}</NavLink>
            ))}
            {user ? (
              <>
                <NavLink to="/notifications" onClick={close} className="nav-icon">
                  🔔 <span className="sr-only">Notifications</span>
                  {unread.data?.total > 0 && <span className="count">{unread.data.total}</span>}
                </NavLink>
                {isCustomer && (
                  <NavLink to="/cart" onClick={close} className="nav-icon">
                    🛒 Cart
                    {cart.data?.item_count > 0 && <span className="count">{cart.data.item_count}</span>}
                  </NavLink>
                )}
                <NavLink to="/profile" onClick={close}>{user.full_name.split(' ')[0]}</NavLink>
                <button type="button" className="btn btn--ghost btn--small" onClick={handleLogout}>
                  Log out
                </button>
              </>
            ) : (
              <>
                <NavLink to="/login" onClick={close}>Log in</NavLink>
                <Link to="/register" className="btn btn--primary btn--small" onClick={close}>Sign up</Link>
              </>
            )}
          </nav>
        </div>
      </header>
      <main id="main" className="container main">
        {/* Lazy-loaded pages show a spinner while their chunk downloads. */}
        <Suspense fallback={<Spinner label="Loading page" />}>
          <Outlet />
        </Suspense>
      </main>
      <footer className="footer">
        <div className="container muted">© {new Date().getFullYear()} MealConnect · Demo project · Payments run in sandbox mode</div>
      </footer>
    </div>
  )
}
