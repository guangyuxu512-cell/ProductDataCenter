/** Use the existing Douyin resize template only for known unsigned image URLs. */
export function previewImageUrl(source: string): string {
  try {
    const url = new URL(source)
    if (url.protocol !== 'https:' || !['p3-item.ecombdimg.com', 'p26-item.ecombdimg.com'].includes(url.hostname) || url.port || url.search || url.hash) return source
    const match = url.pathname.match(/^(\/img\/[^~]+)~tplv-5mmsx3fupr-(?:resize|resize_q):\d+:\d+(?::q\d+)?\.(webp|png|jpe?g)$/i)
    if (!match) return source
    url.pathname = `${match[1]}~tplv-5mmsx3fupr-resize:384:0.${match[2]}`
    return url.href
  } catch {
    return source
  }
}
