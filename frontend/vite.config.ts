import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { writeFileSync } from 'fs'
import { resolve } from 'path'

function versionJsonPlugin(): Plugin {
  const buildVersion = Date.now().toString()
  return {
    name: 'version-json',
    config() {
      return { define: { __APP_BUILD_VERSION__: JSON.stringify(buildVersion) } }
    },
    writeBundle(options) {
      const outDir = options.dir ?? resolve(__dirname, 'dist')
      writeFileSync(resolve(outDir, 'version.json'), JSON.stringify({ version: buildVersion }))
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), versionJsonPlugin()],
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
