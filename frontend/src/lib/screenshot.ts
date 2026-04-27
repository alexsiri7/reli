import { toCanvas } from 'html-to-image'

const MAX_BYTES = 2 * 1024 * 1024

export async function capturePageToCanvas(): Promise<HTMLCanvasElement> {
  return toCanvas(document.body, {
    filter: (node) => {
      if (node instanceof HTMLElement && node.dataset.screenshotExclude) return false
      return true
    },
    cacheBust: true,
  })
}

export function canvasToJpegBase64(canvas: HTMLCanvasElement, quality = 0.85): string {
  const dataUrl = canvas.toDataURL('image/jpeg', quality)
  return dataUrl.split(',')[1]
}

export function isWithinSizeLimit(base64: string): boolean {
  const bytes = (base64.length * 3) / 4
  return bytes <= MAX_BYTES
}
