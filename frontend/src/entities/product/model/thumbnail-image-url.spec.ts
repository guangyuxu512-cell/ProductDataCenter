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

  it('derives a 144px CDN view for unsigned PDD images on the verified hosts', () => {
    for (const host of ['img.pddpic.com', 'commimg.pddpic.com']) {
      for (const ext of ['jpeg.a.jpeg', 'jpeg', 'png']) {
        const source = `https://${host}/mms-material-img/example.${ext}`
        expect(thumbnailImageUrl(source)).toBe(`${source}?imageView2/2/w/144/q/80/format/webp`)
      }
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
      'https://img.pddpic.com/example.jpeg?signature=abc',
      'https://img.pddpic.com.evil.invalid/example.jpeg',
      'https://img.pddpic.com/example.gif',
      'http://p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:800:800.webp',
      '/api/v1/products/1/images/main/0',
      'data:image/svg+xml,example',
      'not a URL',
    ]) expect(thumbnailImageUrl(source)).toBe(source)
  })
})
