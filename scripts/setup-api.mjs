import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const apiDir = path.resolve(__dirname, '..', 'api')
const isWin = process.platform === 'win32'
const venvDir = path.join(apiDir, '.venv')
const venvPython = isWin
  ? path.join(venvDir, 'Scripts', 'python.exe')
  : path.join(venvDir, 'bin', 'python')
const systemPython = isWin ? 'python' : 'python3'

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    shell: isWin,
    ...options,
  })
  if (result.status !== 0) {
    process.exit(result.status ?? 1)
  }
}

if (!fs.existsSync(venvPython)) {
  console.log('Creating Python virtual environment in api/.venv …')
  run(systemPython, ['-m', 'venv', venvDir], { cwd: apiDir })
}

console.log('Installing API dependencies (runtime + dev tools) …')
run(venvPython, ['-m', 'pip', 'install', '-r', 'requirements-dev.txt'], {
  cwd: apiDir,
})

console.log('API setup complete.')
