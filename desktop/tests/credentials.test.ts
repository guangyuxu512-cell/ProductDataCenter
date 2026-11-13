import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { BasicCredentialStore, isExpectedChallenge, maySendCredentials, parseLegacyLogin, validateCredentials, verifyCredentials, type SecretCipher } from '../credentials'

const fakeCipher: SecretCipher = {
  isEncryptionAvailable: () => true,
  encryptString: (value) => Buffer.from(Buffer.from(value, 'utf8').map((byte) => byte ^ 0xa5)),
  decryptString: (value) => Buffer.from(Buffer.from(value).map((byte) => byte ^ 0xa5)).toString('utf8'),
}

test('历史登录文件只提取用户名和密码，禁止控制字符', () => {
  assert.deepEqual(parseLegacyLogin('username: demo\npassword: sample:with-colon\n'), { username: 'demo', password: 'sample:with-colon' })
  assert.throws(() => parseLegacyLogin('username: demo\n'))
  assert.throws(() => validateCredentials({ username: 'a:b', password: 'test' }))
  assert.throws(() => validateCredentials({ username: 'a', password: 'a\nb' }))
})

test('凭据只以加密形式保存，并绑定原始服务器地址', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pdc-credential-test-'))
  try {
    const file = join(root, 'secure', 'login.enc')
    const store = new BasicCredentialStore(file, fakeCipher)
    const credentials = { username: 'example-user', password: 'example-secret' }
    assert.equal(await store.load('https://example.test'), null)
    await store.save('https://example.test', credentials)
    assert.equal((await readFile(file)).includes(Buffer.from(credentials.password)), false)
    assert.deepEqual(await store.load('https://example.test'), credentials)
    assert.equal(await store.load('https://other.test'), null)
    await store.save('https://example.test', { username: 'next', password: 'replacement' })
    assert.deepEqual(await store.load('https://example.test'), { username: 'next', password: 'replacement' })
    await assert.rejects(() => new BasicCredentialStore(file, { ...fakeCipher, isEncryptionAvailable: () => false }).load('https://example.test'))
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('仅向预期 HTTPS 服务或本机测试服务响应 Basic 挑战', () => {
  const origin = 'https://119.29.188.118:19001'
  const challenge = { isProxy: false, scheme: 'basic', host: '119.29.188.118', port: 19001 }
  assert.equal(isExpectedChallenge(origin + '/api/v1/products', challenge, origin), true)
  assert.equal(isExpectedChallenge('https://other.test/', challenge, origin), false)
  assert.equal(isExpectedChallenge(origin + '/', { ...challenge, isProxy: true }, origin), false)
  assert.equal(isExpectedChallenge(origin + '/', { ...challenge, host: 'other.test' }, origin), false)
  assert.equal(isExpectedChallenge(origin + '/', { ...challenge, port: 443 }, origin), false)
  assert.equal(maySendCredentials('http://192.168.0.102:3612'), false)
  assert.equal(maySendCredentials('http://127.0.0.1:3612'), true)
})

test('凭据只在实际验证成功后可用于保存，且不跟随重定向', async () => {
  let redirectedRequests = 0
  const server = createServer((req, res) => {
    if (req.url === '/redirect-target') { redirectedRequests++; res.writeHead(200).end(); return }
    if (req.headers.authorization === 'Basic ' + Buffer.from('demo:redirect').toString('base64')) res.writeHead(302, { Location: '/redirect-target' }).end()
    else if (req.headers.authorization === 'Basic ' + Buffer.from('demo:correct').toString('base64')) res.writeHead(200).end('ok')
    else res.writeHead(401).end()
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  try {
    const address = server.address()
    assert.ok(address && typeof address !== 'string')
    const origin = 'http://127.0.0.1:' + address.port
    assert.equal(await verifyCredentials(origin, { username: 'demo', password: 'correct' }), true)
    assert.equal(await verifyCredentials(origin, { username: 'demo', password: 'wrong' }), false)
    assert.equal(await verifyCredentials(origin, { username: 'demo', password: 'redirect' }), false)
    assert.equal(redirectedRequests, 0)
    assert.equal(await verifyCredentials('http://192.168.0.102:3612', { username: 'demo', password: 'correct' }), false)
  } finally { await new Promise<void>((resolve, reject) => server.close((e) => e ? reject(e) : resolve())) }
})
