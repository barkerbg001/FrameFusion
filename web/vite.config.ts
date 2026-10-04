import { defineConfig } from 'vite'

declare const process: { env: Record<string, string | undefined> }

// Same variables as scripts/run-api.mjs, so moving the API keeps the proxy pointed at it.
const apiHost = process.env.FRAMEFUSION_HOST || '127.0.0.1'
const apiPort = process.env.FRAMEFUSION_PORT || '8000'

export default defineConfig({
    server: {
        proxy: {
            '/api': {
                target: `http://${apiHost}:${apiPort}`,
                changeOrigin: true,
            },
        },
    },
});
