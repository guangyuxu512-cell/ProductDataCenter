import { expect, test, type Page } from '@playwright/test'
import type { ProductEditorDraft, ProductEditorState } from '../src/features/product-library/model/editor-contracts'

const first = '3760269504500859111', second = '3760269504500859112', manual = 'manual:12345678901234567890'
const groupId = '00000000-0000-4000-8000-000000000001'
const fingerprint = 'a'.repeat(64)
const photo = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120"><rect width="120" height="120" fill="gray"/></svg>')

function makeDraft(title: string): ProductEditorDraft {
  return { title, categoryIds: ['100'], categoryPath: '家居/测试类目', mainImages: [{ id: 'main-0', url: photo }],
    detailImages: [{ id: 'detail-0', url: photo }], attributes: [], imageDimensionId: 'color',
    dimensions: [
      { id: 'color', name: '颜色', values: [{ id: 'black', sourceValueId: 'b', name: '黑色', imageUrl: photo }, { id: 'white', sourceValueId: 'w', name: '白色', imageUrl: '' }] },
      { id: 'style', name: '款式', values: [{ id: 'long', sourceValueId: 'l', name: '长款', imageUrl: '' }, { id: 'short', sourceValueId: 's', name: '短款', imageUrl: '' }] },
    ], skus: [
      { id: 'one', sourceSkuId: '1234567890123456789', sourceLabel: '', specValueIds: { color: 'black', style: 'long' }, unmappedSpecIds: [], price: '19.90', stock: 3, merchantCode: '', state: 'active' },
      { id: 'two', sourceSkuId: '1234567890123456790', sourceLabel: '', specValueIds: { color: 'white', style: 'short' }, unmappedSpecIds: [], price: '20', stock: 0, merchantCode: '', state: 'inactive' },
    ] }
}

function state(productId: string, title: string, revision = 0): ProductEditorState {
  return { productId, revision, sourceFingerprint: fingerprint, sourceChanged: false, draft: makeDraft(title) }
}

function row(id: string, title: string) {
  return { product_id: id, source_product_id: id === manual ? null : id, source_platform: id === manual ? 'manual' : 'douyin',
    group_id: null, group_name: null, title, title_status: '', shop_name: '', category_level_4: '', category_path: '家居/测试类目',
    current_price_min: '19.90', current_price_max: '20.00', sku_count: 2, main_image_count: 1, detail_image_count: 1,
    sku_image_count: 1, main_image_url: photo, captured_at: '2026-10-26T00:18:34Z', updated_at: null,
    asset_rel_path: '', workbook_rel_path: '', raw_rel_path: '' }
}

async function fixtures(page: Page) {
  const states = new Map([[first, state(first, '第一个商品')], [second, state(second, '第二个商品')]])
  const writes: ProductEditorDraft[] = []
  await page.route('**/api/v1/**', async (route) => {
    const { pathname } = new URL(route.request().url()), method = route.request().method()
    if (pathname === '/api/v1/capabilities') return route.fulfill({ json: { groupWrites: true, export: true, productEdit: true, manualCreate: true, assetUploads: false, importProducts: false } })
    if (pathname === '/api/v1/product-groups') return route.fulfill({ json: { groups: [{ groupId, name: '正价品', productCount: 2 }] } })
    if (pathname === '/api/v1/products/manual' && method === 'POST') {
      const title = route.request().postDataJSON().title as string
      const created = state(manual, title, 1); created.draft = { ...created.draft, categoryIds: [], categoryPath: '', mainImages: [], detailImages: [], dimensions: [], skus: [], imageDimensionId: null }
      states.set(manual, created)
      return route.fulfill({ status: 201, json: created })
    }
    if (pathname === '/api/v1/products/group' && method === 'PATCH') return route.fulfill({ json: { updated: route.request().postDataJSON().productIds, groupId } })
    if (pathname === '/api/v1/products') return route.fulfill({ json: { items: [...states.values()].map((item) => row(item.productId, item.draft.title)), total: states.size, totalIncluded: true, limit: 20, offset: 0 } })
    const edit = pathname.match(/^\/api\/v1\/products\/(.+)\/edit-draft$/)
    if (edit) {
      const id = decodeURIComponent(edit[1]), current = states.get(id)!
      if (method === 'GET') return route.fulfill({ json: current })
      const body = route.request().postDataJSON()
      if (body.expectedRevision !== current.revision || body.sourceFingerprint !== fingerprint) return route.fulfill({ status: 409, json: { message: '草稿版本冲突' } })
      writes.push(body.draft)
      const updated = { ...current, revision: current.revision + 1, draft: body.draft as ProductEditorDraft }
      states.set(id, updated); return route.fulfill({ json: updated })
    }
    const detail = pathname.match(/^\/api\/v1\/products\/(.+)$/)
    if (detail) {
      const id = decodeURIComponent(detail[1]), current = states.get(id)!
      return route.fulfill({ json: { product: row(id, current.draft.title), skus: [], images: [] } })
    }
    return route.fulfill({ status: 404, json: { message: 'fixture endpoint not defined' } })
  })
  return { states, writes }
}

test('左侧范围独立，规格切换保留 SKU 编码，切换商品保护草稿', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const { writes } = await fixtures(page)
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品' }).first().click()
  await expect(page.getByText('编辑商品', { exact: true })).toBeVisible()
  const range = page.locator('.product-preview__navigator'), editor = page.locator('.product-editor__main')
  expect((await range.boundingBox())!.x).toBeLessThan((await editor.boundingBox())!.x)
  await page.getByText('规格与 SKU', { exact: true }).click()
  await expect(page.getByText('未采集', { exact: true })).toHaveCount(2)
  await page.getByLabel('SKU 商家编码').first().fill('000123-A')
  await page.getByRole('switch', { name: '款式添加规格图' }).click()
  await page.getByRole('button', { name: '开启', exact: true }).click()
  await expect(page.locator('.product-editor__axis').first().getByLabel('规格类型')).toHaveValue('款式')
  await expect(page.getByLabel('SKU 商家编码').first()).toHaveValue('000123-A')
  await page.getByText('基本信息', { exact: true }).click()
  await page.getByLabel('商品标题', { exact: true }).fill('已修改的商品标题')
  await range.getByRole('button', { name: '下一件' }).click()
  await expect(page.getByText('当前商品有未保存的修改')).toBeVisible()
  await page.getByRole('button', { name: '保存并切换' }).click()
  await expect(page.getByLabel('商品标题', { exact: true })).toHaveValue('第二个商品')
  expect(writes[0].title).toBe('已修改的商品标题')
  expect(writes[0].skus.find((sku) => sku.id === 'one')?.merchantCode).toBe('000123-A')
  expect(writes[0].imageDimensionId).toBe('style')
  await range.getByRole('button', { name: '上一件' }).click()
  await expect(page.getByLabel('商品标题', { exact: true })).toHaveValue('已修改的商品标题')
  expect(errors).toEqual([])
})

test('手动创建使用云库编号，并保持预检与数据包未完成状态', async ({ page }) => {
  await fixtures(page)
  await page.goto('/#/products')
  await page.getByRole('button', { name: '手动创建商品' }).click()
  await page.getByLabel('新商品标题').fill('手动测试商品')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByLabel('商品标题', { exact: true })).toHaveValue('手动测试商品')
  await expect(page.getByText('待预检 · 数据包待生成')).toBeVisible()
  await expect(page.locator('.product-editor__main').getByRole('button', { name: '导出商品数据包', exact: true })).toBeDisabled()
})

test('超长标题保留原文但不能保存，修改至上限后可以保存', async ({ page }) => {
  const { writes } = await fixtures(page)
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品' }).first().click()
  const title = page.getByLabel('商品标题', { exact: true })
  await title.fill('商'.repeat(31))
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('请填写商品标题，最多 60 个计数单位')).toBeVisible()
  await expect(title).toHaveValue('商'.repeat(31))
  expect(writes).toHaveLength(0)
  await title.fill('商'.repeat(30))
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
})
