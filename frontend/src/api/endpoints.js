/**
 * One small function per backend endpoint. Pages never build URLs themselves,
 * so if an endpoint changes there is exactly one place to update.
 */
import { api } from './client'

const data = (promise) => promise.then((res) => res.data)

export const authApi = {
  register: (body) => data(api.post('/auth/register', body)),
  login: (body) => data(api.post('/auth/login', body)),
  logout: (refresh_token) => api.post('/auth/logout', { refresh_token }),
  me: () => data(api.get('/users/me')),
  updateMe: (body) => data(api.patch('/users/me', body)),
  changePassword: (body) => api.post('/users/me/change-password', body),
}

export const addressApi = {
  list: () => data(api.get('/users/me/addresses')),
  create: (body) => data(api.post('/users/me/addresses', body)),
  update: (id, body) => data(api.patch(`/users/me/addresses/${id}`, body)),
  remove: (id) => api.delete(`/users/me/addresses/${id}`),
}

export const catalogueApi = {
  restaurants: (params) => data(api.get('/restaurants', { params })),
  restaurant: (id) => data(api.get(`/restaurants/${id}`)),
  menu: (id) => data(api.get(`/restaurants/${id}/menu`)),
  reviews: (id, params) => data(api.get(`/restaurants/${id}/reviews`, { params })),
  searchItems: (params) => data(api.get('/search/menu-items', { params })),
}

export const cartApi = {
  get: () => data(api.get('/cart')),
  add: (menu_item_id, quantity = 1) => data(api.post('/cart/items', { menu_item_id, quantity })),
  update: (menu_item_id, quantity) => data(api.patch(`/cart/items/${menu_item_id}`, { quantity })),
  remove: (menu_item_id) => data(api.delete(`/cart/items/${menu_item_id}`)),
  clear: () => api.delete('/cart'),
}

export const orderApi = {
  place: (body) => data(api.post('/orders', body)),
  list: (params) => data(api.get('/orders', { params })),
  get: (id) => data(api.get(`/orders/${id}`)),
  cancel: (id, reason) => data(api.post(`/orders/${id}/cancel`, { reason })),
  review: (id, body) => data(api.post(`/orders/${id}/review`, body)),
}

export const paymentApi = {
  checkout: (orderId) => data(api.post(`/payments/orders/${orderId}/checkout`)),
  get: (orderId) => data(api.get(`/payments/orders/${orderId}`)),
  sandboxPay: (orderId, outcome) =>
    data(api.post(`/payments/sandbox/orders/${orderId}/pay`, null, { params: { outcome } })),
}

export const complaintApi = {
  create: (body) => data(api.post('/complaints', body)),
  list: (params) => data(api.get('/complaints', { params })),
}

export const notificationApi = {
  list: (params) => data(api.get('/notifications', { params })),
  read: (id) => data(api.patch(`/notifications/${id}/read`)),
  readAll: () => data(api.post('/notifications/read-all')),
}

const R = (rid) => `/owner/restaurants/${rid}`
export const ownerApi = {
  restaurants: () => data(api.get('/owner/restaurants')),
  createRestaurant: (body) => data(api.post('/owner/restaurants', body)),
  restaurant: (rid) => data(api.get(R(rid))),
  updateRestaurant: (rid, body) => data(api.patch(R(rid), body)),
  menu: (rid) => data(api.get(`${R(rid)}/menu`)),
  createCategory: (rid, body) => data(api.post(`${R(rid)}/categories`, body)),
  updateCategory: (rid, cid, body) => data(api.patch(`${R(rid)}/categories/${cid}`, body)),
  deleteCategory: (rid, cid) => api.delete(`${R(rid)}/categories/${cid}`),
  createItem: (rid, body) => data(api.post(`${R(rid)}/menu-items`, body)),
  updateItem: (rid, iid, body) => data(api.patch(`${R(rid)}/menu-items/${iid}`, body)),
  setAvailability: (rid, iid, is_available) =>
    data(api.patch(`${R(rid)}/menu-items/${iid}/availability`, { is_available })),
  deleteItem: (rid, iid) => api.delete(`${R(rid)}/menu-items/${iid}`),
  orders: (rid, params) => data(api.get(`${R(rid)}/orders`, { params })),
  order: (oid) => data(api.get(`/owner/orders/${oid}`)),
  accept: (oid) => data(api.post(`/owner/orders/${oid}/accept`)),
  reject: (oid, reason) => data(api.post(`/owner/orders/${oid}/reject`, { reason })),
  setStatus: (oid, status) => data(api.patch(`/owner/orders/${oid}/status`, { status })),
  analytics: (rid, params) => data(api.get(`${R(rid)}/analytics`, { params })),
}

export const adminApi = {
  users: (params) => data(api.get('/admin/users', { params })),
  setUserStatus: (id, body) => data(api.patch(`/admin/users/${id}/status`, body)),
  restaurants: (params) => data(api.get('/admin/restaurants', { params })),
  setRestaurantStatus: (id, body) => data(api.patch(`/admin/restaurants/${id}/status`, body)),
  orders: (params) => data(api.get('/admin/orders', { params })),
  order: (id) => data(api.get(`/admin/orders/${id}`)),
  cancelOrder: (id, reason) => data(api.post(`/admin/orders/${id}/cancel`, { reason })),
  complaints: (params) => data(api.get('/admin/complaints', { params })),
  updateComplaint: (id, body) => data(api.patch(`/admin/complaints/${id}`, body)),
  analytics: (params) => data(api.get('/admin/analytics/overview', { params })),
  auditLogs: (params) => data(api.get('/admin/audit-logs', { params })),
}
