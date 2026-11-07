'use strict';
// Codex's explicitly branded local distribution. The upstream install,
// checksum, atomic activation, rollback and post-install paths remain in use.
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { pipeline } = require('node:stream/promises');
const { Transform } = require('node:stream');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const run = promisify(execFile);
const CONFIG = '/usr/local/share/codex/workspace-runtime/provider.json';

function officialUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password ||
      !['persistent.oaistatic.com', 'oaisidekickupdates.blob.core.windows.net'].includes(url.hostname))
    throw Error('The official workspace source must use a trusted OpenAI HTTPS origin');
  return url.toString();
}

function readConfig(filename = CONFIG) {
  const state = fs.lstatSync(filename);
  if (!state.isFile() || state.size > 65536) throw Error('Invalid Codex dependency provider configuration');
  const value = JSON.parse(fs.readFileSync(filename, 'utf8'));
  if (value.schema === 'codex.workspace-provider.v1' && value.source === 'official-manifest') {
    officialUrl(value.manifestUrl);
    return value;
  }
  if (value.schema === 'codex.workspace-provider.v1' && value.source === 'official-catalog') return value;
  if (value.schema !== 'codex.workspace-provider.v1' || value.source !== 'codex-local' || value.targetPlatform !== 'linux' ||
      value.targetArch !== 'arm64' || !/^Codex-ARM64-[\d.]+$/.test(value.bundleVersion) ||
      !/^[a-f0-9]{64}$/.test(value.archiveSha256) ||
      path.dirname(value.archivePath) !== path.dirname(filename) ||
      !/^codex-workspace-[\d.]+\.tar\.gz$/.test(path.basename(value.archivePath))) {
    throw Error('Invalid Codex ARM64 dependency distribution descriptor');
  }
  return value;
}

function selected(target) {
  return process.env.CODEX_WORKSPACE_PROVIDER === '1' &&
    (target?.platform ?? process.platform) === 'linux' &&
    ['arm64', 'aarch64'].includes(target?.arch ?? process.arch);
}

function manifest(config) {
  return { archiveName: path.basename(config.archivePath), archiveSha256: config.archiveSha256,
    archiveUrl: 'codex-workspace:' + config.bundleVersion, bundleFormatVersion: 2,
    bundleVersion: config.bundleVersion, format: 'tar.gz', runtimeRootDirectoryName: 'codex-primary-runtime',
    targetPlatform: 'linux', targetArch: 'arm64' };
}

async function copyArchive(url, destination, progress, signal, config) {
  if (url !== manifest(config).archiveUrl) throw Error('Unknown Codex dependency distribution');
  signal?.throwIfAborted();
  const handle = await fsp.open(config.archivePath, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const state = await handle.stat();
    if (!state.isFile()) throw Error('Codex dependency archive is not a regular file');
    let copied = 0;
    const count = new Transform({ transform(chunk, encoding, done) {
      copied += chunk.length;
      progress?.({ downloadedBytes: copied, totalBytes: state.size });
      done(null, chunk);
    } });
    await pipeline(handle.createReadStream({ autoClose: false }), count,
      fs.createWriteStream(destination, { flags: 'wx', mode: 0o600 }), { signal });
  } finally { await handle.close(); }
}

async function validate(root, { execute = false } = {}) {
  const metadata = JSON.parse(await fsp.readFile(path.join(root, 'runtime.json'), 'utf8'));
  const local = metadata.provider === 'Codex';
  if (metadata.targetArch != null && !['arm64', 'aarch64'].includes(metadata.targetArch) ||
      metadata.targetPlatform != null && metadata.targetPlatform !== 'linux')
    throw Error('The installed workspace tools target another platform');
  if (!local && !['official-manifest', 'official-catalog'].includes(readConfig().source))
    throw Error('The installed workspace provider does not match its configured source');
  for (const executable of ['dependencies/node/bin/node', 'dependencies/python/bin/python3']) {
    const handle = await fsp.open(path.join(root, executable), 'r');
    try {
      const header = Buffer.alloc(20);
      const { bytesRead } = await handle.read(header, 0, header.length, 0);
      if (bytesRead !== 20 || header[0] !== 0x7f || header.toString('ascii', 1, 4) !== 'ELF' || header[4] !== 2 ||
          header[5] !== 1 || header.readUInt16LE(18) !== 183)
        throw Error('Workspace executable is not Linux ARM64 ELF: ' + executable);
    } finally { await handle.close(); }
  }
  const inventory = local ? JSON.parse(await fsp.readFile(path.join(root, 'codex-integrity.json'), 'utf8')) : { requiredFiles: [] };
  for (const item of inventory.requiredFiles) {
    const filename = path.resolve(root, item.path);
    if (!filename.startsWith(path.resolve(root) + path.sep)) throw Error('Unsafe dependency integrity path');
    const info = await fsp.lstat(filename);
    if (!info.isFile() || info.size !== item.bytes) throw Error('Missing or damaged workspace dependency: ' + item.path);
    const actual = crypto.createHash('sha256').update(await fsp.readFile(filename)).digest('hex');
    if (actual !== item.sha256) throw Error('Workspace dependency checksum differs: ' + item.path);
  }
  if (execute) {
    const environment = { ...process.env, PYTHONHOME: path.join(root, 'dependencies/python'),
      PYTHONPATH: '', PYTHONDONTWRITEBYTECODE: '1',
      PATH: [path.join(root, 'dependencies/node/bin'), path.join(root, 'dependencies/bin/fallback'),
        '/usr/local/bin', '/usr/bin', '/bin'].join(':'),
      NODE_PATH: path.join(root, 'dependencies/node/node_modules') };
    const receipts = [];
    for (const [executable, script] of [
      ['dependencies/node/bin/node', 'checks/workspace-node-check.cjs'],
      ['dependencies/python/bin/python3', 'checks/workspace-python-check.py'],
      ['dependencies/python/bin/python3', 'checks/workspace-render-check.py']]) {
      try {
        const result = await run(path.join(root, executable), [path.join(__dirname, path.basename(script)), root], {
          env: environment, timeout: 45000, maxBuffer: 262144, cwd: root, killSignal: 'SIGKILL' });
        const lines = result.stdout.trim().split('\n');
        const receipt = JSON.parse(lines.at(-1));
        if (receipt.passed !== true) throw Error('The executable check did not pass');
        receipts.push(receipt);
      } catch (error) {
        throw Error('Codex execution check failed (' + executable + '): ' +
          String(error.stderr || error.message).slice(-6000));
      }
    }
    const directory = path.join(os.homedir(), '.local/state/codex-workspace');
    await fsp.mkdir(directory, { recursive: true, mode: 0o700 });
    await fsp.writeFile(path.join(directory, 'last-validation.json'),
      JSON.stringify({ at: new Date().toISOString(), bundleVersion: metadata.bundleVersion, receipts }), { mode: 0o600 });
  }
  return metadata;
}

function nativeInstructions(paths, options, original) {
  if (!selected()) return original(paths, options);
  const toolsDirectory = process.env.CODEX_TOOLS_DIR;
  if (typeof toolsDirectory !== 'string' || !/^\/data\/(?:data|user\/\d+)\/com\.ai\.codex\/files\/codex-tools$/.test(toolsDirectory))
    throw Error('Codex Android application identity is unavailable');
  const config = JSON.parse(fs.readFileSync(path.join(toolsDirectory, 'installation.json'), 'utf8'));
  if (config.uid !== Number(process.env.CODEX_IME_UID)) throw Error('Codex dependency identity differs');
  const physical = guest => guest.startsWith(config.filesDir + '/') ? guest :
    path.join(config.filesDir, 'debian', guest);
  const bin = path.join(config.filesDir, 'codex-tools/bin');
  return original({ ...paths, nodePath: path.join(bin, 'workspace-node'),
    pythonPath: path.join(bin, 'workspace-python3'), pnpmPath: path.join(bin, 'pnpm'),
    gitPath: path.join(bin, 'git'), nodeModulesPath: physical(paths.nodeModulesPath),
    pythonLibrariesPath: physical(paths.pythonLibrariesPath), overrideBinPath: bin, fallbackBinPath: bin }, options) +
    '\n\nProvider: ' + (options?.bundleVersion?.startsWith('Codex-ARM64-') ?
      'Codex Linux ARM64 compatibility distribution; portable OpenAI libraries with real ARM64 engines and native modules. ' :
      'OpenAI Linux ARM64 bundle, acquired from the configured official source and execution-checked on Codex. ') +
    'The executable launchers enter the app-private Debian environment under the ordinary Android application UID. ' +
    'Use the physical task directory as cwd. The default Python command remains Android Python; use workspace-python3 for these bundled libraries. ' +
    'LibreOffice, Poppler and image conversion tools are also in the launcher directory. ' +
    'These dependency launchers use the ordinary app UID. Device Root operations use the separately authorized Android device bridge.';
}

function integrate(original) {
  if (!selected()) return original;
  return {
    ...original,
    resolveManifest: async args => {
      if (!selected(args.target)) return original.resolveManifest(args);
      const config = readConfig();
      if (config.source === 'official-catalog') return original.resolveManifest(args);
      if (config.source === 'official-manifest') {
        const value = await args.fetchManifest(officialUrl(config.manifestUrl), args.signal);
        if (!value || !/^[a-fA-F0-9]{64}$/.test(value.archiveSha256) ||
            typeof value.bundleVersion !== 'string' || !value.bundleVersion.trim() ||
            value.bundleFormatVersion !== 2 ||
            value.runtimeRootDirectoryName != null && value.runtimeRootDirectoryName !== 'codex-primary-runtime' ||
            value.targetArch != null && !['arm64', 'aarch64'].includes(value.targetArch) ||
            value.targetPlatform != null && value.targetPlatform !== 'linux' ||
            value.format != null && !['tar.gz', 'tar.xz'].includes(value.format) ||
            value.archiveName != null && (path.basename(value.archiveName) !== value.archiveName || value.archiveName.includes('\\')))
          throw Error('The official manifest is not compatible with the Codex ARM64 bundle contract');
        officialUrl(value.archiveUrl);
        return value;
      }
      return manifest(config);
    },
    downloadFile: (url, ...args) => url.startsWith('codex-workspace:') ?
      copyArchive(url, args[0], args[1], args[2], readConfig()) : original.downloadFile(url, ...args),
    validatePaths: async options => {
      const paths = await original.validatePaths(options);
      if (selected({ platform: options.targetPlatform, arch: process.arch })) {
        const staging = path.basename(path.dirname(options.runtimeRoot)) === 'payload' &&
          path.basename(path.dirname(path.dirname(options.runtimeRoot))).startsWith('codex-runtime-install-');
        await validate(options.runtimeRoot, { execute: staging });
      }
      return paths;
    },
    diagnose: async options => {
      const result = await original.diagnose(options);
      if (!result.installed) return result;
      const root = options?.runtimeRoot ?? path.join(options?.installRoot ?? path.join(os.homedir(), '.cache/codex-runtimes'), 'codex-primary-runtime');
      try { await validate(root, { execute: true }); return result; }
      catch (error) { return { ...result, installed: false, instructions: null, problems: [error.message] }; }
    },
    instructions: (paths, options) => nativeInstructions(paths, options, original.instructions)
  };
}

// The reviewed clients probe network requirements/configuration before
// creating its task connection. That short-lived probe must not acquire and
// close the task executor's one-shot native bootstrap. Only that fixed probe
// function receives this adapter (26.1016: Qc; 26.1021: xl, the dedicated
// --print-startup-config runner); ordinary task transports are unchanged.
function integrateNetworkProbe(original, runtime = {}) {
  const platform = runtime.platform ?? process.platform;
  const arch = runtime.arch ?? process.arch;
  const verifyExecutable = runtime.verifyExecutable ?? (filename => {
    if (!fs.lstatSync(filename).isFile()) throw Error('Official configuration probe is not a regular executable');
    fs.accessSync(filename, fs.constants.X_OK);
  });
  return function (options, ...args) {
    const env = options?.env;
    if (platform !== 'linux' || !['arm64', 'aarch64'].includes(arch) ||
        env?.CODEX_PHONE_CLIENT_COMPAT !== '1' || !env.CODEX_NATIVE_BOOTSTRAP ||
        options.executablePath !== '/usr/local/bin/codex-native') {
      return original.call(this, options, ...args);
    }
    if (options.spawnCommand != null || options.spawnArgs != null || options.wslDistro != null)
      throw Error('Unsupported startup configuration probe transport');
    const executablePath = '/usr/lib/chatgpt/resources/codex';
    verifyExecutable(executablePath);
    // Preserve the real CLI options, configuration layers, auth policy and
    // environment. The bundled official program has no Codex native-session
    // extension. The original probe reads startup configuration/requirements
    // and optionally performs its existing policy-directed sign-out.
    return original.call(this, { ...options, executablePath }, ...args);
  };
}

// 26.1103 resolves a launch specification before its dedicated startup runner.
// Adapt only the fixed print-config probe after the official resolver succeeds.
function integrateStartupTransportResolver(original, runtime = {}) {
  const selectProbe = integrateNetworkProbe(value => value, runtime);
  return async function (options, ...args) {
    const result = await original.call(this, options, ...args);
    if (!result || options?.startupCommand?.args?.[0] !== '--print-startup-config') return result;
    return selectProbe(result);
  };
}

// Enter Electron's own fullscreen mode (the F11 menu role), once per main window.
// EWMH alone only changes the outer X11 window and can leave the client chrome visible.
function installPhoneFullscreen(electron, env = process.env) {
  if (env.CODEX_PHONE_CLIENT_COMPAT !== '1') return false;
  const { app, BrowserWindow } = electron;
  const installed = Symbol.for('codex.phoneFullscreen.v1');
  if (app[installed]) return true;
  app[installed] = true;
  const tracked = new WeakSet();
  const applied = new WeakSet();
  function track(window) {
    if (!window || window.isDestroyed() || tracked.has(window) || !window.webContents) return;
    tracked.add(window);
    const contents = window.webContents;
    const detach = () => {
      window.removeListener('ready-to-show', enter);
      contents.removeListener('did-finish-load', enter);
    };
    function enter() {
      if (applied.has(window) || window.isDestroyed() || contents.isDestroyed()) return;
      if (window.getParentWindow?.() || window.isModal?.()) return;
      let url;
      try { url = new URL(contents.getURL()); } catch { return; }
      // Never fullscreen auth popups, DevTools, or the client's embedded browser.
      if (url.protocol !== 'app:' || url.hostname !== '-' || url.pathname !== '/index.html') return;
      applied.add(window);
      try {
        window.setFullScreen(true);
        detach();
      } catch {
        applied.delete(window);
        console.warn('[codex-phone-window] Fullscreen request unavailable');
      }
    }
    contents.on('did-finish-load', enter);
    window.on('ready-to-show', enter);
    window.once('closed', detach);
    enter();
  }
  app.on('browser-window-created', (_event, window) => track(window));
  const existing = () => BrowserWindow.getAllWindows().forEach(track);
  if (app.isReady()) existing(); else app.once('ready', existing);
  return true;
}

if (process.versions.electron && process.type === 'browser' && process.env.CODEX_PHONE_CLIENT_COMPAT === '1') {
  installPhoneFullscreen(require('electron'));
}

module.exports = { integrate, integrateNetworkProbe, integrateStartupTransportResolver, installPhoneFullscreen, readConfig, manifest, copyArchive, validate, officialUrl };
