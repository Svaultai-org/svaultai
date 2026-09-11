import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  final repoRoot = Directory.current.parent;
  final scripts = Directory.current.path + '/scripts';

  String read(String name) => File('$scripts/$name').readAsStringSync();

  test('production web wrappers reject stale release branches', () {
    final shell = read('build-web-release.sh');
    final powershell = read('build-web-release.ps1');
    final guard = read('verify-release-baseline.sh');

    expect(shell, contains('verify-release-baseline.sh'));
    expect(powershell, contains('git merge-base --is-ancestor'));
    expect(guard, contains('refs/heads/main:refs/remotes/origin/main'));
    expect(guard, contains('git merge-base --is-ancestor'));
    expect(guard, contains(r'git diff --quiet "$candidate_sha" --'));
  });

  test('shared release gate runs baseline check before either test suite', () {
    final gate = read('run-release-stabilization-gate.sh');
    final baseline = gate.indexOf('verify-release-baseline.sh');
    final backend = gate.indexOf(r'cd "$repo_dir/vault_ai_backend"');
    expect(baseline, greaterThanOrEqualTo(0));
    expect(backend, greaterThan(baseline));
  });

  test('the stale build-54 line does not contain current main', () async {
    final result = await Process.run(
      'git',
      const [
        'merge-base',
        '--is-ancestor',
        'origin/main',
        'codex/login-zk-fix-20260910',
      ],
      workingDirectory: repoRoot.path,
    );
    expect(result.exitCode, isNot(0));
  });
}
