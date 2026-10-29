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
