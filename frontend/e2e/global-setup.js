import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

/** Reset the development database to the deterministic demo data before the run. */
export default function globalSetup() {
  const backend = fileURLToPath(new URL('../../backend/', import.meta.url))
  execFileSync(`${backend}.venv/bin/python`, ['-m', 'app.seed', '--reset'], {
    cwd: backend,
    stdio: 'inherit',
    env: { ...process.env, LOG_LEVEL: 'WARNING' },
  })
}
