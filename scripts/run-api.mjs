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

const reload = process.argv.includes('--reload')
const uvicornArgs = [
  '-m',
  'uvicorn',
  'app.main:app',
  '--host',
  '0.0.0.0',
  '--port',
  '8000',
]

if (reload) {
  uvicornArgs.push('--reload')
}

const child = spawn(python, uvicornArgs, {
  cwd: apiDir,
  stdio: 'inherit',
  shell: isWin,
})

child.on('exit', (code) => {
  process.exit(code ?? 0)
})

child.on('error', (error) => {
  console.error(error.message)
  process.exit(1)
})
