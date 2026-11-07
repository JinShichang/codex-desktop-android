'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { installPhoneFullscreen } = require('../tools/runtime/codex-workspace-provider.cjs');

function window(url = 'app://-/index.html', parent = null) {
  const win = new EventEmitter();
  const contents = new EventEmitter();
  Object.assign(contents, { url, getURL() { return this.url; }, isDestroyed: () => false });
  return Object.assign(win, {
    webContents: contents, destroyed: false, fullscreen: false, calls: [],
    isDestroyed() { return this.destroyed; }, getParentWindow: () => parent, isModal: () => false,
    setFullScreen(value) { this.calls.push(value); this.fullscreen = value; },
  });
}
function runtime(windows = [], ready = true) {
  return { app: Object.assign(new EventEmitter(), { isReady: () => ready }),
    BrowserWindow: { getAllWindows: () => windows } };
}
const phone = { CODEX_PHONE_CLIENT_COMPAT: '1' };

test('phone startup enters F11 mode once and respects a later manual exit', () => {
  const win = window();
  installPhoneFullscreen(runtime([win]), phone);
  assert.deepEqual(win.calls, [true]);
  win.fullscreen = false; // The person presses F11.
  win.emit('ready-to-show'); win.webContents.emit('did-finish-load');
  assert.equal(win.fullscreen, false);
  assert.deepEqual(win.calls, [true]);
});
test('waits for the main document and handles windows created after startup', () => {
  const electron = runtime();
  installPhoneFullscreen(electron, phone);
  const win = window('about:blank');
  electron.app.emit('browser-window-created', {}, win);
  assert.deepEqual(win.calls, []);
  win.webContents.url = 'app://-/index.html?locale=zh-CN#home';
  win.webContents.emit('did-finish-load');
  win.emit('ready-to-show');
  assert.deepEqual(win.calls, [true]);
});
test('does not fullscreen auth, embedded browser, devtools or child dialogs', () => {
  const windows = [window('https://auth.openai.com/'), window('https://example.com/'),
    window('devtools://devtools/'), window('app://-/index.html', {})];
  installPhoneFullscreen(runtime(windows), phone);
  windows.forEach(win => assert.deepEqual(win.calls, []));
});
test('does not change the non-phone profile', () => {
  const win = window(), electron = runtime([win]);
  assert.equal(installPhoneFullscreen(electron, {}), false);
  assert.equal(electron.app.listenerCount('browser-window-created'), 0);
  assert.deepEqual(win.calls, []);
});
test('registers only once, including when loaded before Electron is ready', () => {
  const win = window(), electron = runtime([win], false);
  installPhoneFullscreen(electron, phone);
  installPhoneFullscreen(electron, phone);
  assert.deepEqual(win.calls, []);
  electron.app.emit('ready');
  assert.deepEqual(win.calls, [true]);
  assert.equal(electron.app.listenerCount('browser-window-created'), 1);
});
test('a closed or destroyed window is never changed by a delayed load', () => {
  const win = window('about:blank'), electron = runtime([win]);
  installPhoneFullscreen(electron, phone);
  win.destroyed = true; win.emit('closed');
  win.webContents.url = 'app://-/index.html';
  win.webContents.emit('did-finish-load');
  assert.deepEqual(win.calls, []);
});
