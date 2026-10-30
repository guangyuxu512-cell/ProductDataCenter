import { app, BrowserWindow, dialog, nativeTheme } from 'electron'
import { isTrustedNavigation, resolveProductUrl } from './runtime'

let window: BrowserWindow | null = null
const productUrl = resolveProductUrl(process.env.PRODUCT_WORKBENCH_URL)

app.setName('商品云库')
app.enableSandbox()
if (process.platform === 'win32') app.setAppUserModelId('com.siyu.productworkbench')

function focusWindow(): void {
  if (!window || window.isDestroyed()) return
  if (window.isMinimized()) window.restore()
  if (!window.isVisible()) window.show()
  window.focus()
}

function openWindow(): BrowserWindow {
  const mainWindow = new BrowserWindow({
    title: '商品云库',
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    autoHideMenuBar: true,
    show: false,
    ...(process.platform === 'win32' ? {
      titleBarStyle: 'hidden' as const,
      hasShadow: false,
      titleBarOverlay: {
        color: '#00000000',
        symbolColor: nativeTheme.shouldUseDarkColors ? '#e4e7eb' : '#222a34',
        height: 54,
      },
    } : {}),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      devTools: !app.isPackaged,
      navigateOnDragDrop: false,
      webviewTag: false,
    },
  })
  mainWindow.removeMenu()
  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isTrustedNavigation(url, productUrl.origin)) event.preventDefault()
  })
  mainWindow.webContents.on('will-redirect', (event, url) => {
    if (!isTrustedNavigation(url, productUrl.origin)) event.preventDefault()
  })
  mainWindow.webContents.session.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(contents === mainWindow.webContents && permission === 'clipboard-sanitized-write' &&
      isTrustedNavigation(details.requestingUrl, productUrl.origin))
  })
  mainWindow.on('closed', () => { if (window === mainWindow) window = null })

  async function load(): Promise<void> {
    try {
      await mainWindow.loadURL(new URL('#/products', productUrl).href)
    } catch {
      if (mainWindow.isDestroyed()) return
      mainWindow.show()
      const result = await dialog.showMessageBox(mainWindow, {
        type: 'error', title: '商品云库', message: '无法连接商品云库，请检查 NAS 和网络。',
        buttons: ['重试', '退出'], defaultId: 0, cancelId: 1,
      })
      if (result.response === 0 && !mainWindow.isDestroyed()) await load()
      else if (!mainWindow.isDestroyed()) mainWindow.close()
    }
  }
  void load()
  return mainWindow
}

if (!app.requestSingleInstanceLock()) {
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
