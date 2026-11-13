// Test-only Electron entry point: exercise the local prompt using synthetic credentials.
const { app } = require('electron')
app.on('browser-window-created', (_event, window) => {
  window.webContents.on('did-finish-load', () => {
    if (window.getTitle() !== '商品云库登录') return
    void window.webContents.executeJavaScript(
      "document.getElementById('username').value='test-user';" +
      "document.getElementById('password').value='test-password';" +
      "document.getElementById('login-form').requestSubmit()",
    ).catch(() => app.exit(1))
  })
})
require('../dist/main.js')
