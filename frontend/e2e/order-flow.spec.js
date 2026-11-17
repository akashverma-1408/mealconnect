/**
 * Full marketplace flow in real browsers:
 * customer orders and pays -> owner accepts and delivers -> customer sees it and rates it.
 * Demo accounts come from backend/app/seed.py (local development only).
 */
import { expect, test } from '@playwright/test'

const PASSWORD = 'DemoPass123'

async function login(page, email) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  // Logged in = redirected away from /login. (Waiting for a navbar button is wrong on
  // phones: the hamburger "Menu" button is visible before login too.)
  await expect(page).not.toHaveURL(/\/login$/)
}

async function openMenuIfMobile(page) {
  const toggle = page.getByRole('button', { name: 'Menu' })
  if (await toggle.isVisible()) await toggle.click()
}

test('customer orders, owner delivers, customer rates', async ({ browser }) => {
  // ---------------------------------------------------------------- customer
  const customer = await (await browser.newContext()).newPage()
  await login(customer, 'asha@example.com')

  await customer.goto('/')
  await customer.getByRole('searchbox', { name: /Search restaurants/ }).fill('Spice')
  await customer.getByRole('link', { name: /Spice Route/ }).click()
  await expect(customer.getByRole('heading', { name: 'Spice Route', level: 1 })).toBeVisible()

  await customer.getByRole('button', { name: 'Add Paneer Tikka to cart' }).click()
  await expect(customer.getByText('Paneer Tikka added to cart')).toBeVisible()
  await customer.getByRole('button', { name: /Add Paneer Tikka to cart/ }).click()
  await expect(customer.getByText(/2 in cart/)).toBeVisible()

  await customer.goto('/cart')
  await expect(customer.getByText('₹498.00').first()).toBeVisible() // 2 x 249
  await customer.getByRole('button', { name: /Place order/ }).click()
  await expect(customer).toHaveURL(/\/orders\/\d+\/pay$/)
  const orderId = customer.url().match(/orders\/(\d+)/)[1]

  await customer.getByRole('button', { name: /Pay ₹/ }).click()
  await expect(customer).toHaveURL(new RegExp(`/orders/${orderId}$`))
  await expect(customer.getByText('Placed', { exact: true }).first()).toBeVisible()

  // ---------------------------------------------------------------- owner
  const owner = await (await browser.newContext()).newPage()
  await login(owner, 'owner.spice@example.com')
  await owner.goto('/owner/restaurants/1?tab=orders')
  const row = owner.getByRole('row', { name: new RegExp(`#${orderId}`) })
  await row.getByRole('button', { name: 'Manage' }).click()
  const dialog = owner.getByRole('dialog', { name: `Order #${orderId}` })
  await dialog.getByRole('button', { name: 'Accept order' }).click()
  for (const step of ['preparing', 'out for delivery', 'delivered']) {
    await dialog.getByRole('button', { name: `Mark as ${step}` }).click()
    await expect(owner.getByText(new RegExp(`Order #${orderId}: ${step}`, 'i'))).toBeVisible()
  }

  // ---------------------------------------------------------------- customer again
  await customer.reload()
  await expect(customer.getByText('Delivered', { exact: true }).first()).toBeVisible()
  await customer.getByRole('button', { name: 'Rate this order' }).click()
  const review = customer.getByRole('dialog', { name: 'Rate your order' })
  await review.getByRole('button', { name: '4 stars' }).click()
  await review.getByLabel('Comment (optional)').fill('Tested end to end by Playwright')
  await review.getByRole('button', { name: 'Submit review' }).click()
  await expect(customer.getByText('Thanks for your review!')).toBeVisible()

  // The notification bell picked up the status updates.
  await openMenuIfMobile(customer)
  await customer.getByRole('link', { name: /Notifications/ }).click()
  await expect(customer.getByText('Delivered').first()).toBeVisible()
})

test('guards: anonymous users are sent to login, customers cannot open admin', async ({ page }) => {
  await page.goto('/orders')
  await expect(page).toHaveURL(/\/login$/)
  await login(page, 'ravi@example.com')
  await page.goto('/admin')
  await expect(page).toHaveURL(/\/$/)
})
