import type { CategoryAttribute } from '../api/category-lookup'
import type { LibraryProduct, ProductAttributeValue } from './contracts'

function valuesOf(item: LibraryProduct['attributes'][number] | NonNullable<LibraryProduct['targetAttributes']>[number]): ProductAttributeValue[] {
  if (item.valueItems?.length) return item.valueItems.map((value) => ({ ...value }))
  const text = 'value' in item ? item.value : item.values.join('、')
  return text.split('、').map((name) => name.trim()).filter(Boolean).map((name) => ({ valueId: '0', name }))
}

export function originalAttributeValues(
  target: CategoryAttribute, definitions: CategoryAttribute[], product: LibraryProduct, categoryId: string | null,
): ProductAttributeValue[] {
  if (product.platform !== 'douyin' || !categoryId || categoryId !== product.sourceCategoryId) return []
  const byId = product.attributes.filter((item) => item.id && item.id === target.id)
  if (byId.length === 1) return valuesOf(byId[0])
  if (byId.length > 1) return []
  const label = target.label.trim()
  if (!label || definitions.filter((item) => item.label.trim() === label).length !== 1) return []
  const byName = product.attributes.filter((item) => item.name.trim() === label)
  return byName.length === 1 ? valuesOf(byName[0]) : []
}

/** The source value is a preview, not proof that the current platform accepts it. */
export function originalAttributeValue(
  target: CategoryAttribute, definitions: CategoryAttribute[], product: LibraryProduct, categoryId: string | null,
): string {
  return originalAttributeValues(target, definitions, product, categoryId).map((value) => value.name).join('、')
}

export function pddAttributeValues(target: CategoryAttribute, definitions: CategoryAttribute[], product: LibraryProduct): ProductAttributeValue[] {
  if (product.platform !== 'pdd') return []
  const label = target.label.trim()
  if (!label || definitions.filter((item) => item.label.trim() === label).length !== 1) return []
  const matches = product.attributes.filter((item) => item.name.trim() === label)
  if (matches.length !== 1) return []
  const source = valuesOf(matches[0])
  if (!source.length) return []
  return source.flatMap((value) => {
    const options = target.options.filter((option) => option.label === value.name)
    if (options.length === 1) return [{ valueId: options[0].value, name: options[0].label }]
    if (!target.options.length && ['text', 'number'].includes(target.control)) return [{ valueId: '0', name: value.name }]
    if (target.allowCustom === true || target.ruleStatus === 'unknown') return [{ valueId: '0', name: value.name }]
    return []
  })
}

/** Cross-platform IDs are unrelated: match only unique names and accepted values. */
export function pddAttributeValue(target: CategoryAttribute, definitions: CategoryAttribute[], product: LibraryProduct): string {
  return pddAttributeValues(target, definitions, product).map((value) => value.name).join('、')
}
