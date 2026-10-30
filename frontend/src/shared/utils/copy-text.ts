/** 浏览器剪贴板 API 需要安全上下文；局域网 HTTP 使用用户操作触发的降级。 */
export async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      // 某些桌面环境禁用了 Clipboard API，继续尝试浏览器原生复制。
    }
  }
  const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const input = document.createElement('textarea')
  input.value = value
  input.setAttribute('readonly', '')
  input.style.position = 'fixed'
  input.style.left = '-9999px'
  document.body.appendChild(input)
  try {
    input.focus({ preventScroll: true })
    input.select()
    if (!document.execCommand('copy')) throw new Error('复制失败')
  } finally {
    input.remove()
    focused?.focus({ preventScroll: true })
  }
}
