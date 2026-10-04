import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const apiDir = path.resolve(__dirname, '..', 'api')
const isWin = process.platform === 'win32'
const venvPython = isWin
  ? path.join(apiDir, '.venv', 'Scripts', 'python.exe')
  : path.join(apiDir, '.venv', 'bin', 'python')
const python = fs.existsSync(venvPython)
  ? venvPython
  : isWin
    ? 'python'
    : 'python3'

const host = process.env.FRAMEFUSION_HOST || '127.0.0.1'
const port = process.env.FRAMEFUSION_PORT || '8000'
const reload = process.argv.includes('--reload')

// FrameFusion has no login, so refuse to listen beyond this machine unless told otherwise.
const loopback = new Set(['127.0.0.1', 'localhost', '::1', '[::1]'])
const allowRemote = /^(1|true|yes|on)$/i.test(process.env.FRAMEFUSION_ALLOW_REMOTE || '')
if (!loopback.has(host) && !allowRemote) {
  console.error(
    `Refusing to bind to ${host}: FrameFusion has no login and anyone who can reach it can use ` +
      'your saved API keys. Use 127.0.0.1, or set FRAMEFUSION_ALLOW_REMOTE=true only behind ' +
      'your own authentication (see SECURITY.md).',
  )
  process.exit(1)
}

// The background job runner lives inside this process, so run a single server process.
const args = ['manage.py', 'runserver', `${host}:${port}`]
if (!reload) {
  args.push('--noreload')
}

const child = spawn(python, args, {
  cwd: apiDir,
  stdio: 'inherit',
})

child.on('exit', (code) => {
  process.exit(code ?? 0)
})

child.on('error', (error) => {
  console.error(error.message)
  process.exit(1)
})
