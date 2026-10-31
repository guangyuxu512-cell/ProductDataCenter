import type { EditorSku, ProductEditorDraft } from './editor-contracts'

export interface SkuCombination { key: string; specValueIds: Record<string, string>; sku: EditorSku | null }
export interface SkuGrid { combinations: SkuCombination[]; unmatched: EditorSku[]; tooMany: boolean }

function combinationKey(values: Record<string, string>): string {
  return JSON.stringify(Object.entries(values).sort(([a], [b]) => a.localeCompare(b)))
}

/** 未采集的组合只显示占位；不会自动创建 SKU，也不会猜测在售状态。 */
export function buildSkuGrid(draft: ProductEditorDraft, limit = 1000): SkuGrid {
  const axes = draft.dimensions
  if (!axes.length || axes.some((axis) => !axis.values.length)) {
    return { combinations: [], unmatched: [...draft.skus], tooMany: false }
  }
  if (axes.reduce((count, axis) => count * axis.values.length, 1) > limit) {
    return { combinations: [], unmatched: [...draft.skus], tooMany: true }
  }
  const valid = new Map<string, EditorSku>()
  const unmatched: EditorSku[] = []
  for (const sku of draft.skus) {
    const complete = !sku.unmappedSpecIds.length && Object.keys(sku.specValueIds).length === axes.length &&
      axes.every((axis) => axis.values.some((value) => value.id === sku.specValueIds[axis.id]))
    const key = combinationKey(sku.specValueIds)
    if (!complete || valid.has(key)) unmatched.push(sku)
    else valid.set(key, sku)
  }
  let choices: Array<Record<string, string>> = [{}]
  for (const axis of axes) {
    choices = choices.flatMap((choice) => axis.values.map((value) => ({ ...choice, [axis.id]: value.id })))
  }
  return { combinations: choices.map((specValueIds) => {
    const key = combinationKey(specValueIds)
    return { key, specValueIds, sku: valid.get(key) ?? null }
  }), unmatched, tooMany: false }
}
