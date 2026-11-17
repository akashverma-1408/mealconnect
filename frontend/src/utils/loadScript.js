/** Load an external script once (e.g. a payment gateway's checkout widget). */
const loaded = new Map()

export function loadScript(src) {
  if (!loaded.has(src)) {
    loaded.set(
      src,
      new Promise((resolve, reject) => {
        const el = document.createElement('script')
        el.src = src
        el.async = true
        el.onload = resolve
        el.onerror = () => {
          loaded.delete(src)
          reject(new Error(`Could not load ${src}`))
        }
        document.body.appendChild(el)
      }),
    )
  }
  return loaded.get(src)
}
