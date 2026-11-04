import type { CategoryAttribute } from '../api/category-lookup'
import type { LibraryProduct } from './contracts'

/** The source value is a preview, not proof that the current platform accepts it. */
export function originalAttributeValue(
  target: CategoryAttribute, definitions: CategoryAttribute[], product: LibraryProduct, categoryId: string | null,
): string {
  if (product.platform !== 'douyin' || !categoryId || categoryId !== product.sourceCategoryId) return ''
  const byId = product.attributes.filter((item) => item.id && item.id === target.id)
  if (byId.length === 1) return byId[0].value
  if (byId.length > 1) return ''
  const label = target.label.trim()
  if (!label || definitions.filter((item) => item.label.trim() === label).length !== 1) return ''
  const byName = product.attributes.filter((item) => item.name.trim() === label)
  return byName.length === 1 ? byName[0].value : ''
}

/** Cross-platform IDs are unrelated: match only unique names and accepted values. */
export function pddAttributeValue(target: CategoryAttribute, definitions: CategoryAttribute[], product: LibraryProduct): string {
  if (product.platform !== 'pdd') return ''
  const label = target.label.trim()
  if (!label || definitions.filter((item) => item.label.trim() === label).length !== 1) return ''
  const matches = product.attributes.filter((item) => item.name.trim() === label)
  if (matches.length !== 1) return ''
  const values = matches[0].value.split('、').map((value) => value.trim()).filter(Boolean)
  if (!values.length || (target.options.length && target.allowCustom !== true && values.some((value) =>
    target.options.filter((option) => option.label === value).length !== 1))) return ''
  return values.join('、')
}
