/**
 * Screenshot capture utilities using html-to-image.
 *
 * The capture flow:
 * 1. Caller hides the feedback dialog
 * 2. Waits 350ms for the DOM to repaint without the dialog
 * 3. Calls captureScreenshot() to capture the visible page
 * 4. Returns an HTMLCanvasElement for annotation
 */

import { toCanvas } from 'html-to-image'

export const SCREENSHOT_MAX_BYTES = 2 * 1024 * 1024 // 2MB
export const SCREENSHOT_JPEG_QUALITY = 0.85

/**
 * Capture the full document body as a canvas.
 * Elements marked with data-screenshot-exclude="true" are filtered out
 * (use this on the feedback dialog portal so it doesn't appear in the capture).
 */
export async function captureScreenshot(): Promise<HTMLCanvasElement> {
  return toCanvas(document.body, {
    filter: (node: Node) => {
      if (node instanceof Element) {
        if (node.getAttribute('data-screenshot-exclude') === 'true') return false
      }
      return true
    },
  })
}

/**
 * Export a canvas as a JPEG data URL at the configured quality.
 * Throws if the result exceeds SCREENSHOT_MAX_BYTES.
 */
export function canvasToJpeg(canvas: HTMLCanvasElement): string {
  const dataUrl = canvas.toDataURL('image/jpeg', SCREENSHOT_JPEG_QUALITY)
  // Approximate byte size: base64 encodes 3 bytes as 4 chars
  const base64Part = dataUrl.split(',')[1] ?? ''
  const approxBytes = Math.ceil((base64Part.length * 3) / 4)
  if (approxBytes > SCREENSHOT_MAX_BYTES) {
    throw new Error(`Screenshot exceeds 2 MB limit (≈${(approxBytes / 1024 / 1024).toFixed(1)} MB)`)
  }
  return dataUrl
}
