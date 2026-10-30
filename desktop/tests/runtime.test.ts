import assert from 'node:assert/strict'
import test from 'node:test'
import { defaultProductUrl, isTrustedNavigation, resolveProductUrl } from '../runtime'

test('默认地址是现有 NAS 商品云库', () => {
  assert.equal(resolveProductUrl().href, defaultProductUrl)
  assert.equal(resolveProductUrl('http://127.0.0.1:3612/').hostname, '127.0.0.1')
  assert.equal(resolveProductUrl('https://example.test/').protocol, 'https:')
})

test('拒绝外网明文地址、凭据和非网页协议', () => {
  for (const value of ['http://example.test/', 'http://8.8.8.8/', 'http://u:p@192.168.0.102:3612/', 'file:///tmp/x', 'https://example.test/path']) {
    assert.throws(() => resolveProductUrl(value))
  }
})

test('只允许导航到商品云库本源', () => {
  const origin = resolveProductUrl().origin
  assert.equal(isTrustedNavigation('http://192.168.0.102:3612/#/products', origin), true)
  assert.equal(isTrustedNavigation('http://192.168.0.102:3613/', origin), false)
  assert.equal(isTrustedNavigation('https://example.test/', origin), false)
  assert.equal(isTrustedNavigation('not a url', origin), false)
})
