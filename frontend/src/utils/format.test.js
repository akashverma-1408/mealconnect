import { describe, expect, it } from 'vitest'
import { errorCode, errorMessage, money, statusLabel } from './format'
import { validateRegistration } from './validation'
import { apiError } from '../test/utils'

describe('money', () => {
  it('formats API money strings as Indian rupees', () => {
    expect(money('1234.50')).toBe('₹1,234.50')
    expect(money('0.00')).toBe('₹0.00')
  })
  it('shows a dash for invalid values', () => {
    expect(money(undefined)).toBe('—')
  })
})

describe('errorMessage', () => {
  it('uses the API error message', () => {
    expect(errorMessage(apiError(409, 'EMAIL_TAKEN', 'Email already registered'))).toBe('Email already registered')
    expect(errorCode(apiError(409, 'EMAIL_TAKEN'))).toBe('EMAIL_TAKEN')
  })
  it('lists validation errors per field', () => {
    const err = apiError(422, 'VALIDATION_ERROR', 'Request validation failed', [
      { field: 'email', message: 'invalid email' },
      { field: 'password', message: 'too short' },
    ])
    expect(errorMessage(err)).toBe('email: invalid email · password: too short')
  })
  it('explains network failures', () => {
    expect(errorMessage({ code: 'ERR_NETWORK' })).toMatch(/Cannot reach the server/)
  })
})

describe('statusLabel', () => {
  it('maps order statuses to friendly labels', () => {
    expect(statusLabel('OUT_FOR_DELIVERY')).toBe('Out for delivery')
  })
})

describe('validateRegistration', () => {
  const valid = { full_name: 'Asha Rao', email: 'asha@example.com', phone: '', password: 'Secret123' }
  it('accepts valid input', () => {
    expect(validateRegistration(valid)).toEqual({})
  })
  it('mirrors the backend password rules', () => {
    expect(validateRegistration({ ...valid, password: 'short1' }).password).toMatch(/8 characters/)
    expect(validateRegistration({ ...valid, password: 'lettersonly' }).password).toMatch(/digit/)
  })
  it('flags bad email and phone', () => {
    const errors = validateRegistration({ ...valid, email: 'nope', phone: 'abc' })
    expect(Object.keys(errors).sort()).toEqual(['email', 'phone'])
  })
})
