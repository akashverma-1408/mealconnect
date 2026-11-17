/** Landing page for each role after login. */
export function homeFor(role) {
  if (role === 'admin') return '/admin'
  if (role === 'restaurant_owner') return '/owner'
  return '/'
}
