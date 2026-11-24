// Basilisk C extension: language detection + language client for basilisk_lsp.py
const vscode = require('vscode');
const { LanguageClient, TransportKind } = require('vscode-languageclient/node');

const PATTERN = new RegExp(
  '^\\s*(?:event\\s+\\w+\\s*\\(' +
  '|#\\s*include\\s*"(?:navier-stokes|grid|two-phase|vof|saint-venant|layered|embed|tension|run|utils|' +
  'output|view|fractions|axi|reduced|curvature|tracer|diffusion|poisson|green-naghdi|compressible|bcg|' +
  'advection|atmosphere|momentum|contact|heights|common)[/.]' +
  '|(?:(?:face|vertex|symmetric)\\s+)?(?:scalar|vector|tensor)\\s+\\*?\\s*\\w+\\s*\\[\\]' +
  '|foreach(?:_\\w+)?\\s*\\()', 'm');

let client;

function cfg() { return vscode.workspace.getConfiguration('basilisk'); }

function looksLikeBasilisk(doc) {
  if (!['c', 'cpp'].includes(doc.languageId) || !/\.(c|h)$/.test(doc.fileName)) return false;
  return PATTERN.test(doc.getText(new vscode.Range(0, 0, 500, 0)));
}

async function maybeSwitch(doc) {
  if (cfg().get('autoDetect') && looksLikeBasilisk(doc))
    await vscode.languages.setTextDocumentLanguage(doc, 'basilisk');
}

function settings() {
  const c = cfg();
  return {
    basiliskPath: c.get('path'), qcc: c.get('qcc'), qccFlags: c.get('qccFlags'),
    includeDirs: c.get('includeDirs'), diagnostics: c.get('diagnostics'), debounce: c.get('debounce'),
  };
}

function startClient(context) {
  const server = context.asAbsolutePath('server/basilisk_lsp.py');
  const python = cfg().get('pythonPath') || 'python3';
  const run = { command: python, args: [server], transport: TransportKind.stdio };
  client = new LanguageClient('basilisk', 'Basilisk C', { run, debug: run }, {
    documentSelector: [{ scheme: 'file', language: 'basilisk' }, { scheme: 'untitled', language: 'basilisk' }],
    initializationOptions: settings(),
    synchronize: { configurationSection: 'basilisk' },
  });
  return client.start();
}

async function activate(context) {
  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument(maybeSwitch),
    vscode.commands.registerCommand('basilisk.setLanguage', () => {
      const ed = vscode.window.activeTextEditor;
      if (ed) vscode.languages.setTextDocumentLanguage(ed.document, 'basilisk');
    }),
    vscode.commands.registerCommand('basilisk.restartServer', async () => {
      if (client) await client.stop();
      await startClient(context);
    }),
  );
  vscode.workspace.textDocuments.forEach(maybeSwitch);
  await startClient(context);
}

function deactivate() { return client ? client.stop() : undefined; }

module.exports = { activate, deactivate };
