import { cloneVNode } from 'vue'
import { useMessage, type ImageRenderToolbarProps } from 'naive-ui'

const extensions: Record<string, string> = {
  'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif',
  'image/webp': 'webp', 'image/svg+xml': 'svg', 'image/avif': 'avif',
}

function filename(source: string, type: string): string {
  let name = ''
  try { name = decodeURIComponent(new URL(source, window.location.href).pathname.split('/').pop() ?? '') }
  catch { /* Use the generic filename when the source has no usable path. */ }
  name = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').slice(0, 100) || '商品图片'
  const extension = extensions[type]
  if (type === 'image/jpeg' && /\.jpe?g$/i.test(name)) return name
  return extension && !name.toLowerCase().endsWith(`.${extension}`) ? `${name}.${extension}` : name
}

/** Keep Naive's preview controls while turning its open-link action into a download. */
export function useImagePreviewToolbar(source: () => string | null | undefined) {
  const message = useMessage()
  let downloading = false
  async function download() {
    const url = source()
    if (!url || downloading) return
    downloading = true
    try {
      // Existing uploaded images can be cached without the new CORS header.
      // Refresh the response when the user explicitly downloads the image.
      const response = await fetch(url, { credentials: 'same-origin', referrerPolicy: 'no-referrer', cache: 'reload' })
      if (!response.ok) throw new Error('image request failed')
      const image = await response.blob()
      const type = image.type.toLowerCase().split(';', 1)[0].trim()
      if (!type.startsWith('image/') || !image.size) throw new Error('not an image')
      const objectUrl = URL.createObjectURL(image)
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = filename(url, type)
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000)
    } catch {
      message.error('图片下载失败，请检查图片地址或来源访问限制')
    } finally {
      downloading = false
    }
  }
  return ({ nodes }: ImageRenderToolbarProps) => {
    const button = cloneVNode(nodes.download)
    button.props = { ...button.props, onClick: download, role: 'button', ariaLabel: '下载图片', title: '下载图片',
      tabindex: 0, onKeydown: (event: KeyboardEvent) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); void download() }
      } }
    return [nodes.rotateCounterclockwise, nodes.rotateClockwise, nodes.resizeToOriginalSize,
      nodes.zoomOut, nodes.zoomIn, button, nodes.close]
  }
}
