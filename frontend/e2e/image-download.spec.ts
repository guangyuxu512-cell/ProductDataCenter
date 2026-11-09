import { readFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { expect, test, type Page } from '@playwright/test'

const ids = ['3760269504500859111', '3760269504500859112']
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/CZYAAAAASUVORK5CYII=', 'base64')
const images = {
  main: 'https://source.example.test/main.png',
  detail: 'https://source.example.test/detail.png',
  sku: 'https://owned.example.test/rpa/v1/product-images/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png',
}
const bytes = (kind: keyof typeof images) => Buffer.concat([png, Buffer.from(kind)])
const archive = Buffer.from('UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==', 'base64')
const product = (id: string, mainImage = images.main) => ({
  product_id: id, source_product_id: id, source_platform: 'douyin', group_id: null, group_name: null,
  title: '隔离测试商品', title_status: '', shop_name: '测试店铺', category_level_4: '', category_path: '',
  current_price_min: '19.99', current_price_max: '19.99', sku_count: 1, main_image_count: 1,
  detail_image_count: 1, sku_image_count: 1, main_image_url: mainImage,
  captured_at: '2026-10-26T00:18:34Z', updated_at: null, asset_rel_path: '', workbook_rel_path: '', raw_rel_path: '',
})

async function fixtures(page: Page, mainImage = images.main) {
  await page.route('https://*.example.test/**', (route) => {
    const kind = (Object.entries(images).find(([, url]) => url === route.request().url())?.[0] ?? 'main') as keyof typeof images
    return route.fulfill({ status: 200, contentType: 'image/png', body: bytes(kind),
      headers: { 'Access-Control-Allow-Origin': '*' } })
  })
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/v1/capabilities') return route.fulfill({ json: { groupWrites: true, export: true, productEdit: true, categoryLookup: false } })
    if (url.pathname === '/api/v1/product-groups') return route.fulfill({ json: { groups: [] } })
    if (url.pathname === '/api/v1/products') return route.fulfill({ json: {
      items: ids.map((id) => product(id, mainImage)), total: ids.length, totalIncluded: true, limit: 20, offset: 0,
    } })
    if (url.pathname === '/api/v1/products/export-uu') return route.fulfill({ status: 200,
      contentType: 'application/zip', body: archive, headers: { 'Content-Disposition': 'attachment; filename="test.zip"', 'X-Export-Count': '2' } })
    if (url.pathname.endsWith('/edit')) return route.fulfill({ json: {
      version: 'a'.repeat(64), specImageGroup: '颜色', specImages: [{ id: '11', name: '白色', url: images.sku }],
      specGroups: [{ index: 0, name: '颜色', movable: false, values: [{ id: '11', name: '白色', url: images.sku }] }],
      skus: [{ skuId: 'sku-1', specIds: ['11'], price: '19.99', stock: 9, enabled: true, merchantCode: '' }],
    } })
    if (url.pathname.startsWith('/api/v1/products/')) return route.fulfill({ json: {
      product: product(ids[0], mainImage), sourceCategoryId: null, sourceAttributes: [],
      skus: [{ sku_id: 'sku-1', sku_name: '颜色: 白色', current_price: '19.99', image_rel_path: '', sort_order: 0 }],
      images: Object.entries(images).map(([image_type, source_url]) => ({ image_type, source_url, sort_order: 0, rel_path: '' })),
    } })
    return route.fulfill({ status: 404, json: { message: 'fixture endpoint not defined' } })
  })
}

async function expectDownload(page: Page, kind: keyof typeof images) {
  const [download] = await Promise.all([
    page.waitForEvent('download'), page.getByRole('button', { name: '下载图片' }).click(),
  ])
  expect(download.suggestedFilename()).toMatch(/\.png$/)
  expect(await readFile((await download.path())!)).toEqual(bytes(kind))
  await page.keyboard.press('Escape')
  await expect(page.locator('.n-image-preview-container')).not.toBeVisible()
}

test('列表、主图、详情图、SKU 和规格图均下载当前原图并保留草稿', async ({ page }) => {
  await fixtures(page)
  await page.goto('/#/products')
  await page.locator('.n-data-table-tbody tr').first().locator('.product-image img').click()
  await expectDownload(page, 'main')
  await expect(page).toHaveURL(/#\/products/)
  await page.getByRole('button', { name: '编辑', exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  const title = dialog.getByRole('textbox', { name: '商品标题' })
  await expect(title).toBeEditable()
  await title.fill('未保存的标题')
  await dialog.getByRole('tab', { name: '图文信息' }).click()
  for (const [index, kind] of (['main', 'detail', 'sku'] as const).entries()) {
    await dialog.locator('.product-preview__image-section').nth(index).locator('img').first().click()
    await expectDownload(page, kind)
    await expect(dialog).toBeVisible()
  }
  await dialog.getByRole('tab', { name: '规格与 SKU' }).click()
  await dialog.getByRole('img', { name: '白色规格图片' }).click()
  await expectDownload(page, 'sku')
  await dialog.getByRole('tab', { name: '基本信息' }).click()
  await expect(title).toHaveValue('未保存的标题')
})

test('来源不允许跨域下载时显示失败，预览与商品页面保留', async ({ page }) => {
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'image/png' })
    response.end(png)
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  try {
    const address = server.address()
    if (!address || typeof address === 'string') throw new Error('image server unavailable')
    await fixtures(page, `http://127.0.0.1:${address.port}/blocked.png`)
    await page.goto('/#/products')
    await page.locator('.n-data-table-tbody tr').first().locator('.product-image img').click()
    await page.getByRole('button', { name: '下载图片' }).click()
    await expect(page.getByText('图片下载失败，请检查图片地址或来源访问限制')).toBeVisible()
    await expect(page.locator('.n-image-preview-container')).toBeVisible()
    await expect(page).toHaveURL(/#\/products/)
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()))
  }
})

test('列表单件与批量商品数据包均触发文件下载', async ({ page }) => {
  await fixtures(page)
  await page.goto('/#/products')
  const [single] = await Promise.all([
    page.waitForEvent('download'), page.getByRole('button', { name: '导出', exact: true }).first().click(),
  ])
  expect(single.suggestedFilename()).toBe('test.zip')
  expect(await readFile((await single.path())!)).toEqual(archive)
  for (const id of ids) await page.locator('.n-data-table-tbody tr').filter({ hasText: id }).locator('.n-checkbox').click()
  const [batch] = await Promise.all([
    page.waitForEvent('download'), page.getByRole('button', { name: '批量导出', exact: true }).click(),
  ])
  expect(batch.suggestedFilename()).toBe('test.zip')
  expect(await readFile((await batch.path())!)).toEqual(archive)
})
