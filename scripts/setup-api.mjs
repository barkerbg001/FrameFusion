import { spawnSync } from 'node:child_process'
import { randomBytes } from 'node:crypto'
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
const envPath = path.join(apiDir, '.env')
const examplePath = path.join(apiDir, '.env.example')

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    ...options,
  })
  if (result.error) {
    console.error(`Could not run ${command}: ${result.error.message}`)
    process.exit(1)
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1)
  }
}

function parseEnv(text) {
  const values = new Map()
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/)
    if (match) values.set(match[1], match[2].replace(/^["']|["']$/g, ''))
  }
  return values
}

// Fernet keys are 32 random bytes, url-safe base64 encoded (with padding).
function fernetKey() {
  return randomBytes(32).toString('base64').replace(/\+/g, '-').replace(/\//g, '_')
}

function djangoSecret() {
  return randomBytes(48).toString('base64url')
}

// Creates api/.env from the example, or appends settings that are missing.
// Existing values are never changed.
function ensureEnvFile() {
  const example = fs.readFileSync(examplePath, 'utf8')
  const generated = {
    DJANGO_SECRET_KEY: djangoSecret(),
    FRAMEFUSION_ENCRYPTION_KEY: fernetKey(),
  }

  if (!fs.existsSync(envPath)) {
    const contents = example.replace(
      /^(DJANGO_SECRET_KEY|FRAMEFUSION_ENCRYPTION_KEY)=\s*$/gm,
      (_, name) => `${name}=${generated[name]}`,
    )
    fs.writeFileSync(envPath, contents, { mode: 0o600 })
    console.log('Created api/.env with a new Django secret and encryption key.')
    return
  }

  const current = parseEnv(fs.readFileSync(envPath, 'utf8'))
  const wanted = parseEnv(example)
  const additions = []
  for (const [name, value] of wanted) {
    if (!current.has(name)) additions.push(`${name}=${generated[name] ?? value}`)
  }
  if (additions.length > 0) {
    fs.appendFileSync(envPath, `\n# Added by npm run setup\n${additions.join('\n')}\n`)
    console.log(`Added to api/.env: ${additions.map((l) => l.split('=')[0]).join(', ')}`)
  }

  const empty = Object.keys(generated).filter((name) => current.get(name) === '')
  if (empty.length > 0) {
    console.warn(
      `api/.env has an empty ${empty.join(' and ')}. Fill it in (see api/.env.example); ` +
        'setup never rewrites existing lines.',
    )
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

ensureEnvFile()

console.log('Upgrading the database from the multi-account version if needed …')
run(venvPython, ['manage.py', 'upgrade_single_user'], { cwd: apiDir })

console.log('Applying database migrations …')
run(venvPython, ['manage.py', 'migrate', '--noinput'], { cwd: apiDir })

console.log('\nAPI setup complete. Start everything with: npm run dev')
console.log('Then open http://127.0.0.1:5173 and follow the setup steps.')
