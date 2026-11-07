'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { integrateNetworkProbe } = require('./codex-workspace-provider.cjs');

function options() {
  return Object.freeze({ executablePath: '/usr/local/bin/codex-native',
    args: Object.freeze(['-c', 'fixture=true', 'app-server', '--analytics-default-enabled']),
    cwd: '/home/codex', env: Object.freeze({ CODEX_PHONE_CLIENT_COMPAT: '1',
      CODEX_NATIVE_BOOTSTRAP: '/private/startup.json', CODEX_CLI_PATH: '/usr/local/bin/codex-native' }) });
}
const phone = { platform: 'linux', arch: 'arm64', verifyExecutable: filename => {
  assert.equal(filename, '/usr/lib/chatgpt/resources/codex');
} };

test('only the probe executable changes; config, environment and call arguments are preserved', () => {
  const input = options();
  const context = {};
  let received;
  const probe = integrateNetworkProbe(function (...args) { received = args; assert.equal(this, context); return 42; }, phone);
  assert.equal(probe.call(context, input, '26.1016.51333', { signOut: false }), 42);
  assert.equal(received[0].executablePath, '/usr/lib/chatgpt/resources/codex');
  assert.equal(received[0].env, input.env);
  assert.equal(received[0].args, input.args);
  assert.equal(received[0].cwd, input.cwd);
  assert.deepEqual(received.slice(1), ['26.1016.51333', { signOut: false }]);
  assert.equal(input.executablePath, '/usr/local/bin/codex-native');
});
test('other platforms and architectures keep their original transport', () => {
  for (const runtime of [{ platform: 'win32', arch: 'arm64' }, { platform: 'linux', arch: 'x64' }]) {
    const input = options();
    const probe = integrateNetworkProbe(value => value, { ...runtime, verifyExecutable: () => assert.fail('must not select helper') });
    assert.equal(probe(input), input);
  }
});
test('26.1021 startup command preserves print-config flags and runner timeout', () => {
  const input = { ...options(), args: ['app-server', '--print-startup-config',
    '--startup-client-info', '{"name":"codex_desktop","version":"26.1021.22027"}',
    '--startup-sign-out'] };
  let received;
  const probe = integrateNetworkProbe((...args) => { received = args; }, phone);
  probe(input, 30000);
  assert.equal(received[0].executablePath, '/usr/lib/chatgpt/resources/codex');
  assert.equal(received[0].args, input.args);
  assert.equal(received[0].env, input.env);
  assert.equal(received[1], 30000);
});
test('unselected phone mode or native session leaves the transport alone', () => {
  for (const env of [{}, { CODEX_PHONE_CLIENT_COMPAT: '1' }, { CODEX_NATIVE_BOOTSTRAP: '/private/startup.json' }]) {
    const input = { ...options(), env };
    assert.equal(integrateNetworkProbe(value => value, phone)(input), input);
  }
});
test('custom executable selections are retained', () => {
  const input = { ...options(), executablePath: '/custom/codex' };
  assert.equal(integrateNetworkProbe(value => value, phone)(input), input);
});
test('an unavailable official helper fails instead of consuming the native task session', () => {
  const probe = integrateNetworkProbe(() => assert.fail('must not invoke task launcher'), {
    ...phone, verifyExecutable: () => { throw Error('missing official helper'); } });
  assert.throws(() => probe(options()), /missing official helper/);
});
test('unexpected spawn overrides cannot redirect the configuration probe', () => {
  for (const override of [{ spawnCommand: 'other' }, { spawnArgs: [] }, { wslDistro: 'other' }])
    assert.throws(() => integrateNetworkProbe(() => assert.fail('must not spawn'), phone)({ ...options(), ...override }), /Unsupported/);
});
const { integrateStartupTransportResolver } = require('./codex-workspace-provider.cjs');
test('26.1103 resolver adapts only the fixed startup probe after resolving the official spec', async () => {
  const spec = options(), context = {};
  const input = Object.freeze({ startupCommand: { args: ['--print-startup-config','--startup-client-info','{}','--startup-sign-out'] } });
  let received;
  const resolve = integrateStartupTransportResolver(function (...args) { received=args; assert.equal(this,context); return spec; },phone);
  const output = await resolve.call(context,input,['profile=fixture']);
  assert.equal(output.executablePath,'/usr/lib/chatgpt/resources/codex');
  assert.equal(output.env,spec.env);assert.equal(output.args,spec.args);
  assert.deepEqual(received,[input,['profile=fixture']]);
});
test('26.1103 ordinary tasks, unrelated startup commands and null resolutions keep the native selection', async () => {
  const spec=options();
  for(const input of [{},{startupCommand:{args:['app-server']}},{startupCommand:{args:[]}}])
    assert.equal(await integrateStartupTransportResolver(()=>spec,phone)(input),spec);
  assert.equal(await integrateStartupTransportResolver(()=>null,phone)({startupCommand:{args:['--print-startup-config']}}),null);
});
test('26.1103 resolver preserves failures and rejects unexpected startup transports', async () => {
  const input={startupCommand:{args:['--print-startup-config']}};
  await assert.rejects(integrateStartupTransportResolver(()=>{throw Error('resolver failed');},phone)(input),/resolver failed/);
  await assert.rejects(integrateStartupTransportResolver(()=>({...options(),spawnCommand:'other'}),phone)(input),/Unsupported/);
});
