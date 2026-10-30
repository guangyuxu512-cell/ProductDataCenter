import { describe, expect, it } from 'vitest'
import { thumbnailImageUrl } from './thumbnail-image-url'

describe('thumbnailImageUrl', () => {
  it('derives a 144px WebP for the verified unsigned Douyin templates', () => {
    for (const host of ['p3-item.ecombdimg.com', 'p26-item.ecombdimg.com']) {
      const source = `https://${host}/img/ecom-shop-material/example~tplv-5mmsx3fupr-resize_q:1080:1080:q90.webp`
      expect(thumbnailImageUrl(source)).toBe(`https://${host}/img/ecom-shop-material/example~tplv-5mmsx3fupr-resize_q:144:144:q80.webp`)
      expect(thumbnailImageUrl(source.replace('resize_q:1080:1080:q90', 'resize:1200:0'))).toBe(`https://${host}/img/ecom-shop-material/example~tplv-5mmsx3fupr-resize_q:144:144:q80.webp`)
    }
  })

  it('does not alter signed, unknown, unsupported, local, or already small images', () => {
    for (const source of [
      'https://p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:800:800.webp?signature=abc',
      'https://p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:800:800.webp#signed',
      'https://p3-item.ecombdimg.com:8443/img/example~tplv-5mmsx3fupr-resize:800:800.webp',
      'https://user:password@p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:800:800.webp',
      'https://p3-item.ecombdimg.com.evil.invalid/img/example~tplv-5mmsx3fupr-resize:800:800.webp',
      'https://p3-item.ecombdimg.com/img/example~tplv-another-resize:800:800.webp',
      'https://p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:800:800.jpeg',
      'https://p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:144:144.webp',
      'https://img.pddpic.com/example.jpeg',
      'http://p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:800:800.webp',
      '/api/v1/products/1/images/main/0',
      'data:image/svg+xml,example',
      'not a URL',
    ]) expect(thumbnailImageUrl(source)).toBe(source)
  })
})
