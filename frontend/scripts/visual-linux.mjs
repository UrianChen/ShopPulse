// Run the visual tests in the Playwright Linux container, as CI does, so that Linux baselines can
// be checked and updated from any OS: `npm run test:visual:linux -- --update-snapshots`.
// The frontend is copied into the container (without node_modules), and the Linux screenshots
// and test results are copied back.
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));
const version = lock.packages['node_modules/@playwright/test'].version;
const args = process.argv.slice(2).map(arg => `'${arg.replaceAll("'", "'\\''")}'`);
const script = [
  'mkdir /app',
  'tar -C /work --exclude=./node_modules --exclude=./dist --exclude=./test-results -cf - . | tar -C /app -xf -',
  'cd /app',
  'npm ci --no-audit --no-fund --loglevel=error',
  `npm run test:visual -- ${args.join(' ')}; status=$?`,
  'mkdir -p /work/visual/__screenshots__ && cp -r visual/__screenshots__/linux /work/visual/__screenshots__/',
  'rm -rf /work/test-results && if [ -d test-results ]; then cp -r test-results /work/; fi',
  'exit $status',
].join(' && ');
const result = spawnSync(
  'docker',
  [
    'run',
    '--rm',
    '--ipc=host',
    '--env',
    'CI=1',
    '--mount',
    `type=bind,source=${root},target=/work`,
    `mcr.microsoft.com/playwright:v${version}-noble`,
    'bash',
    '-c',
    script,
  ],
  { stdio: 'inherit' },
);
process.exit(result.status ?? 1);
