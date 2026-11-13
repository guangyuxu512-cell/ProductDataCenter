import { app, BrowserWindow, dialog, ipcMain, nativeTheme, safeStorage } from 'electron'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { BasicCredentialStore, isExpectedChallenge, parseLegacyLogin, validateCredentials, verifyCredentials, type BasicCredentials } from './credentials'
import { defaultProductUrl, isTrustedNavigation, resolveProductUrl } from './runtime'

let window: BrowserWindow | null = null
let promptWindow: BrowserWindow | null = null
let pendingAuth: Promise<BasicCredentials | null> | null = null
let attemptedStored = false
const productUrl = resolveProductUrl(process.env.PRODUCT_WORKBENCH_URL)
const hiddenSmokeTest = process.env.PRODUCT_WORKBENCH_SMOKE_TEST === '1'
const localSmokeOrigin = hiddenSmokeTest && productUrl.protocol === 'http:' && productUrl.hostname === '127.0.0.1'

app.setName('商品云库')
app.setPath('userData', join(app.getPath('appData'), '商品云库'))
if (localSmokeOrigin && process.env.PRODUCT_WORKBENCH_SMOKE_DATA_DIR) app.setPath('userData', process.env.PRODUCT_WORKBENCH_SMOKE_DATA_DIR)
app.enableSandbox()
if (process.platform === 'win32') app.setAppUserModelId('com.siyu.productworkbench')

function credentialStore(): BasicCredentialStore {
  return new BasicCredentialStore(join(app.getPath('userData'), 'secure', 'web-login.encrypted'), safeStorage)
}

async function importExistingLogin(source: string): Promise<void> {
  // The one-time migration must never send an existing credential to an overridden destination.
  if (productUrl.origin !== new URL(defaultProductUrl).origin && !localSmokeOrigin) throw new Error('目标地址不匹配')
  const credentials = parseLegacyLogin(await readFile(source, { encoding: 'utf8', signal: AbortSignal.timeout(8000) }))
  if (!await verifyCredentials(productUrl.origin, credentials)) throw new Error('登录验证失败')
  await credentialStore().save(productUrl.origin, credentials)
}

function promptForCredentials(): Promise<BasicCredentials | null> {
  return new Promise((resolve) => {
    const prompt = new BrowserWindow({
      title: '商品云库登录', width: 440, height: 300, resizable: false, autoHideMenuBar: true, show: false,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true,
        preload: join(__dirname, 'login-preload.js') },
    })
    promptWindow = prompt
    prompt.removeMenu()
    const target = pathToFileURL(join(__dirname, '..', 'login.html')).href
    prompt.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    prompt.webContents.on('will-navigate', (event, url) => { if (url !== target) event.preventDefault() })
    let finished = false, verifying = false
    function finish(value: BasicCredentials | null) {
      if (finished) return
      finished = true
      ipcMain.removeListener('workbench-auth-submit', submit)
      ipcMain.removeListener('workbench-auth-cancel', cancel)
      if (promptWindow === prompt) promptWindow = null
      if (!prompt.isDestroyed()) prompt.close()
      resolve(value)
    }
    async function submit(event: Electron.IpcMainEvent, username: unknown, password: unknown) {
      if (event.sender !== prompt.webContents || verifying) return
      verifying = true
      try {
        const credentials = validateCredentials({ username, password })
        if (!await verifyCredentials(productUrl.origin, credentials)) throw new Error('登录失败，请检查账号密码或网络')
        await credentialStore().save(productUrl.origin, credentials)
        finish(credentials)
      } catch {
        if (!prompt.isDestroyed()) prompt.webContents.send('workbench-auth-error', '登录失败，请检查账号密码和网络后重试')
      } finally { verifying = false }
    }
    function cancel(event: Electron.IpcMainEvent) { if (event.sender === prompt.webContents) finish(null) }
    ipcMain.on('workbench-auth-submit', submit)
    ipcMain.on('workbench-auth-cancel', cancel)
    prompt.once('closed', () => finish(null))
    prompt.once('ready-to-show', () => { if (!hiddenSmokeTest) prompt.show() })
    void prompt.loadURL(target).catch(() => finish(null))
  })
}

function getCredentials(firstAttempt: boolean): Promise<BasicCredentials | null> {
  if (!pendingAuth) {
    pendingAuth = (async () => {
      if (firstAttempt && !attemptedStored) {
        attemptedStored = true
        try {
          const stored = await credentialStore().load(productUrl.origin)
          if (stored) return stored
        } catch { /* An unavailable local credential can be replaced through the login dialog. */ }
      }
      return promptForCredentials()
    })().finally(() => { pendingAuth = null })
  }
  return pendingAuth
}

app.on('login', (event, contents, details, info, callback) => {
  if (!window || contents !== window.webContents || !isExpectedChallenge(details.url, info, productUrl.origin)) return
  event.preventDefault()
  void getCredentials(details.firstAuthAttempt).then((credentials) => {
    if (credentials) callback(credentials.username, credentials.password)
    else callback()
  }).catch(() => callback())
})

function focusWindow(): void {
  const target = promptWindow || window
  if (!target || target.isDestroyed()) return
  if (target.isMinimized()) target.restore()
  if (!target.isVisible()) target.show()
  target.focus()
}

function openWindow(): BrowserWindow {
  const mainWindow = new BrowserWindow({
    title: '商品云库', width: 1280, height: 800, minWidth: 960, minHeight: 640, autoHideMenuBar: true, show: false,
    ...(process.platform === 'win32' ? {
      titleBarStyle: 'hidden' as const, hasShadow: false,
      titleBarOverlay: { color: '#00000000', symbolColor: nativeTheme.shouldUseDarkColors ? '#e4e7eb' : '#222a34', height: 54 },
    } : {}),
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true,
      allowRunningInsecureContent: false, devTools: !app.isPackaged, navigateOnDragDrop: false, webviewTag: false },
  })
  mainWindow.removeMenu()
  mainWindow.once('ready-to-show', () => { if (!hiddenSmokeTest) mainWindow.show() })
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => { if (!isTrustedNavigation(url, productUrl.origin)) event.preventDefault() })
  mainWindow.webContents.on('will-redirect', (event, url) => { if (!isTrustedNavigation(url, productUrl.origin)) event.preventDefault() })
  mainWindow.webContents.session.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(contents === mainWindow.webContents && permission === 'clipboard-sanitized-write' &&
      isTrustedNavigation(details.requestingUrl, productUrl.origin))
  })
  mainWindow.on('closed', () => { if (window === mainWindow) window = null })

  async function load(): Promise<void> {
    try { await mainWindow.loadURL(new URL('#/products', productUrl).href) }
    catch {
      if (mainWindow.isDestroyed()) return
      if (hiddenSmokeTest) { app.exit(1); return }
      mainWindow.show()
      const result = await dialog.showMessageBox(mainWindow, {
        type: 'error', title: '商品云库', message: '无法连接商品云库，请检查服务器和网络。',
        buttons: ['重试', '退出'], defaultId: 0, cancelId: 1,
      })
      if (result.response === 0 && !mainWindow.isDestroyed()) await load()
      else if (!mainWindow.isDestroyed()) mainWindow.close()
    }
  }
  void load()
  return mainWindow
}

const importIndex = process.argv.indexOf('--import-login-file')
if (importIndex !== -1) {
  void app.whenReady().then(async () => {
    try { await importExistingLogin(process.argv[importIndex + 1]); app.exit(0) }
    catch { app.exit(1) }
  })
} else if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', focusWindow)
  void app.whenReady().then(() => {
    window = openWindow()
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) window = openWindow()
      else focusWindow()
    })
  })
  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
}
