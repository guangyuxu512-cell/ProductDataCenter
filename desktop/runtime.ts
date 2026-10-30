export const defaultProductUrl = 'http://192.168.0.102:3612/'

/** HTTP is supported only for the existing private NAS network. */
export function resolveProductUrl(value = defaultProductUrl): URL {
  const url = new URL(value)
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('商品云库地址必须是无凭据的服务根地址')
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error('商品云库地址必须使用 HTTP 或 HTTPS')
  }
  if (url.protocol === 'http:' && !isPrivateIPv4OrLocalhost(url.hostname)) {
    throw new Error('HTTP 只允许用于局域网；其他地址需要 HTTPS')
  }
  return url
}

function isPrivateIPv4OrLocalhost(host: string): boolean {
  if (host === 'localhost') return true
  const pieces = host.split('.')
  if (pieces.length !== 4 || pieces.some((part) => !/^\d+$/.test(part) || Number(part) > 255)) return false
  const [first, second] = pieces.map(Number)
  return first === 127 || first === 10 || (first === 172 && second >= 16 && second <= 31) || (first === 192 && second === 168)
}

export function isTrustedNavigation(value: string, origin: string): boolean {
  try {
    return new URL(value).origin === origin
  } catch {
    return false
  }
}
