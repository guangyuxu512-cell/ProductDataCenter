import { randomUUID } from 'node:crypto'
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { request as httpRequest } from 'node:http'
import { request as httpsRequest } from 'node:https'

export interface BasicCredentials { username: string; password: string }
export interface SecretCipher {
  isEncryptionAvailable(): boolean
  encryptString(value: string): Buffer
  decryptString(value: Buffer): string
}

export function validateCredentials(value: unknown): BasicCredentials {
  if (!value || typeof value !== 'object') throw new Error('登录信息格式无效')
  const { username, password } = value as Partial<BasicCredentials>
  if (typeof username !== 'string' || !username || username.length > 256 || /[:\r\n]/.test(username)) throw new Error('用户名格式无效')
  if (typeof password !== 'string' || !password || password.length > 4096 || /[\r\n]/.test(password)) throw new Error('密码格式无效')
  return { username, password }
}

export function parseLegacyLogin(text: string): BasicCredentials {
  const fields: Record<string, string> = {}
  for (const line of text.split(/\r?\n/)) {
    const at = line.indexOf(':')
    if (at < 0) continue
    const key = line.slice(0, at).trim().toLowerCase()
    if (key === 'username' || key === 'password') fields[key] = line.slice(at + 1).trim()
  }
  return validateCredentials(fields)
}

export function maySendCredentials(origin: string): boolean {
  try {
    const url = new URL(origin)
    return url.protocol === 'https:' || (url.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname))
  } catch { return false }
}

export function isExpectedChallenge(requestUrl: string, info: { isProxy: boolean; scheme: string; host: string; port: number }, origin: string): boolean {
  try {
    const url = new URL(origin)
    const expectedPort = Number(url.port || (url.protocol === 'https:' ? 443 : 80))
    return maySendCredentials(origin) && !info.isProxy && info.scheme.toLowerCase() === 'basic' &&
      new URL(requestUrl).origin === url.origin && info.host.toLowerCase() === url.hostname.toLowerCase() && info.port === expectedPort
  } catch { return false }
}

export class BasicCredentialStore {
  constructor(private readonly file: string, private readonly cipher: SecretCipher) {}

  async load(origin: string): Promise<BasicCredentials | null> {
    let data: Buffer
    try { data = await readFile(this.file) }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
      throw new Error('无法读取本机登录信息')
    }
    if (!this.cipher.isEncryptionAvailable()) throw new Error('系统加密不可用')
    try {
      const value = JSON.parse(this.cipher.decryptString(data)) as { origin?: string; credentials?: unknown }
      if (value.origin !== origin) return null
      return validateCredentials(value.credentials)
    } catch { throw new Error('本机登录信息无法解密') }
  }

  async save(origin: string, value: BasicCredentials): Promise<void> {
    if (!maySendCredentials(origin) || !this.cipher.isEncryptionAvailable()) throw new Error('无法安全保存登录信息')
    const credentials = validateCredentials(value)
    const encrypted = this.cipher.encryptString(JSON.stringify({ origin, credentials }))
    await mkdir(dirname(this.file), { recursive: true, mode: 0o700 })
    const temporary = this.file + '.' + randomUUID() + '.tmp'
    try {
      await writeFile(temporary, encrypted, { flag: 'wx', mode: 0o600 })
      await rename(temporary, this.file)
    } finally { await unlink(temporary).catch(() => undefined) }
  }
}

/** A one-shot request to the exact configured origin; redirects are never followed. */
export function verifyCredentials(origin: string, value: BasicCredentials, timeoutMs = 8000): Promise<boolean> {
  if (!maySendCredentials(origin)) return Promise.resolve(false)
  const url = new URL('/', origin)
  const credentials = validateCredentials(value)
  const authorization = 'Basic ' + Buffer.from(credentials.username + ':' + credentials.password, 'utf8').toString('base64')
  return new Promise((resolve) => {
    const request = (url.protocol === 'https:' ? httpsRequest : httpRequest)(url, {
      method: 'GET', timeout: timeoutMs, headers: { Authorization: authorization },
    }, (response) => { response.resume(); resolve(response.statusCode === 200) })
    request.once('error', () => resolve(false))
    request.once('timeout', () => { request.destroy(); resolve(false) })
    request.end()
  })
}
