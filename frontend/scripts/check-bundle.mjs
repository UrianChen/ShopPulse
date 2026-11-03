// Size budget for the production build (run after `npm run build`).
// The entry chunk is what every first visit downloads; pages are split per route. Budgets are
// gzip sizes, which is what browsers transfer.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const ENTRY_BUDGET = 135 * 1024;
const CHUNK_BUDGET = 40 * 1024;

const assets = fileURLToPath(new URL('../dist/assets', import.meta.url));
const chunks = readdirSync(assets)
  .filter(name => name.endsWith('.js'))
  .map(name => ({ name, size: gzipSync(readFileSync(join(assets, name))).length }))
  .sort((a, b) => b.size - a.size);
const failures = [];
for (const chunk of chunks) {
  const entry = chunk.name.startsWith('index-');
  const budget = entry ? ENTRY_BUDGET : CHUNK_BUDGET;
  const line = `${chunk.name.padEnd(36)} ${(chunk.size / 1024).toFixed(1).padStart(7)} kB gzip`;
  console.log(line + (chunk.size > budget ? `  > ${budget / 1024} kB budget` : ''));
  if (chunk.size > budget) failures.push(chunk.name);
}
if (!chunks.some(chunk => chunk.name.startsWith('index-'))) failures.push('no entry chunk found');
if (failures.length) {
  console.log(`FAIL: over budget: ${failures.join(', ')}`);
  process.exit(1);
}
console.log(`PASS: ${chunks.length} chunks within budget`);
