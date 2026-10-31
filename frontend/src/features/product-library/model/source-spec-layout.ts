import type { ProductSku } from './contracts'

export interface SourceSpecAxis {
  name: string
  values: string[]
}

export interface SourceSpecLayout {
  axes: SourceSpecAxis[]
  rows: Record<string, string[]>
}

/** Read display labels only; ambiguous or inconsistent source text stays intact. */
export function sourceSpecLayout(skus: readonly ProductSku[]): SourceSpecLayout | null {
  if (!skus.length) return null
  const rows: Record<string, string[]> = {}
  let names: string[] | null = null
  for (const sku of skus) {
    const segments = sku.name.split(/\s*\/\s*(?=[^/:：]{1,40}[：:])/u)
    if (!segments.length || segments.length > 3) return null
    const pairs = segments.map((segment) => segment.match(/^\s*([^/:：]{1,40})[：:]\s*(.+?)\s*$/u))
    if (pairs.some((pair) => !pair)) return null
    const rowNames = pairs.map((pair) => pair![1].replace(/\s*[（(]\d+[）)]\s*$/u, '').trim())
    const values = pairs.map((pair) => pair![2].trim())
    if (rowNames.some((name) => !name) || values.some((value) => !value) || new Set(rowNames).size !== rowNames.length) return null
    if (names && (names.length !== rowNames.length || names.some((name, index) => name !== rowNames[index]))) return null
    names = rowNames
    rows[sku.draftKey] = values
  }
  return {
    axes: names!.map((name, index) => ({ name, values: [...new Set(skus.map((sku) => rows[sku.draftKey][index]))] })),
    rows,
  }
}
