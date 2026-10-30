const { execFileSync } = require('node:child_process')
const path = require('node:path')

const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: path.join(__dirname, '..'), encoding: 'utf8' }).trim()
if (!/^[0-9a-f]{40}$/.test(sha)) throw new Error('无法读取发行包源提交 SHA')

async function applyElectronFuses(context) {
  if (context.electronPlatformName !== 'win32') throw new Error('仅支持 Windows 发行包')
  const { flipFuses, FuseVersion, FuseV1Options } = await import('@electron/fuses')
  await flipFuses(path.join(context.appOutDir, 'ProductWorkbench.exe'), {
    version: FuseVersion.V1,
    strictlyRequireAllFuses: true,
    [FuseV1Options.RunAsNode]: false,
    [FuseV1Options.EnableCookieEncryption]: true,
    [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
    [FuseV1Options.EnableNodeCliInspectArguments]: false,
    [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
    [FuseV1Options.OnlyLoadAppFromAsar]: true,
    [FuseV1Options.LoadBrowserProcessSpecificV8Snapshot]: false,
    [FuseV1Options.GrantFileProtocolExtraPrivileges]: false,
    [FuseV1Options.WasmTrapHandlers]: true,
  })
}

module.exports = {
  appId: 'com.siyu.productworkbench',
  productName: '商品云库',
  directories: { output: 'release' },
  asar: true,
  files: ['dist/main.js', 'dist/runtime.js', 'package.json'],
  npmRebuild: false,
  electronDownload: {
    checksums: {
      'electron-v44.3.0-win32-x64.zip': '26bf9a617d58d81772b3d68305d59ee48272969c15083c06db634a77358a8d9d',
    },
  },
  extraMetadata: { releaseSourceSha: sha },
  afterPack: applyElectronFuses,
  win: {
    target: [{ target: 'nsis', arch: ['x64'] }],
    executableName: 'ProductWorkbench',
    requestedExecutionLevel: 'asInvoker',
    artifactName: `Product-Workbench-${sha.slice(0, 12)}-windows-\${arch}-setup.\${ext}`,
  },
  nsis: {
    oneClick: true,
    perMachine: false,
    createDesktopShortcut: 'always',
    createStartMenuShortcut: true,
    shortcutName: '商品云库',
    uninstallDisplayName: '商品云库',
    deleteAppDataOnUninstall: false,
    runAfterFinish: true,
  },
  publish: null,
}
