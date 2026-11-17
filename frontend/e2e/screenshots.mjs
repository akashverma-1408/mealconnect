// Captures README screenshots from the running dev stack:  node e2e/screenshots.mjs
import { chromium } from '@playwright/test'

const OUT = new URL('../../docs/screenshots/', import.meta.url).pathname
const BASE = process.env.BASE_URL || 'http://localhost:5173'
const PASSWORD = 'DemoPass123'
const browser = await chromium.launch()

async function session(email, viewport = { width: 1280, height: 800 }) {
  const ctx = await browser.newContext({ viewport, colorScheme: 'light' })
  const page = await ctx.newPage()
  if (email) {
    await page.goto(`${BASE}/login`)
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Log in' }).click()
    await page.waitForURL((u) => !u.pathname.endsWith('/login'))
  }
  return page
}
const shot = async (page, name, path, ready) => {
  await page.goto(`${BASE}${path}`)
  await page.getByText(ready).first().waitFor()
  await page.waitForTimeout(400)
  await page.screenshot({ path: `${OUT}${name}.png` })
  console.log('saved', name)
}

const guest = await session(null)
await shot(guest, '01-home', '/', 'Spice Route')
await shot(guest, '02-menu', '/restaurants/1', 'Paneer Tikka')

const customer = await session('asha@example.com')
await customer.goto(`${BASE}/restaurants/1`)
await customer.getByRole('button', { name: 'Add Paneer Tikka to cart' }).click()
await customer.getByRole('button', { name: /Add Paneer Tikka to cart/ }).click()
await shot(customer, '03-cart', '/cart', 'Checkout')
await customer.getByRole('button', { name: /Place order/ }).click()
await customer.waitForURL(/\/pay$/)
await customer.getByRole('button', { name: /Pay ₹/ }).click()
await customer.waitForURL(/\/orders\/\d+$/)
await customer.getByText('Timeline').waitFor()
await customer.waitForTimeout(400)
await customer.screenshot({ path: `${OUT}04-order-tracking.png` })
console.log('saved 04-order-tracking')

const owner = await session('owner.spice@example.com')
await shot(owner, '05-owner-analytics', '/owner/restaurants/1?tab=analytics', 'Daily revenue')
await shot(owner, '06-owner-menu', '/owner/restaurants/1?tab=menu', 'Add dish')

const admin = await session('admin@example.com')
await shot(admin, '07-admin-overview', '/admin', 'Top restaurants')

const phone = await session('asha@example.com', { width: 390, height: 844 })
await shot(phone, '08-mobile-menu', '/restaurants/1', 'Paneer Tikka')

await browser.close()
