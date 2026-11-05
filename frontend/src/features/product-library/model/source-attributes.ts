import type { CategoryAttribute } from '../api/category-lookup'
import type { LibraryProduct, ProductAttributeValue } from './contracts'

function valuesOf(item: LibraryProduct['attributes'][number] | NonNullable<LibraryProduct['targetAttributes']>[number]): ProductAttributeValue[] {
  if (item.valueItems?.length) return item.valueItems.map((value) => ({ ...value }))
  const texts = 'value' in item ? [item.value] : item.values
  return texts.map((name) => name.trim()).filter(Boolean).map((name) => ({ valueId: '0', name }))
}

export function normalizeMultiValues(target: CategoryAttribute, values: ProductAttributeValue[]): ProductAttributeValue[] {
  if (target.control !== 'multi' || target.ruleStatus !== 'confirmed') return values
  const byName = (name: string) => target.options.filter((option) => option.label.trim() === name)
  const mapped = values.flatMap((value) => {
    const byId = target.options.filter((option) => value.valueId !== '0' && option.value === value.valueId)
    if (byId.length === 1) return [{ valueId: byId[0].value, name: byId[0].label }]
    const exact = byName(value.name.trim())
    if (value.valueId === '0' && exact.length === 1) return [{ valueId: exact[0].value, name: exact[0].label }]
    const parts = value.name.split(/[|、,，;；]/u).map((part) => part.trim())
    if (value.valueId === '0' && parts.length > 1 && parts.every((part) => byName(part).length === 1)) {
      return parts.map((part) => ({ valueId: byName(part)[0].value, name: byName(part)[0].label }))
    }
    return [value]
  })
  return mapped.filter((value, index) => mapped.findIndex((item) => item.valueId === value.valueId && item.name === value.name) === index)
}

export function originalAttributeValues(
  target: CategoryAttribute, definitions: CategoryAttribute[], product: LibraryProduct, categoryId: string | null,
): ProductAttributeValue[] {
  if (product.platform !== 'douyin' || !categoryId || categoryId !== product.sourceCategoryId) return []
  const byId = product.attributes.filter((item) => item.id && item.id === target.id)
  if (byId.length === 1) return normalizeMultiValues(target, valuesOf(byId[0]))
  if (byId.length > 1) return []
  const label = target.label.trim()
  if (!label || definitions.filter((item) => item.label.trim() === label).length !== 1) return []
  const byName = product.attributes.filter((item) => item.name.trim() === label)
  return byName.length === 1 ? normalizeMultiValues(target, valuesOf(byName[0])) : []
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
  const source = normalizeMultiValues(target, valuesOf(matches[0]))
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
