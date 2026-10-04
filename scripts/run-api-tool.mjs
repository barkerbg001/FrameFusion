import { spawnSync } from 'node:child_process'
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

const toolArgs = process.argv.slice(2)
if (toolArgs.length === 0) {
  console.error('Usage: node scripts/run-api-tool.mjs <command> [args…]')
  process.exit(1)
}

// Run tools through the venv interpreter so they never pick up a global install.
const [command, ...args] = toolArgs
const pythonArgs = command === 'manage' ? ['manage.py', ...args] : ['-m', command, ...args]
const result = spawnSync(python, pythonArgs, {
  cwd: apiDir,
  stdio: 'inherit',
  env: {
    ...process.env,
    PYTHONPATH: apiDir,
  },
})

if (result.error) {
  console.error(`Could not run ${python}: ${result.error.message}`)
}
process.exit(result.status ?? 1)
