import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyText } from './copy-text'

describe('copyText', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('优先使用 Clipboard API', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await copyText('3760269504500859111')
    expect(writeText).toHaveBeenCalledWith('3760269504500859111')
  })

  it('局域网 HTTP 没有 Clipboard API 时使用用户触发的复制', async () => {
    vi.stubGlobal('navigator', {})
    const command = vi.fn(() => true)
    Object.defineProperty(document, 'execCommand', { value: command, configurable: true })
    await copyText('商品标题')
    expect(command).toHaveBeenCalledWith('copy')
    expect(document.querySelector('textarea')).toBeNull()
  })

  it('复制被拒绝时报告失败并清理临时元素', async () => {
    vi.stubGlobal('navigator', {})
    Object.defineProperty(document, 'execCommand', { value: () => false, configurable: true })
    await expect(copyText('商品')).rejects.toThrow('复制失败')
    expect(document.querySelector('textarea')).toBeNull()
  })
})
