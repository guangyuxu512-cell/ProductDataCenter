import { describe, expect, it } from 'vitest'
import { previewImageUrl } from './preview-image-url'

describe('previewImageUrl', () => {
  it('only derives a smaller preview for a known Douyin resize URL', () => {
    const source = 'https://p3-item.ecombdimg.com/img/ecom-shop-material/example~tplv-5mmsx3fupr-resize_q:1080:1080:q90.webp'
    expect(previewImageUrl(source)).toBe('https://p3-item.ecombdimg.com/img/ecom-shop-material/example~tplv-5mmsx3fupr-resize:384:0.webp')
    expect(previewImageUrl('https://p26-item.ecombdimg.com/img/ecom-shop-material/example~tplv-5mmsx3fupr-resize:1200:0.png')).toContain('resize:384:0.png')
  })

  it('leaves signed, unknown, local and malformed sources unchanged', () => {
    for (const source of [
      'https://p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:800:800.webp?signature=abc',
      'https://p3-item.ecombdimg.com.evil.invalid/img/example~tplv-5mmsx3fupr-resize:800:800.webp',
      'https://p3-item.ecombdimg.com/img/example~tplv-another-resize:800:800.webp',
      'http://p3-item.ecombdimg.com/img/example~tplv-5mmsx3fupr-resize:800:800.webp',
      '/api/v1/products/1/images/main/0',
      'data:image/svg+xml,example',
    ]) expect(previewImageUrl(source)).toBe(source)
  })
})
