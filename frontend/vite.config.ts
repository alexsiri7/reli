import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'
import { createHash } from 'crypto'
import { readFileSync, writeFileSync } from 'fs'
import { resolve } from 'path'

function versionJsonPlugin(): Plugin {
  let contentHash = ''
  return {
    name: 'version-json',
    config() {
      // __APP_BUILD_VERSION__ reads from globalThis at runtime; the actual
      // value is injected into index.html by writeBundle once the
      // content hash is known.
      return { define: { __APP_BUILD_VERSION__: 'globalThis.__APP_BUILD_VERSION__' } }
    },
    generateBundle(_options, bundle) {
      // Hash the content of all JS chunks so the version only changes
      // when actual code changes, not on every redeploy.
      const hash = createHash('sha256')
      for (const fileName of Object.keys(bundle).sort()) {
        const chunk = bundle[fileName]
        if (chunk.type === 'chunk') {
          hash.update(chunk.code)
        }
      }
      contentHash = hash.digest('hex').slice(0, 16)

      // Emit version.json for the polling check
      this.emitFile({
        type: 'asset',
        fileName: 'version.json',
        source: JSON.stringify({ version: contentHash }),
      })
    },
    writeBundle(options) {
      const outDir = options.dir ?? resolve(__dirname, 'dist')
      // Inject the content hash into index.html so the app knows its version
      const htmlPath = resolve(outDir, 'index.html')
      const html = readFileSync(htmlPath, 'utf-8')
      const script = `<script>globalThis.__APP_BUILD_VERSION__=${JSON.stringify(contentHash)}</script>`
      writeFileSync(htmlPath, html.replace('<head>', `<head>${script}`))
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    versionJsonPlugin(),
    VitePWA({
      registerType: 'autoUpdate',
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff,woff2}'],
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            urlPattern: /^https?:\/\/[^/]+\/api\/(things|thing-types|briefing)(\?.*)?$/,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'api-read-cache',
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 60 * 60 * 24, // 1 day
              },
            },
          },
          {
            urlPattern: /^https?:\/\/[^/]+\/api\/things\/[^/]+\/relationships(\?.*)?$/,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'api-relationships-cache',
              expiration: {
                maxEntries: 100,
                maxAgeSeconds: 60 * 60 * 24,
              },
            },
          },
          {
            urlPattern: /^https?:\/\/[^/]+\/api\/chat/,
            handler: 'NetworkOnly',
          },
          {
            urlPattern: /\.(?:woff2?|ttf|otf|eot)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'static-fonts',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 60 * 60 * 24 * 30, // 30 days
              },
            },
          },
          {
            urlPattern: /\.(?:png|jpg|jpeg|gif|webp|svg|ico)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'static-images',
              expiration: {
                maxEntries: 50,
                maxAgeSeconds: 60 * 60 * 24 * 30, // 30 days
              },
            },
          },
        ],
      },
      manifest: {
        name: 'Reli',
        short_name: 'Reli',
        description: 'Reli — your personal relationship manager',
        theme_color: '#4F46E5',
        background_color: '#ffffff',
        display: 'standalone',
        icons: [
          {
            src: '/apple-touch-icon.png',
            sizes: '180x180',
            type: 'image/png',
          },
          {
            src: '/favicon-32.png',
            sizes: '32x32',
            type: 'image/png',
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
