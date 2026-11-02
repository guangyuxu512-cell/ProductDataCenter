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
    if (url.pathname === '/api/v1/products/group' && method === 'PATCH') {
      const body = route.request().postDataJSON()
      return route.fulfill({ json: { updated: body.productIds, missing: [] } })
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
  await expect(page.getByText('编辑商品', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '更多', exact: true }).click()
  await page.getByText('复制标题', { exact: true }).click()
  expect(await page.evaluate(() => (window as unknown as { copiedId: string }).copiedId)).toBe('厨房收纳盒 · 隔离测试商品')
  await page.getByRole('tab', { name: '规格与 SKU', exact: true }).click()
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

test('商品范围在左，四个页签读取当前商品并支持连续查看', async ({ page }) => {
  await fixtures(page)
  const writes: string[] = []
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/') && request.method() !== 'GET') writes.push(request.method())
  })
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  const navigator = dialog.locator('.product-preview__navigator')
  const content = dialog.locator('.product-preview__main')
  await expect(dialog.getByRole('textbox', { name: '商品标题' })).toHaveAttribute('readonly', '')
  await expect(dialog.getByRole('textbox', { name: '抖店类目' })).toBeDisabled()
  await expect(dialog.getByText('来源类目：家居/厨房/收纳')).toBeVisible()
  expect((await navigator.boundingBox())!.x).toBeLessThan((await content.boundingBox())!.x)
  for (const name of ['基本信息', '图文信息', '商品属性', '规格与 SKU']) {
    await expect(dialog.getByRole('tab', { name, exact: true })).toBeVisible()
  }
  await expect(dialog.getByRole('button', { name: '移动分组' })).toBeEnabled()
  await expect(dialog.getByRole('button', { name: '导出商品数据包' })).toBeEnabled()
  await dialog.getByRole('tab', { name: '图文信息', exact: true }).click()
  await expect(dialog.locator('.product-preview__image-section')).toHaveCount(3)
  await dialog.getByRole('tab', { name: '规格与 SKU', exact: true }).click()
  await expect(dialog.locator('.product-preview__sku')).toContainText('白色')
  const bodyMetrics = await dialog.locator('.product-preview__content').evaluate((node) => ({
    width: node.clientWidth, scrollWidth: node.scrollWidth,
  }))
  expect(bodyMetrics.scrollWidth).toBeLessThanOrEqual(bodyMetrics.width + 1)
  const actions = await dialog.getByRole('button', { name: '复制全部信息' }).boundingBox()
  const main = await content.boundingBox()
  expect(actions!.x + actions!.width).toBeLessThanOrEqual(main!.x + main!.width + 1)
  await dialog.getByRole('button', { name: '下一件', exact: true }).click()
  await expect(dialog.getByText('商品 ID ' + String(BigInt(firstId) + 1n))).toBeVisible()
  await expect(dialog.getByRole('tab', { name: '规格与 SKU' })).toHaveAttribute('aria-selected', 'true')
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  expect(writes).toEqual([])
})

test('按来源规格显示布局，不补造缺失 SKU 或错误关联图片', async ({ page }, testInfo) => {
  await fixtures(page)
  await page.route(`**/api/v1/products/${firstId}`, async (route) => {
    const skus = [
      { sku_id: 's1', sku_name: '颜色（2）：黑色 / 款式：长款', current_price: '19.99', image_rel_path: '', sort_order: 0 },
      { sku_id: 's2', sku_name: '颜色（2）：黑色 / 款式：短款', current_price: '20.99', image_rel_path: '', sort_order: 1 },
      { sku_id: 's3', sku_name: '颜色（2）：白色 / 款式：长款', current_price: '21.99', image_rel_path: '', sort_order: 2 },
    ]
    const images = [
      { image_type: 'main', sort_order: 0, rel_path: '', source_url: image },
      { image_type: 'sku', sort_order: 0, rel_path: '', source_url: image },
      { image_type: 'sku', sort_order: 1, rel_path: '', source_url: image },
    ]
    await route.fulfill({ json: { product: product(firstId), skus, images } })
  })
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await page.screenshot({ path: testInfo.outputPath('approved-layout-basic.png'), animations: 'disabled' })
  await dialog.getByRole('tab', { name: '图文信息' }).click()
  await expect(dialog.locator('.product-preview__image-section').nth(2).locator('img')).toHaveCount(2)
  await expect(dialog.getByRole('button', { name: '添加图片' }).first()).toBeDisabled()
  await page.screenshot({ path: testInfo.outputPath('approved-layout-images.png'), animations: 'disabled' })
  await dialog.getByRole('tab', { name: '规格与 SKU' }).click()
  await expect(dialog.getByText('销售规格', { exact: true })).toBeVisible()
  await expect(dialog.locator('.product-preview__axis')).toHaveCount(2)
  await expect(dialog.getByLabel('颜色规格值')).toHaveCount(2)
  await expect(dialog.getByLabel('款式规格值')).toHaveCount(2)
  await expect(dialog.locator('.n-data-table-tbody .n-data-table-tr')).toHaveCount(3)
  await expect(dialog.getByLabel('SKU 商家编码')).toHaveCount(3)
  await expect(dialog.getByLabel('SKU 商家编码').first()).toBeDisabled()
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  await page.screenshot({ path: testInfo.outputPath('approved-layout-sku.png'), animations: 'disabled' })
})

test('窄窗口内商品范围、四个页签和底部关闭按钮可用', async ({ page }) => {
  await fixtures(page)
  await page.setViewportSize({ width: 900, height: 560 })
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  for (const width of [900, 640]) {
    await page.setViewportSize({ width, height: 560 })
    await expect(dialog.getByRole('tab', { name: '图文信息' })).toBeVisible()
    await dialog.getByRole('tab', { name: '规格与 SKU' }).click()
    const close = await dialog.getByRole('button', { name: '关闭', exact: true }).boundingBox()
    expect(close!.y + close!.height).toBeLessThanOrEqual(560)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    const body = await dialog.locator('.product-preview__content').evaluate((node) => ({
      width: node.clientWidth, scrollWidth: node.scrollWidth,
    }))
    expect(body.scrollWidth).toBeLessThanOrEqual(body.width + 1)
  }
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
})

test('详情内移动分组沿用原有写接口', async ({ page }) => {
  await fixtures(page)
  let body: { productIds: string[]; groupId: string | null } | undefined
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === '/api/v1/products/group' && request.method() === 'PATCH') {
      body = request.postDataJSON()
    }
  })
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: '移动分组' }).click()
  const form = page.getByRole('dialog').last()
  await expect(form.getByText('目标分组')).toBeVisible()
  await form.getByRole('button', { name: '保存', exact: true }).click()
  await expect.poll(() => body).toEqual({ productIds: [firstId], groupId: null })
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

test('40 张详情图片按需加载，失败可单图重试，商品范围缩略图随滚动加载', async ({ page }) => {
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
  await page.getByRole('tab', { name: '图文信息', exact: true }).click()
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
  await gallery.nth(1).locator('img').last().scrollIntoViewIfNeeded()
  await expect.poll(() => requested.includes('/detail-20.svg')).toBe(true)
})

test('详情图片还在请求时有固定显示区域，滚动后可加载后续图片', async ({ page }) => {
  await fixtures(page)
  let releaseImages!: () => void
  const gate = new Promise<void>((resolve) => { releaseImages = resolve })
  const requested: string[] = []
  await page.route('https://slow-image.invalid/**', async (route) => {
    requested.push(new URL(route.request().url()).pathname)
    await gate
    await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="800"><rect width="800" height="800" fill="gray"/></svg>' })
  })
  await page.route(`**/api/v1/products/${firstId}`, async (route) => {
    const images = Array.from({ length: 20 }, (_, sort_order) => ({ image_type: 'main', sort_order, rel_path: '', source_url: `https://slow-image.invalid/main-${sort_order}.svg` }))
    await route.fulfill({ json: { product: product(firstId), skus: [], images } })
  })
  try {
    await page.goto('/#/products')
    await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
    await page.getByRole('tab', { name: '图文信息', exact: true }).click()
    const gallery = page.locator('.product-preview__image-section').first()
    const first = gallery.locator('img').first()
    await expect(first).toBeAttached()
    await expect.poll(() => requested.includes('/main-0.svg')).toBe(true)
    await expect.poll(async () => Math.round((await first.boundingBox())?.width ?? 0)).toBe(112)
    expect(Math.round((await first.boundingBox())?.height ?? 0)).toBe(112)
    expect(requested.length).toBeLessThan(20)
    releaseImages()
    await expect.poll(() => first.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(800)
    await gallery.locator('img').last().scrollIntoViewIfNeeded()
    await expect.poll(() => requested.includes('/main-19.svg')).toBe(true)
  } finally {
    releaseImages()
  }
})

test('抖音详情优先请求平台小图，失败回退原图，放大使用原图', async ({ page }) => {
  await fixtures(page)
  const requested: string[] = []
  const original = (index: number) => `https://p3-item.ecombdimg.com/img/ecom-shop-material/test-${index}~tplv-5mmsx3fupr-resize_q:1080:1080:q90.webp`
  await page.route('https://p3-item.ecombdimg.com/**', async (route) => {
    const url = route.request().url()
    requested.push(url)
    if (url.includes('test-1~') && url.includes('resize:384:0')) return route.abort('failed')
    await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="384" height="384"><rect width="384" height="384" fill="gray"/></svg>' })
  })
  await page.route(`**/api/v1/products/${firstId}`, async (route) => {
    const images = [0, 1].map((sort_order) => ({ image_type: 'main', sort_order, rel_path: '', source_url: original(sort_order) }))
    await route.fulfill({ json: { product: product(firstId), skus: [], images } })
  })
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  await page.getByRole('tab', { name: '图文信息', exact: true }).click()
  const images = page.locator('.product-preview__image-section').first().locator('img')
  await expect(images).toHaveCount(2)
  await expect.poll(() => requested.some((url) => url.includes('test-0~') && url.includes('resize:384:0'))).toBe(true)
  await expect.poll(() => requested.includes(original(1))).toBe(true)
  expect(await images.first().getAttribute('data-preview-src')).toBe(original(0))
  await images.first().click()
  await expect.poll(() => requested.includes(original(0))).toBe(true)
})

test('未显示的 SKU 明细不会提前请求原尺寸图片，滚动后仍能展示', async ({ page }) => {
  await fixtures(page)
  const requested: string[] = []
  const original = (type: string, index: number) => `https://p3-item.ecombdimg.com/img/ecom-shop-material/${type}-${index}~tplv-5mmsx3fupr-resize:1200:0.webp`
  await page.route('https://p3-item.ecombdimg.com/**', async (route) => {
    requested.push(route.request().url())
    await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="384" height="384"><rect width="384" height="384" fill="gray"/></svg>' })
  })
  await page.route(`**/api/v1/products/${firstId}`, async (route) => {
    const images = ([['main', 12], ['sku', 9], ['detail', 15]] as const).flatMap(([image_type, count]) =>
      Array.from({ length: count }, (_, sort_order) => ({ image_type, sort_order, rel_path: image_type === 'sku' ? `sku-${sort_order}.jpg` : '', source_url: original(image_type, sort_order) })))
    const skus = Array.from({ length: 9 }, (_, sort_order) => ({ sku_id: `sku-${sort_order}`, sku_name: `SKU ${sort_order}`, current_price: '19.99', image_rel_path: `sku-${sort_order}.jpg`, sort_order }))
    await route.fulfill({ json: { product: product(firstId), skus, images } })
  })
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  await page.getByRole('tab', { name: '图文信息', exact: true }).click()
  await expect(page.locator('.product-preview__image-section').first().locator('img').first()).toBeVisible()
  await expect.poll(() => requested.some((url) => url.includes('sku-0~') && url.includes('resize:384:0'))).toBe(true)
  expect(requested.filter((url) => url.includes('/sku-') && url.includes('resize:1200:0'))).toHaveLength(0)
  await page.getByRole('tab', { name: '规格与 SKU', exact: true }).click()
  const row = page.locator('.product-preview__sku').first()
  await row.scrollIntoViewIfNeeded()
  await expect.poll(() => requested.some((url) => url.includes('sku-0~') && url.includes('resize_q:144:144:q80'))).toBe(true)
  expect(requested.includes(original('sku', 0))).toBe(false)
  await expect(row.locator('img')).toBeVisible()
  await row.locator('img').click()
  await expect.poll(() => requested.includes(original('sku', 0))).toBe(true)
})

test('商品列表按可见区域加载小图，失败回退原图，原图失败可重试', async ({ page }) => {
  await fixtures(page)
  const requested: string[] = []
  let retryAllowed = false
  const original = (index: number) => `https://p3-item.ecombdimg.com/img/ecom-shop-material/list-${index}~tplv-5mmsx3fupr-resize_q:1080:1080:q90.webp`
  await page.route('https://p3-item.ecombdimg.com/**', async (route) => {
    const url = route.request().url()
    requested.push(url)
    if (url.includes('list-1~') && url.includes('resize_q:144:144:q80')) return route.abort('failed')
    if (url.includes('list-2~') && !retryAllowed) return route.abort('failed')
    await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144"><rect width="144" height="144" fill="gray"/></svg>' })
  })
  await page.route('**/api/v1/products**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname !== '/api/v1/products') return route.fallback()
    const items = Array.from({ length: 20 }, (_, i) => ({ ...product(String(BigInt(firstId) + BigInt(i))), main_image_url: original(i) }))
    return route.fulfill({ json: { items, total: 20, totalIncluded: true, limit: 20, offset: 0 } })
  })
  await page.goto('/#/products')
  const images = page.locator('.data-table .product-image img')
  await expect(page.locator('.data-table .product-image')).toHaveCount(20)
  await expect.poll(() => requested.some((url) => url.includes('list-0~') && url.includes('resize_q:144:144:q80'))).toBe(true)
  await expect.poll(() => requested.includes(original(1))).toBe(true)
  await expect(page.getByRole('button', { name: '重试商品图片' })).toBeVisible()
  expect(requested.some((url) => url.includes('list-19~'))).toBe(false)
  const nearNextRow = await images.evaluateAll((elements) => {
    const scrollArea = elements[0]?.closest('.n-scrollbar-container')
    if (!scrollArea) return null
    const bottom = scrollArea.getBoundingClientRect().bottom
    return elements.find((element) => {
      const top = element.getBoundingClientRect().top
      return top > bottom && top < bottom + 100
    })?.getAttribute('data-preview-src') ?? null
  })
  expect(nearNextRow).not.toBeNull()
  const nearThumbnail = nearNextRow!.replace('resize_q:1080:1080:q90', 'resize_q:144:144:q80')
  await expect.poll(() => requested.includes(nearThumbnail)).toBe(true)
  expect(await images.first().getAttribute('data-preview-src')).toBe(original(0))
  retryAllowed = true
  await page.getByRole('button', { name: '重试商品图片' }).click()
  await expect(page.getByRole('button', { name: '重试商品图片' })).toHaveCount(0)
  await expect.poll(() => requested.filter((url) => url.includes('list-2~') && url.includes('resize_q:144:144:q80')).length).toBe(2)
  await images.last().scrollIntoViewIfNeeded()
  await expect.poll(() => requested.some((url) => url.includes('list-19~') && url.includes('resize_q:144:144:q80'))).toBe(true)
  await images.first().scrollIntoViewIfNeeded()
  await images.first().click()
  await expect.poll(() => requested.includes(original(0))).toBe(true)
})

test('拼多多带参数的图片保留原地址，不尝试推测缩略图格式', async ({ page }) => {
  await fixtures(page)
  const original = 'https://img.pddpic.com/fixture/list.webp?signature=example'
  const requested: string[] = []
  await page.route('https://img.pddpic.com/**', async (route) => {
    requested.push(route.request().url())
    await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144"><rect width="144" height="144" fill="gray"/></svg>' })
  })
  await page.route('**/api/v1/products**', async (route) => {
    if (new URL(route.request().url()).pathname !== '/api/v1/products') return route.fallback()
    return route.fulfill({ json: { items: [{ ...product('pdd:3800000000000000001', 'pinduoduo'), main_image_url: original }], total: 1, totalIncluded: true, limit: 20, offset: 0 } })
  })
  await page.goto('/#/products')
  const image = page.locator('.data-table .product-image img')
  await expect.poll(() => requested.length).toBeGreaterThan(0)
  await expect(image).toHaveAttribute('data-preview-src', original)
  expect(requested.every((url) => url === original)).toBe(true)
})

test('拼多多无参数图片使用小图，失败回退原图，放大仍是原图', async ({ page }) => {
  await fixtures(page)
  const requested: string[] = []
  const original = (index: number) => `https://img.pddpic.com/mms-material-img/list-${index}.jpeg.a.jpeg`
  await page.route('https://img.pddpic.com/**', async (route) => {
    const url = route.request().url()
    requested.push(url)
    if (url.includes('list-1.') && url.includes('?imageView2')) return route.abort('failed')
    await route.fulfill({ status: 200, contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144"><rect width="144" height="144" fill="gray"/></svg>' })
  })
  await page.route('**/api/v1/products**', async (route) => {
    if (new URL(route.request().url()).pathname !== '/api/v1/products') return route.fallback()
    const items = [0, 1].map((i) => ({ ...product(`pdd:${3800000000000000001n + BigInt(i)}`, 'pinduoduo'), main_image_url: original(i) }))
    return route.fulfill({ json: { items, total: 2, totalIncluded: true, limit: 20, offset: 0 } })
  })
  await page.goto('/#/products')
  const images = page.locator('.data-table .product-image img')
  await expect.poll(() => requested.includes(original(0) + '?imageView2/2/w/144/q/80/format/webp')).toBe(true)
  await expect.poll(() => requested.includes(original(1))).toBe(true)
  await expect(images.first()).toHaveAttribute('data-preview-src', original(0))
  await images.first().click()
  await expect.poll(() => requested.includes(original(0))).toBe(true)
})

test('类目候选与属性只读查看，切换商品后不沿用上一件的结果', async ({ page }) => {
  await fixtures(page)
  const shop = '00000000-0000-4000-8000-000000000111'
  await page.route('**/api/v1/capabilities', (route) => route.fulfill({ json: {
    groupWrites: true, export: true, productEdit: false, importProducts: false, categoryLookup: true,
  } }))
  await page.route('**/api/v1/category-lookup/search', (route) => route.fulfill({ json: {
    shopId: shop, candidates: [{ id: '1000010075', name: '汤勺', path: '餐具 > 汤勺' }],
  } }))
  await page.route('**/api/v1/category-lookup/schema', (route) => route.fulfill({ json: {
    categoryId: '1000010075', attributes: [{ id: '12', label: '材质', required: true, options: [] }],
  } }))
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: '查找类目' }).click()
  await dialog.locator('[aria-label="抖店类目"]').click()
  await page.getByText('餐具 > 汤勺', { exact: true }).last().click()
  await expect(dialog.getByText('当前类目和属性仅供查看，尚未保存')).toBeVisible()
  await dialog.getByRole('tab', { name: '商品属性' }).click()
  await expect(dialog.getByText('材质', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  await dialog.getByRole('button', { name: '下一件' }).click()
  await expect(dialog.getByText('商品 ID ' + String(BigInt(firstId) + 1n))).toBeVisible()
  await expect(dialog.getByText('材质', { exact: true })).toHaveCount(0)
})

test('抖音原类目直接取属性，切换商品时不使用旧响应', async ({ page }) => {
  await fixtures(page)
  const secondId = String(BigInt(firstId) + 1n)
  const title = '完整商品标题'.repeat(30)
  const calls: Array<{ path: string; body: Record<string, string> }> = []
  let releaseFirst!: () => void
  const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve })
  await page.route('**/api/v1/capabilities', (route) => route.fulfill({ json: {
    groupWrites: true, export: true, productEdit: false, importProducts: false, categoryLookup: true,
  } }))
  await page.route('**/api/v1/products/*', (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!)
    return route.fulfill({ json: { product: { ...product(id), title },
      sourceCategoryId: id === firstId ? '1000010075' : '1000010078', skus: [], images: [] } })
  })
  await page.route('**/api/v1/category-lookup/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = route.request().postDataJSON() as Record<string, string>
    calls.push({ path, body })
    if (body.categoryId === '1000010075') await firstGate
    await route.fulfill({ json: { shopId: '00000000-0000-4000-8000-000000000111', categoryId: body.categoryId,
      attributes: [{ id: '12', label: body.categoryId === '1000010075' ? '材质' : '品牌', required: true, options: [] }] } })
  })
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  expect(calls).toHaveLength(0)
  await dialog.getByRole('tab', { name: '商品属性' }).click()
  await expect.poll(() => calls.length).toBe(1)
  await dialog.getByRole('button', { name: '下一件' }).click()
  await expect(dialog.getByText('商品 ID ' + secondId)).toBeVisible()
  await expect(dialog.getByText('品牌', { exact: true })).toBeVisible()
  releaseFirst()
  await expect(dialog.getByText('材质', { exact: true })).toHaveCount(0)
  expect(calls.map((item) => item.path)).toEqual([
    '/api/v1/category-lookup/schema/auto', '/api/v1/category-lookup/schema/auto',
  ])
  expect(calls.map((item) => item.body.categoryId)).toEqual(['1000010075', '1000010078'])
  expect(calls.every((item) => item.body.title === title)).toBe(true)
})

test('非抖音来源不会把原平台类目当作抖店类目', async ({ page }) => {
  await fixtures(page)
  const calls: string[] = []
  await page.route('**/api/v1/capabilities', (route) => route.fulfill({ json: {
    groupWrites: true, export: true, productEdit: false, importProducts: false, categoryLookup: true,
  } }))
  await page.route(`**/api/v1/products/${firstId}`, (route) => route.fulfill({ json: {
    product: product(firstId, 'pinduoduo'), sourceCategoryId: '999999', skus: [], images: [],
  } }))
  await page.route('**/api/v1/category-lookup/**', (route) => {
    calls.push(new URL(route.request().url()).pathname)
    return route.fulfill({ status: 500 })
  })
  await page.goto('/#/products')
  await page.getByRole('button', { name: '查看商品', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('平台推荐类目尚未接通，可手动查找类目')).toBeVisible()
  await dialog.getByRole('tab', { name: '商品属性' }).click()
  await expect(dialog.getByText('请先查找并选择抖店类目')).toBeVisible()
  expect(calls).toEqual([])
})
