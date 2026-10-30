// CI only: a disposable HTTP fixture verifies the packaged Electron process.
const http = require('node:http')
const { spawn } = require('node:child_process')
const { once } = require('node:events')
const path = require('node:path')

async function main() {
  let resolveReady
  const ready = new Promise((resolve) => { resolveReady = resolve })
  const server = http.createServer((request, response) => {
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
  const child = spawn(exe, [], {
    env: { ...process.env, PRODUCT_WORKBENCH_URL: `http://127.0.0.1:${server.address().port}/` },
    stdio: 'ignore',
  })
  const exit = once(child, 'exit').then(([code]) => { throw new Error(`桌面程序提前退出: ${code}`) })
  try {
    await Promise.race([ready, exit, new Promise((_, reject) => setTimeout(() => reject(new Error('桌面程序加载超时')), 30000))])
    console.log('PASS: packaged Electron loaded the local fixture with Node disabled')
  } finally {
    if (child.pid) spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore' })
    server.close()
  }
}
main().catch((error) => { console.error(error.message); process.exitCode = 1 })
