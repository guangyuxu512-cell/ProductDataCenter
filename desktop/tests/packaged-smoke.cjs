// CI only: a disposable local fixture verifies packaged authentication and isolation.
const http = require('node:http')
const { spawn } = require('node:child_process')
const { once } = require('node:events')
const { mkdtemp, readFile, writeFile } = require('node:fs/promises')
const { tmpdir } = require('node:os')
const path = require('node:path')

async function main() {
  const root = await mkdtemp(path.join(tmpdir(), 'pdc-desktop-smoke-'))
  const source = path.join(root, 'fixture-login.txt')
  await writeFile(source, 'username: test-user\npassword: test-password\n')
  let resolveReady
  const nextReady = () => new Promise((resolve) => { resolveReady = resolve })
  let ready = nextReady()
  const expected = 'Basic ' + Buffer.from('test-user:test-password').toString('base64')
  const server = http.createServer((request, response) => {
    if (request.headers.authorization !== expected) {
      response.writeHead(401, { 'www-authenticate': 'Basic realm="Fixture"' }).end()
      return
    }
    if (request.url.startsWith('/desktop-ready')) {
      const url = new URL(request.url, 'http://127.0.0.1')
      if (!request.headers['user-agent']?.includes('Electron/') || url.searchParams.get('node') !== 'undefined') {
        response.writeHead(400).end()
        return
      }
      response.writeHead(204).end()
      resolveReady()
      return
    }
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    response.end('<!doctype html><title>商品云库隔离测试</title><script>fetch("/desktop-ready?node=" + typeof window.require)</script>')
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const exe = path.resolve('release/win-unpacked/ProductWorkbench.exe')
  const env = { ...process.env, PRODUCT_WORKBENCH_URL: 'http://127.0.0.1:' + server.address().port + '/',
    PRODUCT_WORKBENCH_SMOKE_TEST: '1', PRODUCT_WORKBENCH_SMOKE_DATA_DIR: path.join(root, 'profile') }
  let child, promptChild
  try {
    const importer = spawn(exe, ['--import-login-file', source], { env, windowsHide: true, stdio: 'ignore' })
    const [code] = await Promise.race([once(importer, 'exit'), new Promise((_, reject) => setTimeout(() => reject(new Error('凭据迁移超时')), 30000))])
    if (code !== 0) throw new Error('凭据迁移失败: ' + code)
    const encrypted = await readFile(path.join(root, 'profile', 'secure', 'web-login.encrypted'))
    if (encrypted.includes(Buffer.from('test-password'))) throw new Error('凭据未加密')
    child = spawn(exe, [], { env, windowsHide: true, stdio: 'ignore' })
    const exit = once(child, 'exit').then(([value]) => { throw new Error('桌面程序提前退出: ' + value) })
    await Promise.race([ready, exit, new Promise((_, reject) => setTimeout(() => reject(new Error('桌面程序加载超时')), 30000))])
    console.log('PASS: packaged Electron encrypted credentials and loaded the authenticated fixture with Node disabled')
    ready = nextReady()
    const promptEnv = { ...env, PRODUCT_WORKBENCH_SMOKE_DATA_DIR: path.join(root, 'prompt-profile') }
    promptChild = spawn(require('electron'), [path.resolve('tests/prompt-driver.cjs')], { env: promptEnv, windowsHide: true, stdio: 'ignore' })
    const promptExit = once(promptChild, 'exit').then(([value]) => { throw new Error('首次登录测试提前退出: ' + value) })
    await Promise.race([ready, promptExit, new Promise((_, reject) => setTimeout(() => reject(new Error('首次登录测试超时')), 30000))])
    const prompted = await readFile(path.join(root, 'prompt-profile', 'secure', 'web-login.encrypted'))
    if (prompted.includes(Buffer.from('test-password'))) throw new Error('首次登录凭据未加密')
    console.log('PASS: first-login prompt saved an encrypted credential and connected')
  } finally {
    if (child?.pid) spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore', windowsHide: true })
    if (promptChild?.pid) spawn('taskkill', ['/pid', String(promptChild.pid), '/t', '/f'], { stdio: 'ignore', windowsHide: true })
    server.close()
  }
}
main().catch((error) => { console.error(error.message); process.exitCode = 1 })
