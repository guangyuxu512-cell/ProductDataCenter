import type { MeasureTemplate } from '../api/category-lookup'

export interface MeasurePart { value: string; unit: string }

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
