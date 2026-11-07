"""Independently check the real new run-as broker result (no device actions)."""
import argparse
import json
from pathlib import Path

PROOFS = {'memoryRead', 'memoryWrite', 'pidfdGetfd', 'sharedOffset', 'privateReadDenied',
          'protectedWriteDenied', 'rawChdirDenied', 'networkDenied', 'ioctlDenied', 'binderDenied',
          'threadMemory', 'threadPidfdGetfd'}


def verify(report):
    def require(value, message):
        if not value:
            raise ValueError(message)
    require(report['schema'] == 'codex.runas.broker-activity.v1', 'Wrong Activity schema')
    require(report['action'] == 'com.ai.codex.runasbrokerqualification.v1.RUN_BROKER_V1', 'Wrong independent action')
    require(report['state'] == 'complete' and report['passed'] is True, 'Activity failed')
    service = report['service']
    require(service['schema'] == 'codex.runas.broker-service.v1', 'Wrong service schema')
    require(service['serviceUid'] == 2000 and service['waitStatus'] == 0, 'Wrong shell identity or failed owner')
    for key in ('passed', 'childReaped', 'pipeReadersComplete', 'pipesClosed', 'cleanupComplete',
                'nativeCleanupVerified', 'installationUnchanged'):
        require(service[key] is True, 'Missing service proof: ' + key)
    require(service['quarantined'] is False, 'Service quarantine retained')
    require(report['installation'] == report['preflight'] == service['installation'], 'Install identity mismatch')
    installed = service['installation']
    require(installed['target']['packageName'] == 'com.ai.codex' and installed['target']['debuggable'] is True, 'Wrong target app')
    require(installed['qualification']['packageName'] == 'com.ai.codex.runasbrokerqualification.v1', 'Wrong diagnostic APK')
    require(installed['nativeLibraries']['libcodex_bionic_supervisor.so']
            == '6bccc77b4f2dff0f78fd22e4f6427263ee159d87b35c740e8be0622319fd4dd4', 'Runner is not the reviewed qKM94iHA')
    require(installed['nativeLibraries']['libcodex_qualification_worker.so']
            == '1f7054085ecfd920626cdf24603687cd5e9812b445cf171a2f4cff8efbecd3aa', 'Wrong fixed Bionic workload')
    child, receipt = json.loads(service['stdout']), json.loads(service['stderr'])
    require(child == service['child'] and receipt == service['receipt'], 'Raw streams mismatch parsed records')
    require(child['schema'] == 'codex.runas.broker-child.v1' and receipt['schema'] == 'codex.runas.broker-report.v1', 'Wrong native receipt schemas')
    require(child['pid'] == receipt['pid'] == service['ownerPid'], 'Reaped owner mismatch')
    require(child['nonce'] == receipt['nonce'] == service['nonce'], 'Native correlation nonce differs')
    for record in (child, receipt):
        require(record['passed'] is True and record['cleanupComplete'] is True, 'Native cleanup was not proved')
    require(child['quarantined'] is False and child['stdinChallengeMatches'] is True, 'Native challenge/quarantine differs')
    identity = child['identity']
    require(identity['pid'] == service['ownerPid'] and identity['parentPid'] == service['servicePid'], 'Wrong actual Python ancestry')
    require(identity['uid'] == identity['gid'] == [installed['target']['uid']] * 3, 'Python is not the target app UID/GID')
    require(identity['context'].startswith('u:r:runas_app:'), 'Python domain differs')
    for key in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb'):
        require(int(identity['status'][key], 16) == 0, 'Nonzero Python ' + key)
    for key in ('NoNewPrivs', 'Seccomp', 'Seccomp_filters'):
        require(int(identity['status'][key]) == 0, 'Wrong inherited Python ' + key)
    require(child['supervisorReturncode'] == 0 and child['processClosed'] is True, 'Supervisor was not really waited cleanly')
    result = child['nativeResult']
    require(result['started'] is True and result['cleanupComplete'] is True and result['outcome'] == 'exited'
            and result['exitCode'] == result['signal'] == 0, 'Trusted native lifecycle report failed')
    proofs = json.loads(child['stdout'])
    require(proofs == child['proofs'], 'Worker stream differs from result')
    require(set(proofs) == PROOFS | {'type', 'success'} and proofs['type'] == 'kernel-qualification', 'Wrong exact proof set')
    require(all(proofs[key] is True for key in PROOFS | {'success'}) and child['stderr'] == '', 'Real broker mechanism failed')
    require(child['options']['workspace'] == '/data/user/0/com.ai.codex/files/runas-native-v1/workspace', 'Workspace is not app-private')
    return {'schema': 'codex.runas-broker-verification.v1', 'passed': True, 'kernelProofs': len(PROOFS),
            'targetUid': installed['target']['uid'], 'bootstrapPid': child['pid'], 'supervisorPid': child['supervisorPid'],
            'scope': 'Actual UserService/run-as/Bionic native broker; PRoot shared paths and UI remain unqualified'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.report.read_text(encoding='utf-8-sig'))), indent=2))
