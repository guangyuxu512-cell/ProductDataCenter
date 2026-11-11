import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const manager = 'synthetic-manager-credential'
const oneTime = 'synthetic-one-time-token'
const groupA = '482f31fa-bb52-495e-b479-05eb10ebe532'
const groupB = 'd25215ae-0271-4d07-963a-8c8647d60471'
const ids = ['product.read', 'product.update', 'product.delete', 'group.read', 'precheck.read',
  'image.upload', 'token.read', 'token.create', 'token.update', 'token.revoke']

type TokenRecord = {
  id: string; name: string; permissions: string[]; groupIds: string[] | null
  expiresAt: number | null; revokedAt: number | null; createdAt: number; updatedAt: number; parentId: null
}

async function fixtures(page: Page, options: { restricted?: boolean; injectedName?: boolean; revokedHistory?: boolean; holdRefresh?: boolean } = {}) {
  const tokenDir = resolve(process.cwd(), '..', 'token-manager')
  await page.route('**/token-manager/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const file = path.endsWith('/') ? 'index.html' : path.split('/').pop()!
    if (!['index.html', 'style.css', 'app.js'].includes(file)) return route.fulfill({ status: 404 })
    const body = await readFile(resolve(tokenDir, file))
    const type = file.endsWith('.html') ? 'text/html' : file.endsWith('.css') ? 'text/css' : 'application/javascript'
    return route.fulfill({ body, contentType: type })
  })
  const now = Math.floor(Date.now() / 1000)
  let records: TokenRecord[] = options.injectedName ? [{
    id: '11111111111111111111111111111111', name: '<img src=x onerror=alert(1)>', permissions: ['product.read'],
    groupIds: null, expiresAt: null, revokedAt: null, createdAt: now, updatedAt: now, parentId: null,
  }] : []
  if (options.revokedHistory) {
    records = [
      { id: '11111111111111111111111111111111', name: '已撤销旧凭据', permissions: ['product.read'],
        groupIds: null, expiresAt: null, revokedAt: now, createdAt: now, updatedAt: now, parentId: null },
      { id: '22222222222222222222222222222222', name: '有效凭据', permissions: ['product.read'],
        groupIds: null, expiresAt: null, revokedAt: null, createdAt: now, updatedAt: now, parentId: null },
      { id: '33333333333333333333333333333333', name: '过期凭据', permissions: ['product.read'],
        groupIds: null, expiresAt: now - 60, revokedAt: null, createdAt: now, updatedAt: now, parentId: null },
    ]
  }
  const calls: { method: string; path: string; body: Record<string, unknown> | null }[] = []
  let listReads = 0
  let announceStale = () => {}
  let releaseStale = () => {}
  const staleStarted = new Promise<void>((resolve) => { announceStale = resolve })
  const staleReleased = new Promise<void>((resolve) => { releaseStale = resolve })
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname
    if (req.headers().authorization !== `Bearer ${manager}`) return route.fulfill({ status: 401, json: { detail: '访问未授权' } })
    const body = req.postData() ? req.postDataJSON() as Record<string, unknown> : null
    calls.push({ method: req.method(), path, body })
    if (path === '/api/v1/tokens/permissions') return route.fulfill({ json: {
      items: ids.map((id) => ({ id, description: id, canGrant: !options.restricted || !['product.delete', 'token.update', 'token.revoke'].includes(id) })),
      groupIds: options.restricted ? [groupA] : null, expiresAt: options.restricted ? now + 86400 : null,
    } })
    if (path === '/api/v1/product-groups') return route.fulfill({ json: { groups: [
      { groupId: groupA, name: '第一分组', productCount: 2 },
      ...(options.restricted ? [] : [{ groupId: groupB, name: '第二分组', productCount: 3 }]),
    ] } })
    if (path === '/api/v1/tokens' && req.method() === 'GET') {
      listReads++
      if (options.holdRefresh && listReads === 2) {
        const oldRecords = records.map((record) => ({ ...record }))
        announceStale()
        await staleReleased
        return route.fulfill({ json: { items: oldRecords }, headers: { 'x-stale-fixture': '1' } })
      }
      return route.fulfill({ json: { items: records } })
    }
    if (path === '/api/v1/tokens' && req.method() === 'POST') {
      const record = { id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', name: String(body!.name),
        permissions: body!.permissions as string[], groupIds: body!.groupIds as string[] | null,
        expiresAt: body!.expiresAt as number | null, revokedAt: null, createdAt: now, updatedAt: now, parentId: null }
      records = [record, ...records]
      return route.fulfill({ status: 201, json: { record, token: oneTime } })
    }
    if (path.startsWith('/api/v1/tokens/') && req.method() === 'PATCH') {
      records = records.map((record) => path.endsWith(record.id) ? { ...record, ...body } as TokenRecord : record)
      return route.fulfill({ json: { record: records[0] } })
    }
    if (path.startsWith('/api/v1/tokens/') && req.method() === 'DELETE') {
      records = records.map((record) => path.endsWith(record.id) ? { ...record, revokedAt: now } : record)
      return route.fulfill({ status: 204, body: '' })
    }
    return route.fulfill({ status: 404 })
  })
  return { calls, staleStarted, releaseStale }
}

async function login(page: Page) {
  await page.goto('/token-manager/')
  await page.getByLabel('管理 Token', { exact: true }).fill(manager)
  await page.getByRole('button', { name: '进入管理' }).click()
  await expect(page.getByRole('heading', { name: 'AI Token 管理' })).toBeVisible()
}

test('独立页面创建、修改、撤销，并且只显示一次凭据', async ({ page }) => {
  const { calls } = await fixtures(page)
  await login(page)
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
  expect(page.url()).not.toContain(manager)
  await page.getByRole('button', { name: '创建 Token', exact: false }).click()
  const dialog = page.getByRole('dialog', { name: '创建 Token' })
  await dialog.getByLabel('名称', { exact: true }).fill('Muse')
  await dialog.getByRole('button', { name: '只读' }).click()
  await dialog.getByLabel('指定分组').check()
  await dialog.getByLabel('第一分组').check()
  await dialog.getByRole('button', { name: '创建并显示 Token' }).click()
  await expect(page.getByRole('dialog', { name: 'Token 已创建' })).toBeVisible()
  await expect(page.getByLabel('新 Token')).toHaveValue(oneTime)
  const create = calls.find((call) => call.method === 'POST' && call.path === '/api/v1/tokens')!
  expect(create.body?.groupIds).toEqual([groupA])
  expect(create.body?.permissions).toContain('product.read')
  expect(create.body?.permissions).not.toContain('product.delete')
  await page.getByRole('button', { name: '已保存，关闭' }).click()
  await expect(page.locator('#new-secret')).toHaveValue('')
  const card = page.locator('.token-card').filter({ hasText: 'Muse' })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: '修改权限' }).click()
  const edit = page.getByRole('dialog', { name: '修改 Token' })
  await edit.getByRole('checkbox', { name: /编辑商品/ }).check()
  await edit.getByRole('button', { name: '保存修改' }).click()
  const update = calls.find((call) => call.method === 'PATCH')!
  expect(update.body?.permissions).toContain('product.update')
  expect(update.body).not.toHaveProperty('expiresAt')
  page.once('dialog', (prompt) => prompt.accept())
  await card.getByRole('button', { name: '撤销' }).click()
  await expect(card).toHaveCount(0)
  await expect(page.locator('#list-caption')).toContainText('共 0 个')
  expect(calls.some((call) => call.method === 'DELETE')).toBe(true)
  await page.getByRole('button', { name: '刷新' }).click()
  await expect(card).toHaveCount(0)
  await page.getByRole('button', { name: '退出' }).click()
  await expect(page.getByRole('heading', { name: '管理员登录' })).toBeVisible()
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
})

test('历史中已撤销的凭据不显示，过期但未撤销的凭据仍可管理', async ({ page }) => {
  await fixtures(page, { revokedHistory: true })
  await login(page)
  await expect(page.getByText('已撤销旧凭据')).toHaveCount(0)
  await expect(page.getByText('有效凭据')).toBeVisible()
  await expect(page.getByText('过期凭据')).toBeVisible()
  await expect(page.locator('#list-caption')).toContainText('共 2 个')
  await page.getByRole('button', { name: '刷新' }).click()
  await expect(page.getByText('已撤销旧凭据')).toHaveCount(0)
})

test('较早发出的刷新结果不能让刚撤销的凭据重新出现', async ({ page }) => {
  const { staleStarted, releaseStale } = await fixtures(page, { revokedHistory: true, holdRefresh: true })
  await login(page)
  const card = page.locator('.token-card').filter({ hasText: '有效凭据' })
  await page.getByRole('button', { name: '刷新' }).click()
  await staleStarted
  page.once('dialog', (prompt) => prompt.accept())
  await card.getByRole('button', { name: '撤销' }).click()
  await expect(card).toHaveCount(0)
  const oldResponse = page.waitForResponse((response) => response.headers()['x-stale-fixture'] === '1')
  releaseStale()
  await oldResponse
  await expect(card).toHaveCount(0)
  await expect(page.locator('#list-caption')).toContainText('共 1 个')
})

test('手机界面保留受限发放范围，并安全显示商品名称', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await fixtures(page, { restricted: true, injectedName: true })
  await login(page)
  await expect(page.getByText('<img src=x onerror=alert(1)>')).toBeVisible()
  await expect(page.locator('.token-card img')).toHaveCount(0)
  await page.getByRole('button', { name: '创建 Token', exact: false }).click()
  const dialog = page.getByRole('dialog', { name: '创建 Token' })
  await expect(dialog.getByLabel('全部分组')).toBeDisabled()
  await expect(dialog.getByLabel('指定分组')).toBeChecked()
  await expect(dialog.getByLabel('第一分组')).toBeVisible()
  await expect(dialog.getByRole('checkbox', { name: /删除商品/ })).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
