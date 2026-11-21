import type { CategoryAttribute, MeasureTemplate } from '../api/category-lookup'

export interface MeasurePart { value: string; unit: string }
export interface MultiMeasurePart { name: string; value: string; unit: string }

const escapePattern = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')

export function parseMeasure(template: MeasureTemplate, text: string): MeasurePart[] | null {
  let groups = 1
  const indexes: Array<{ number: number; unit?: number }> = []
  const pattern = template.modules.map((module) => {
    const prefix = escapePattern(module.prefix)
    const suffix = ['*', '×', 'x', 'X'].includes(module.suffix) ? '[xX×*]' : escapePattern(module.suffix)
    const units = [...module.units].sort((a, b) => b.label.length - a.label.length).map((unit) => escapePattern(unit.label))
    const index: { number: number; unit?: number } = { number: groups++ }
    const unitPattern = units.length ? `(${units.join('|')})?` : ''
    if (units.length) index.unit = groups++
    indexes.push(index)
    return `\\s*${prefix}\\s*([+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))?\\s*${unitPattern}\\s*${suffix}`
  }).join('')
  const match = new RegExp(`^${pattern}\\s*$`, 'u').exec(text)
  if (!match || !indexes.some((index) => match[index.number])) return null
  return indexes.map((index) => ({ value: match[index.number] ?? '', unit: index.unit ? match[index.unit] ?? '' : '' }))
}

export function formatMeasure(template: MeasureTemplate, parts: MeasurePart[]): string {
  if (!parts.some((part) => part.value.trim())) return ''
  return template.modules.map((module, index) => {
    const part = parts[index] ?? { value: '', unit: '' }
    return `${module.prefix}${part.value.trim()}${part.value.trim() ? part.unit : ''}${module.suffix}`
  }).join('')
}

export function validMeasure(template: MeasureTemplate, text: string): boolean {
  const parts = parseMeasure(template, text)
  if (!parts) return false
  return template.modules.every((module, index) => {
    const part = parts[index]
    if ((module.required && !part.value) || (part.value && module.units.length > 0 && !part.unit) || (part.unit && !part.value)) return false
    if (!part.value) return true
    const number = Number(part.value)
    const decimals = part.value.includes('.') ? part.value.split('.')[1].length : 0
    return Number.isFinite(number) && (module.dataType !== 'int' || Number.isInteger(number)) &&
      (module.minimum === null || number >= module.minimum) && (module.maximum === null || number <= module.maximum) &&
      (module.precision === null || decimals <= module.precision)
  })
}

export function validMultiMeasure(rule: CategoryAttribute['multiMeasureRule'], value: string,
  options: CategoryAttribute['options'] = []): boolean | null {
  if (!rule?.units.length) return false
  const source = value.trim()
  const unit = [...rule.units].sort((a, b) => b.label.length - a.label.length).find((item) => item.label && source.endsWith(item.label))
  if (!unit) return false
  const text = source.slice(0, -unit.label.length).trim()
  const numeric = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/u
  const validNumber = (raw: string) => {
    const number = Number(raw)
    const decimals = raw.includes('.') ? raw.split('.')[1].length : 0
    return Number.isFinite(number) && (rule.dataType !== 'int' || Number.isInteger(number)) &&
      (rule.minimum === null || number >= rule.minimum) && (rule.maximum === null || number <= rule.maximum) &&
      (rule.precision === null || decimals <= rule.precision)
  }
  const known = new Set(options.filter((option) => option.label && text.startsWith(option.label))
    .map((option) => text.slice(option.label.length).trim()).filter((number) => numeric.test(number)))
  if (known.size === 1) return validNumber([...known][0])
  if (known.size > 1) return null
  const valid = new Set<string>()
  for (let index = 1; index < text.length; index++) {
    const name = text.slice(0, index).trim(), number = text.slice(index).trim()
    if (name && numeric.test(number) && validNumber(number)) valid.add(JSON.stringify([name, number]))
  }
  return valid.size === 1 ? true : valid.size > 1 ? null : false
}

// Only split old composite values when the platform options or numeric rules
// identify exactly one possible split. Ambiguous values stay untouched.
export function parseMultiMeasure(rule: CategoryAttribute['multiMeasureRule'], value: string,
  options: CategoryAttribute['options'] = []): MultiMeasurePart | null {
  if (!rule?.units.length) return null
  const source = value.trim()
  const unit = [...rule.units].sort((a, b) => b.label.length - a.label.length)
    .find((item) => item.label && source.endsWith(item.label))
  if (!unit) return null
  const text = source.slice(0, -unit.label.length).trim()
  const numeric = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/u
  const matches = options.filter((option) => option.label && text.startsWith(option.label))
    .map((option) => ({ name: option.label, value: text.slice(option.label.length).trim(), unit: unit.label }))
    .filter((part) => numeric.test(part.value))
  if (matches.length === 1) return matches[0]
  if (matches.length > 1) return null
  const candidates: MultiMeasurePart[] = []
  for (let index = 1; index < text.length; index++) {
    const name = text.slice(0, index).trim(), number = text.slice(index).trim()
    const valueNumber = Number(number)
    const decimals = number.includes('.') ? number.split('.')[1].length : 0
    if (name && numeric.test(number) && Number.isFinite(valueNumber) &&
        (rule.dataType !== 'int' || Number.isInteger(valueNumber)) &&
        (rule.minimum === null || valueNumber >= rule.minimum) &&
        (rule.maximum === null || valueNumber <= rule.maximum) &&
        (rule.precision === null || decimals <= rule.precision)) {
      candidates.push({ name, value: number, unit: unit.label })
    }
  }
  return candidates.length === 1 ? candidates[0] : null
}

export function fabricCompositionProblem(rule: CategoryAttribute['multiMeasureRule'], values: string[],
  options: CategoryAttribute['options'] = []): string | null {
  if (!rule || rule.units.length !== 1 || rule.units[0].label !== '%' || !values.length ||
      values.some((value) => validMultiMeasure(rule, value, options) !== true)) return null
  const parts = values.map((value) => parseMultiMeasure(rule, value, options))
  if (parts.some((part) => part === null)) return null
  const known = parts.filter((part): part is MultiMeasurePart => part !== null)
  if (new Set(known.map((part) => part.name)).size !== known.length) return '不可重复'
  const total = known.reduce((sum, part) => sum + Number(part.value), 0)
  return Math.abs(total - 100) > 1e-8 ? '含量总和需为100%' : null
}
