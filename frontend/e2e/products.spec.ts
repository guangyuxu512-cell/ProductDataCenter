import { expect, test, type Page } from '@playwright/test'

const firstId = '3760269504500859111'
const image = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120"><rect width="120" height="120" fill="#e2e8f0"/><rect x="30" y="25" width="60" height="75" rx="8" fill="#94a3b8"/></svg>')
const product = (id: string, platform = 'douyin') => ({
  product_id: id, source_product_id: id.split(':').at(-1), source_platform: platform,
  group_id: null, group_name: null, title: '厨房收纳盒 · 隔离测试商品', title_status: '', shop_name: '测试店铺',
  category_level_4: '', category_path: '家居/厨房/收纳', current_price_min: '19.99', current_price_max: '29.99',
  sku_count: 2, main_image_count: 1, detail_image_count: 1, sku_image_count: 1,
  main_image_url: image, captured_at: '2026-10-26T00:18:34.999999Z', updated_at: null,
  asset_rel_path: '', workbook_rel_path: '', raw_rel_path: '',
})

async function fixtures(page: Page) {
  const listRequests: URL[] = []
  const groups = [{ groupId: '00000000-0000-4000-8000-000000000001', name: '正价品', productCount: 2 }]
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const method = route.request().method()
    if (url.pathname === '/api/v1/capabilities') return route.fulfill({ json: { groupWrites: true, export: true, productEdit: false, importProducts: false } })
    if (url.pathname === '/api/v1/product-groups' && method === 'GET') return route.fulfill({ json: { groups } })
    if (url.pathname === '/api/v1/product-groups' && method === 'POST') {
      const name = route.request().postDataJSON().name
      const group = { groupId: '00000000-0000-4000-8000-000000000002', name, productCount: 0 }
      groups.push(group); return route.fulfill({ json: { group } })
    }
    if (url.pathname.startsWith('/api/v1/product-groups/') && method === 'PATCH') {
      const group = groups.find((item) => url.pathname.endsWith(item.groupId))!
      group.name = route.request().postDataJSON().name
      return route.fulfill({ json: { group } })
    }
    if (url.pathname === '/api/v1/products') {
      listRequests.push(url)
      const platform = url.searchParams.get('platform')
      const total = platform === 'pinduoduo' ? 2 : 60
      const offset = Number(url.searchParams.get('offset'))
      const ids = Array.from({ length: Math.min(20, total) }, (_, i) => platform === 'pinduoduo' ? `pdd:${3837817973876326524n + BigInt(i)}` : String(BigInt(firstId) + BigInt(offset + i)))
      return route.fulfill({ json: { items: ids.map((id) => product(id, platform || 'douyin')), total: url.searchParams.get('includeTotal') === 'false' ? null : total,
        totalIncluded: url.searchParams.get('includeTotal') !== 'false', limit: 20, offset } })
    }
    if (url.pathname.startsWith('/api/v1/products/')) {
      const id = decodeURIComponent(url.pathname.split('/').at(-1)!)
      return route.fulfill({ json: { product: product(id),
        skus: [{ sku_id: 'sku-1', sku_name: '白色', current_price: '19.99', image_rel_path: '', sort_order: 0 }],
        images: ['main', 'detail', 'sku'].map((image_type) => ({ image_type, sort_order: 0, rel_path: '', source_url: image })) } })
    }
    return route.fulfill({ status: 404, json: { message: 'fixture endpoint not defined' } })
  })
  return { listRequests }
}

test('中控布局、内部滚动、详情、复制和分页总数复用', async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const { listRequests } = await fixtures(page)
  await page.goto('/#/products')
  await expect(page.locator('.pagination-bar')).toContainText('共 60 条')
  const metrics = await page.evaluate(() => {
    const sidebar = document.querySelector('.app-shell__sidebar')!.getBoundingClientRect()
    const topbar = document.querySelector('.app-shell__topbar')!.getBoundingClientRect()
    const outer = document.querySelector('.app-shell__content')!
    return { sidebar: sidebar.width, topbar: topbar.height, outerHeight: outer.clientHeight,
      outerScroll: outer.scrollHeight, scrollWidth: document.documentElement.scrollWidth, width: innerWidth }
  })
  expect(metrics.sidebar).toBe(228); expect(metrics.topbar).toBe(54)
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.width)
  expect(metrics.outerScroll).toBeLessThanOrEqual(metrics.outerHeight + 1)
  await page.evaluate(() => { Object.defineProperty(navigator, 'clipboard', { configurable: true,
    value: { writeText: async (text: string) => { (window as unknown as { copiedId: string }).copiedId = text } } }) })
  await page.getByRole('button', { name: '复制商品ID', exact: true }).first().click()
  await expect(page.getByText('商品ID已复制')).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { copiedId: string }).copiedId)).toBe(firstId)
  await expect(page.locator('.n-checkbox--checked')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '关闭', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  await expect(page.getByText('商品详情', { exact: true })).toBeVisible()
  await expect(page.getByText('白色', { exact: true }).first()).toBeVisible()
  await expect(page.locator('.app-dialog')).toHaveCSS('opacity', '1')
  await page.screenshot({ path: testInfo.outputPath('product-detail-1440.png'), fullPage: true, animations: 'disabled' })
  await page.getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.locator('.n-pagination-item--button').last().click()
  await expect.poll(() => listRequests.some((url) => url.searchParams.get('offset') === '20' && url.searchParams.get('includeTotal') === 'false')).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('product-library-1440.png'), fullPage: true })
  expect(errors).toEqual([])
})

test('900×560 保持底部分页可见，四套主题复用原 Token', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 900, height: 560 })
  await fixtures(page); await page.goto('/#/products')
  await expect(page.locator('.pagination-bar')).toContainText('共 60 条')
  const pager = await page.locator('.pagination-bar').boundingBox()
  expect(pager!.y + pager!.height).toBeLessThanOrEqual(560)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(900)
  for (const preset of ['graphite', 'forest', 'coral', 'midnight']) {
    await page.evaluate((preset) => localStorage.setItem('control-center.theme-mode', preset), preset)
    await page.reload(); await expect(page.locator('html')).toHaveAttribute('data-theme-preset', preset)
    await expect(page.locator('.pagination-bar')).toContainText('共 60 条')
    await page.screenshot({ path: testInfo.outputPath(`product-library-${preset}-900.png`), fullPage: true })
  }
})

test('分组新增和重命名使用真实交互，生产数据不参与测试', async ({ page }) => {
  await fixtures(page); await page.goto('/#/products')
  await page.getByRole('button', { name: '分组管理', exact: true }).click()
  await page.getByRole('textbox', { name: '分组名称', exact: true }).fill('测试分组')
  await page.getByRole('button', { name: '新增', exact: true }).click()
  await expect(page.getByText('分组已创建', { exact: true })).toBeVisible()
  const row = page.locator('tr').filter({ hasText: '测试分组' })
  await row.getByRole('button', { name: '重命名', exact: true }).click()
  await page.getByRole('textbox', { name: '分组名称', exact: true }).fill('更新分组')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('tr').filter({ hasText: '更新分组' })).toHaveCount(1)
})

test('慢速翻页与切换详情保持外框，旧数据加载时不可操作', async ({ page }) => {
  await fixtures(page)
  let releasePage!: () => void
  let releaseDetail!: () => void
  const pageGate = new Promise<void>((resolve) => { releasePage = resolve })
  const detailGate = new Promise<void>((resolve) => { releaseDetail = resolve })
  const secondId = String(BigInt(firstId) + 1n)
  await page.route('**/api/v1/products**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/v1/products' && url.searchParams.get('offset') === '20') await pageGate
    if (url.pathname === `/api/v1/products/${secondId}`) await detailGate
    await route.fallback()
  })
  await page.goto('/#/products')
  await expect(page.locator('.pagination-bar')).toContainText('共 60 条')
  const table = page.locator('.data-table .n-data-table')
  await expect(table).toBeVisible()
  await table.evaluate((el) => el.setAttribute('data-stability-check', 'table'))
  await page.locator('.n-pagination-item--button').last().click()
  await expect(page.locator('.data-table')).toHaveAttribute('inert', '')
  await expect(page.locator('[data-stability-check="table"]')).toBeVisible()
  await expect(page.locator('.pagination-bar')).toHaveAttribute('inert', '')
  releasePage()
  await expect(page.locator('.data-table')).not.toHaveAttribute('inert')
  await expect(page.locator('[data-stability-check="table"]')).toBeVisible()
  await page.locator('.n-pagination-item--button').first().click()
  await expect(page.getByText('ID：' + firstId)).toBeVisible()
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  await expect(page.getByText('商品 ID ' + firstId)).toBeVisible()
  const modal = page.locator('.app-dialog')
  await modal.evaluate((el) => el.setAttribute('data-stability-check', 'modal'))
  await expect(page.getByRole('button', { name: '下一件', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '下一件', exact: true }).click()
  await expect(page.locator('[data-stability-check="modal"]')).toBeVisible()
  await expect(page.locator('.product-preview__content')).toHaveAttribute('inert', '')
  releaseDetail()
  await expect(page.getByText('商品 ID ' + secondId)).toBeVisible()
  await expect(page.locator('[data-stability-check="modal"]')).toBeVisible()
  await expect(page.getByRole('button', { name: '上一件', exact: true })).toBeEnabled()
})

test('切换详情失败时保留弹窗并显示错误，不能操作旧商品', async ({ page }) => {
  await fixtures(page)
  const secondId = String(BigInt(firstId) + 1n)
  await page.route(`**/api/v1/products/${secondId}`, async (route) => {
    await route.fulfill({ status: 500, json: { message: '详情暂不可用' } })
  })
  await page.goto('/#/products')
  await expect(page.locator('.pagination-bar')).toContainText('共 60 条')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  await expect(page.getByText('商品 ID ' + firstId)).toBeVisible()
  const modal = page.locator('.app-dialog')
  await modal.evaluate((el) => el.setAttribute('data-stability-check', 'modal-error'))
  await page.getByRole('button', { name: '下一件', exact: true }).click()
  await expect(page.locator('[data-stability-check="modal-error"]')).toBeVisible()
  await expect(page.getByRole('dialog').getByRole('button', { name: '重新加载' })).toBeVisible()
  await expect(page.getByText('商品 ID ' + firstId)).toHaveCount(0)
})

test('40 张详情图片按需加载，失败可单图重试，右侧缩略图随滚动加载', async ({ page }) => {
  await fixtures(page)
  const requested: string[] = []
  let firstImageAttempts = 0
  await page.route('https://product-image.invalid/**', async (route) => {
    const name = new URL(route.request().url()).pathname
    requested.push(name)
    if (name === '/main-0.svg' && firstImageAttempts++ === 0) return route.abort('failed')
    return route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect width="160" height="160" fill="gray"/></svg>' })
  })
  await page.route(`**/api/v1/products/${firstId}`, async (route) => {
    const images = ([['main', 12], ['sku', 7], ['detail', 21]] as const).flatMap(([image_type, count]) =>
      Array.from({ length: count }, (_, sort_order) => ({ image_type, sort_order, rel_path: '', source_url: `https://product-image.invalid/${image_type}-${sort_order}.svg` })))
    const skus = Array.from({ length: 7 }, (_, sort_order) => ({ sku_id: `sku-${sort_order}`, sku_name: `测试SKU-${sort_order}`, current_price: '19.99', image_rel_path: '', sort_order }))
    return route.fulfill({ json: { product: product(firstId), skus, images } })
  })
  await page.goto('/#/products')
  await expect(page.locator('.pagination-bar')).toContainText('共 60 条')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  const gallery = page.locator('.product-preview__image-section')
  await expect(gallery.first().getByRole('button', { name: '重试', exact: true })).toBeVisible()
  await gallery.first().getByRole('button', { name: '重试', exact: true }).click()
  await expect.poll(() => firstImageAttempts).toBe(2)
  await expect(gallery.locator('img')).toHaveCount(40)
  expect(await gallery.locator('img').evaluateAll((imgs) => imgs.every((img) => img.getAttribute('loading') === 'lazy'))).toBe(true)
  await page.waitForTimeout(500)
  expect(requested.length).toBeLessThan(41)
  const sidebar = page.locator('.product-preview__navigator-list')
  await expect(sidebar.locator('.deferred-preview-thumbnail')).toHaveCount(20)
  await expect(sidebar.locator('.deferred-preview-thumbnail').first().locator('.product-image')).toHaveCount(1)
  await expect.poll(() => sidebar.locator('.deferred-preview-thumbnail .product-image').count()).toBeLessThan(20)
  const last = sidebar.locator('.deferred-preview-thumbnail').last()
  await last.scrollIntoViewIfNeeded()
  await expect(last.locator('.product-image')).toHaveCount(1)
  await gallery.nth(2).locator('img').last().scrollIntoViewIfNeeded()
  await expect.poll(() => requested.includes('/detail-20.svg')).toBe(true)
})
