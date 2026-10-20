// Record the actual Node runtime and lock inventory without claiming license approval.
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

const npmManifestPath = resolve(dirname(process.execPath), '../lib/node_modules/npm/package.json')
const npmManifest = JSON.parse(readFileSync(npmManifestPath, 'utf8'))

const lockBytes = readFileSync(new URL('./package-lock.json', import.meta.url))
const lock = JSON.parse(lockBytes)
const packages = Object.entries(lock.packages)
  .filter(([path]) => path !== '')
  .map(([path, value]) => ({
    path,
    version: value.version,
    license: value.license ?? 'UNKNOWN',
    review_status: 'PENDING',
    optional: value.optional ?? false,
  }))
const report = {
  scope: 'T02_COMPATIBILITY_LOCK_INVENTORY',
  product_status: 'NOT_RUN',
  node: process.version,
  npm: npmManifest.version,
  platform: process.platform,
  machine: process.arch,
  lock_sha256: createHash('sha256').update(lockBytes).digest('hex'),
  packages,
}
const serialized = `${JSON.stringify(report, null, 2)}\n`
if (process.argv[2]) writeFileSync(process.argv[2], serialized)
else process.stdout.write(serialized)
