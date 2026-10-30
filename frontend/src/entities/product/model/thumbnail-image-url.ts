/**
 * The collector's original image URL remains the source of truth. Only derive
 * a display URL for the unsigned CDN templates verified against existing images.
 */
export function thumbnailImageUrl(source: string): string {
  try {
    const url = new URL(source)
    if (
      url.protocol !== 'https:' ||
      url.username || url.password || url.port || url.search || url.hash
    ) return source

    if (['img.pddpic.com', 'commimg.pddpic.com'].includes(url.hostname)) {
      if (!/\.(?:jpe?g|png|webp)$/i.test(url.pathname)) return source
      url.search = '?imageView2/2/w/144/q/80/format/webp'
      return url.href
    }

    if (!['p3-item.ecombdimg.com', 'p26-item.ecombdimg.com'].includes(url.hostname)) return source

    const match = url.pathname.match(/^(\/img\/[^~]+)~tplv-5mmsx3fupr-(?:resize|resize_q):(\d+):(\d+)(?::q\d+)?\.webp$/i)
    // Do not request a larger version if the source URL is already small.
    if (!match || Number(match[2]) <= 144) return source

    url.pathname = `${match[1]}~tplv-5mmsx3fupr-resize_q:144:144:q80.webp`
    return url.href
  } catch {
    return source
  }
}
