/**
 * The collector's original image URL remains the source of truth. Only derive
 * a display URL for the unsigned Douyin WebP template verified in production.
 */
export function thumbnailImageUrl(source: string): string {
  try {
    const url = new URL(source)
    if (
      url.protocol !== 'https:' ||
      !['p3-item.ecombdimg.com', 'p26-item.ecombdimg.com'].includes(url.hostname) ||
      url.username || url.password || url.port || url.search || url.hash
    ) return source

    const match = url.pathname.match(/^(\/img\/[^~]+)~tplv-5mmsx3fupr-(?:resize|resize_q):(\d+):(\d+)(?::q\d+)?\.webp$/i)
    // Do not request a larger version if the source URL is already small.
    if (!match || Number(match[2]) <= 144) return source

    url.pathname = `${match[1]}~tplv-5mmsx3fupr-resize_q:144:144:q80.webp`
    return url.href
  } catch {
    return source
  }
}
