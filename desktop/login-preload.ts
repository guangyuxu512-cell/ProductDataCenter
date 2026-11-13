import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('workbenchAuth', {
  submit: (username: string, password: string) => ipcRenderer.send('workbench-auth-submit', username, password),
  cancel: () => ipcRenderer.send('workbench-auth-cancel'),
  onError: (callback: (message: string) => void) => ipcRenderer.on('workbench-auth-error', (_event, value: unknown) => {
    if (typeof value === 'string') callback(value)
  }),
})
