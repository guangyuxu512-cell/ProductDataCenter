import { describe, expect, it } from 'vitest'
import { titleUnits } from './title'

describe('商品标题计数', () => {
  it.each([
    ['中'.repeat(30), 60], ['中'.repeat(31), 62], ['中'.repeat(29) + '，!', 60],
    ['中'.repeat(29) + '，!A', 61], ['A'.repeat(60), 60], ['字😀，', 4], ['𠀀', 2],
  ])('汉字计二、字母数字与符号计一', (title, expected) => {
    expect(titleUnits(title as string)).toBe(expected)
  })
})
