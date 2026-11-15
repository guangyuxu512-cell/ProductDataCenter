/** Count Han ideographs as two units and other characters, including symbols, as one. */
export function titleUnits(value: string): number {
  return Array.from(value).reduce((sum, character) => {
    const code = character.codePointAt(0) ?? 0
    const han = (code >= 0x3400 && code <= 0x4dbf) || (code >= 0x4e00 && code <= 0x9fff) ||
      (code >= 0xf900 && code <= 0xfaff) || (code >= 0x20000 && code <= 0x2fa1f) ||
      (code >= 0x30000 && code <= 0x323af)
    return sum + (han ? 2 : 1)
  }, 0)
}
