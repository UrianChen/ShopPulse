// Every Chinese string literal in the interface must have an English translation.
//
// Interface copy uses the Chinese text as its translation key (src/lib/messages.ts), and t()
// silently falls back to Chinese when a key is missing. This check finds such literals, including
// label maps whose values are passed to t() later. Unused translations are reported as warnings;
// `--strict` makes them fail too.
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const { english } = await import('../src/lib/messages.ts');
const { serverEnglish } = await import('../src/lib/serverMessages.ts');

// Files that hold translations or deliberate untranslated text (document titles set per language).
const SKIP = new Set(['src/lib/messages.ts', 'src/lib/serverMessages.ts', 'src/lib/i18n.ts']);
const CJK = /\p{Script=Han}|[、。，；：？！（）《》「」【】…]/u;
// Quoted literals; template literals with ${} are skipped (their text is built at runtime).
const LITERAL = /'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\$]|\\.)*)`/g;

function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return files(path);
    return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1');
}

const missing = [];
const used = new Set();
for (const path of files(join(root, 'src'))) {
  const name = relative(root, path).replaceAll('\\', '/');
  if (SKIP.has(name) || name === 'src/lib/schema.ts' || name.startsWith('src/test/')) continue;
  const lines = stripComments(readFileSync(path, 'utf8')).split('\n');
  lines.forEach((line, index) => {
    for (const match of line.matchAll(LITERAL)) {
      const raw = match[1] ?? match[2] ?? match[3];
      if (!raw || !CJK.test(raw)) continue;
      const text = JSON.parse(`"${raw.replace(/\\'/g, "'").replace(/"/g, '\\"')}"`);
      used.add(text);
      // Punctuation-only joiners (、；) are not copy; they only count as using a translation.
      if (/\p{Script=Han}/u.test(text) && !(text in english) && !(text in serverEnglish))
        missing.push(`${name}:${index + 1}: ${text}`);
    }
  });
}
const unused = Object.keys(english).filter(key => !used.has(key));
if (unused.length)
  console.log(`${unused.length} translation(s) no longer used:\n  ${unused.join('\n  ')}`);
if (missing.length) {
  console.log(`FAIL: ${missing.length} string(s) without an English translation:`);
  console.log('  ' + missing.join('\n  '));
  process.exit(1);
}
if (unused.length && process.argv.includes('--strict')) process.exit(1);
console.log(`PASS: ${used.size} interface strings have English translations`);
