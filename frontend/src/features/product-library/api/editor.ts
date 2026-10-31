import { http } from '@/shared/api/http-client'
import type { DraftInspection, ProductEditorDraft, ProductEditorState } from '../model/editor-contracts'

export async function fetchEditor(productId: string, signal?: AbortSignal) {
  return (await http.get<ProductEditorState>(`/products/${encodeURIComponent(productId)}/edit-draft`, { signal })).data
}

export async function saveEditor(productId: string, expectedRevision: number, sourceFingerprint: string, draft: ProductEditorDraft) {
  return (await http.put<ProductEditorState>(`/products/${encodeURIComponent(productId)}/edit-draft`,
    { expectedRevision, sourceFingerprint, draft })).data
}

export async function inspectEditor(productId: string, expectedRevision: number, sourceFingerprint: string, draft: ProductEditorDraft) {
  return (await http.post<DraftInspection>(`/products/${encodeURIComponent(productId)}/edit-draft/inspect`,
    { expectedRevision, sourceFingerprint, draft })).data
}

export async function createManualProduct(title: string, groupId: string | null) {
  return (await http.post<ProductEditorState>('/products/manual', { title, groupId })).data
}

export async function uploadProductImage(file: File) {
  return (await http.post<{ url: string; sha256: string }>('/product-assets', file,
    { headers: { 'Content-Type': file.type || 'application/octet-stream' }, timeout: 120_000 })).data
}
