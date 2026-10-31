export interface EditorImage { id: string; url: string }
export interface EditorSpecValue { id: string; sourceValueId: string | null; name: string; imageUrl: string }
export interface EditorDimension { id: string; name: string; values: EditorSpecValue[] }
export interface EditorSku {
  id: string
  sourceSkuId: string | null
  sourceLabel: string
  sourceStatusRaw?: string | null
  specValueIds: Record<string, string>
  unmappedSpecIds: string[]
  price: string | null
  stock: number | null
  merchantCode: string
  state: 'active' | 'inactive' | 'unknown'
}
export interface EditorAttribute { id: string; name: string; values: Array<{ id: string; name: string }> }
export interface ProductEditorDraft {
  title: string
  categoryIds: string[]
  categoryPath: string
  mainImages: EditorImage[]
  detailImages: EditorImage[]
  attributes: EditorAttribute[]
  dimensions: EditorDimension[]
  imageDimensionId: string | null
  skus: EditorSku[]
}
export interface ProductEditorState {
  productId: string
  revision: number
  sourceFingerprint: string
  sourceChanged: boolean
  draft: ProductEditorDraft
}
