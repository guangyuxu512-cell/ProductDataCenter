import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import type { PlatformCode } from '@/entities/platform'
import type { LibraryProduct } from './contracts'
import type { NasDetail, ProductRow } from './nas-contracts'

dayjs.extend(utc)
dayjs.extend(timezone)

export function productTitleLength(value: string): number {
  return Array.from(value).reduce((sum, character) => sum + ((character.codePointAt(0) ?? 0) > 127 ? 2 : 1), 0)
}

export function capturedTime(value: string | null): string {
  return value ? dayjs(value).tz('Asia/Shanghai').format('YYYY-MM-DD HH:mm:ss') : '—'
}

export function platformCode(value: string): PlatformCode | null {
  if (value === 'pinduoduo') return 'pdd'
  if (value === 'douyin' || value === 'pdd' || value === 'taobao') return value
  return null
}

export function priceRange(row: ProductRow): string {
  const lo = row.current_price_min, hi = row.current_price_max
  if (lo === null && hi === null) return '—'
  return lo !== null && hi !== null && lo !== hi ? `${lo}–${hi}` : (lo ?? hi ?? '—')
}

export function detailView(detail: NasDetail): LibraryProduct {
  const row = detail.product
  const platform = platformCode(row.source_platform)
  if (!platform && row.source_platform !== 'manual') throw new Error(`暂不支持该来源平台的详情：${row.source_platform || '未知'}`)
  const imageUrl = (image: NasDetail['images'][number]) => image.source_url || (
    image.rel_path ? `/api/v1/products/${encodeURIComponent(row.product_id)}/images/${image.image_type}/${image.sort_order}` : ''
  )
  const images = (kind: string) => detail.images.filter((image) => image.image_type === kind).map(imageUrl).filter(Boolean)
  return {
    id: row.product_id, productId: row.source_product_id || row.product_id,
    platform, title: row.title, shopName: row.shop_name, skuCount: row.sku_count,
    mainImageCount: row.main_image_count, detailImageCount: row.detail_image_count, skuImageCount: row.sku_image_count,
    groupId: row.group_id, groupName: row.group_name, category: row.category_path || null,
    currentPrice: row.current_price_min === null && row.current_price_max === null ? null : priceRange(row),
    currency: 'CNY', collectedAt: capturedTime(row.captured_at), sourceUrl: null,
    mainImageUrl: images('main')[0] || row.main_image_url, previewMainImageUrls: images('main'),
    detailImageUrls: images('detail'), specDimensions: [], attributes: [], mockEditedAt: null,
    skus: detail.skus.map((sku) => ({
      draftKey: sku.sku_id, sourceSkuId: sku.sku_id, name: sku.sku_name,
      currentPrice: sku.current_price, stockLabel: null, specValues: {},
      imageUrl: detail.images.find((image) => image.image_type === 'sku' && image.sort_order === sku.sort_order)
        ? imageUrl(detail.images.find((image) => image.image_type === 'sku' && image.sort_order === sku.sort_order)!) : null,
    })),
    packageFiles: [], history: [],
  }
}
