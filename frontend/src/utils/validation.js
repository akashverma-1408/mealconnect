/** Client-side checks mirror the API rules for instant feedback; the API re-validates. */
export function validateRegistration(form) {
  const errors = {}
  if (form.full_name.trim().length < 2) errors.full_name = 'Please enter your name'
  if (!/^\S+@\S+\.\S+$/.test(form.email)) errors.email = 'Enter a valid email address'
  if (form.password.length < 8) errors.password = 'At least 8 characters'
  else if (!/[A-Za-z]/.test(form.password) || !/\d/.test(form.password))
    errors.password = 'Use at least one letter and one digit'
  if (form.phone && !/^\+?[\d\s-]{7,15}$/.test(form.phone)) errors.phone = 'Enter a valid phone number'
  return errors
}
