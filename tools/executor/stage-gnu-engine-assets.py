"""Stage a successful GNU controller package as an APK-owned matched pair."""
from pathlib import Path
import argparse
import hashlib
import json
import tarfile
import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    if not state.get('buildCompleted') or not state.get('packageCompleted') or state.get('buildExitCode') != 0:
        raise ValueError('A successful, packaged build is required')
    archive = Path(state['package'])
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != state['packageSha256']:
            raise ValueError('GNU package differs from its completed build record')
    version = tomllib.loads((Path(state['source']) / 'codex-rs/Cargo.toml').read_text())['workspace']['package']['version']
    args.output.mkdir(parents=True, exist_ok=False)
    payload = args.output / 'gnu-engine'
    payload.mkdir()
    files = []
    with tarfile.open(archive) as package:
        members = package.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate GNU package entries')
        descriptor = json.load(package.extractfile('manifest.json'))
        if descriptor['target'] != 'aarch64-unknown-linux-gnu' or descriptor['sourceBase'] != state['sourceBase']:
            raise ValueError('GNU package source/target mismatch')
        indexed = {item['path']: item for item in descriptor['files']}
        for name, destination in (('codex', 'codex-native'), ('codex-code-mode-host', 'codex-code-mode-host')):
            member = package.getmember(name)
            if not member.isfile() or not 20 <= member.size <= 536870912:
                raise ValueError('Unexpected GNU controller file')
            expected = indexed[name]
            digest = hashlib.sha256()
            with package.extractfile(member) as source, (payload / destination).open('xb') as output:
                while block := source.read(65536):
                    digest.update(block)
                    output.write(block)
            if member.size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
                raise ValueError('GNU controller differs from package inventory')
            files.append({'name': destination, 'bytes': member.size, 'sha256': digest.hexdigest()})
    (payload / 'manifest.json').write_text(json.dumps({
        'schema': 'codex.gnu-engine.payload.v1', 'target': 'aarch64-unknown-linux-gnu',
        'sourceBase': state['sourceBase'], 'version': version, 'files': files,
    }, indent=2) + '\n')
    print(json.dumps({'version': version, 'output': str(args.output), 'bytes': sum(item['bytes'] for item in files)}))


if __name__ == '__main__':
    main()
