// Tokenizes tests/fixtures/editors/sample.c with the Basilisk grammar on top
// of the real C grammar, as VS Code does, and checks the scopes.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vt = require('vscode-textmate');
const onig = require('vscode-oniguruma');

const ROOT = path.join(__dirname, '..', '..');
const SYN = path.join(ROOT, 'vscode', 'syntaxes');
const files = {
  'source.basilisk': path.join(SYN, 'basilisk.tmLanguage.json'),
  'basilisk.injection': path.join(SYN, 'basilisk-injection.tmLanguage.json'),
  'source.c': require.resolve('tm-grammars/grammars/c.json'),
};
const wasm = fs.readFileSync(require.resolve('vscode-oniguruma/release/onig.wasm')).buffer;
const registry = new vt.Registry({
  onigLib: onig.loadWASM(wasm).then(() => ({
    createOnigScanner: (s) => new onig.OnigScanner(s),
    createOnigString: (s) => new onig.OnigString(s),
  })),
  loadGrammar: async (s) => (files[s] ? vt.parseRawGrammar(fs.readFileSync(files[s], 'utf8'), files[s]) : null),
  getInjections: (s) => (s === 'source.basilisk' ? ['basilisk.injection'] : []),
});

const EXPECT = [  // [line (1-based), token text, scope it must carry]
  [2, 'Sample', 'entity.name.section.markdown'],
  [4, '*emph*', 'markup.italic.basilisk'],
  [4, '`code`', 'markup.inline.raw.basilisk'],
  [6, 'face', 'storage.modifier.basilisk'],
  [6, 'vector', 'storage.type.basilisk'],
  [6, '[]', 'keyword.operator.stencil.basilisk'],
  [7, 'event', 'keyword.control.event.basilisk'],
  [7, 'init', 'entity.name.function.event.basilisk'],
  [8, 'foreach', 'keyword.control.loop.basilisk'],
  [8, 'reduction', 'keyword.control.basilisk'],
  [9, 'Delta', 'variable.language.basilisk'],
];
const NOT = [  // Basilisk words inside comments and strings stay comments/strings
  ['/* foreach in a comment */', 'foreach', 'keyword.control.loop.basilisk'],
  ['printf ("foreach in a string");', 'foreach', 'keyword.control.loop.basilisk'],
];

function tokenize(grammar, text) {
  let state = vt.INITIAL;
  return text.split('\n').map((line) => {
    const r = grammar.tokenizeLine(line, state);
    state = r.ruleStack;
    return r.tokens.map((t) => ({ text: line.slice(t.startIndex, t.endIndex), scopes: t.scopes }));
  });
}

registry.loadGrammar('source.basilisk').then((g) => {
  const lines = tokenize(g, fs.readFileSync(path.join(ROOT, 'tests', 'fixtures', 'editors', 'sample.c'), 'utf8'));
  let failures = 0;
  for (const [ln, text, scope] of EXPECT) {
    const tok = lines[ln - 1].find((t) => t.text.trim() === text || t.text.includes(text) && t.scopes.includes(scope));
    const ok = tok && tok.scopes.includes(scope);
    console.log(`${ok ? 'PASS' : 'FAIL'} line ${ln} ${JSON.stringify(text)} -> ${scope}` + (ok ? '' : `  got ${tok ? tok.scopes.join(' ') : 'no token'}`));
    failures += !ok;
  }
  for (const [src, text, scope] of NOT) {
    const toks = tokenize(g, src)[0].filter((t) => t.text.includes(text));
    const ok = toks.length > 0 && toks.every((t) => !t.scopes.includes(scope));
    console.log(`${ok ? 'PASS' : 'FAIL'} ${JSON.stringify(src)}: ${text} not ${scope}`);
    failures += !ok;
  }
  console.log(`FAILURES: ${failures}`);
  process.exit(failures ? 1 : 0);
});
