import { describe, expect, it } from 'vitest'

import { mergePrecheck, precheckIssueCount, type AutoPrecheck } from './precheck'

function record(revision: number, state: AutoPrecheck['state'], updatedAt: string): AutoPrecheck {
  return { productId: '12345678', revision, state, updatedAt, error: null, result: null }
}

describe('自动预检 revision 合并', () => {
  it('旧请求晚返回时不会覆盖较新的保存结果', () => {
    const latest = record(3, 'pending', '2026-11-04T10:00:00Z')
    const lateOld = record(2, 'done', '2026-11-04T10:01:00Z')
    expect(mergePrecheck(latest, lateOld)).toBe(latest)
  })

  it('相同 revision 只接收更新时间更新的状态', () => {
    const running = record(3, 'running', '2026-11-04T10:00:02Z')
    expect(mergePrecheck(running, record(3, 'pending', '2026-11-04T10:00:01Z'))).toBe(running)
    expect(mergePrecheck(running, record(3, 'done', '2026-11-04T10:00:03Z')).state).toBe('done')
  })

  it('优先按结构化字段问题计数', () => {
    expect(precheckIssueCount({ productId: '1', title: '', status: 'needs_completion',
      issues: ['合并文本'], issueDetails: [
        { code: 'title_missing', message: '商品标题未填写', tab: 'base', fieldId: 'title' },
        { code: 'sku_price_invalid', message: '第 3 个 SKU 价格无效', tab: 'sku', skuIndex: 2 },
      ] })).toBe(2)
  })
})
