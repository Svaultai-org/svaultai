import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_private_file_selection.dart';

void main() {
  const token = 'synthetic-session';
  const vaultId = 'synthetic-vault';
  final mvk = SecretKey(List<int>.filled(32, 41));

  test('one committed private upload supports exact local follow-ups', () {
    final selected = ZkPrivateFileSelection();
    expect(
        selected.bindCommittedV2Uploads(
          fileIds: ['synthetic-file'],
          listOffered: true,
          downloadOffered: true,
          token: token,
          vaultId: vaultId,
          mvk: mvk,
        ),
        true);
    for (final prompt in [
      'open it',
      'download it',
      'play it',
      'what colors are in it?',
    ]) {
      expect(
          selected.forFollowUp(
            prompt: prompt,
            token: token,
            vaultId: vaultId,
            mvk: mvk,
          ),
          'synthetic-file');
    }
  });

  test('multiple, failed, or unreadable uploads clear an earlier selection',
      () {
    final selected = ZkPrivateFileSelection();
    void bindOne() => selected.bindExactResult(
          fileId: 'earlier-file',
          token: token,
          vaultId: vaultId,
          mvk: mvk,
        );
    for (final ids in <List<String?>>[
      [],
      [null],
      [''],
      ['first-file', 'second-file'],
      ['first-file', null],
    ]) {
      bindOne();
      expect(
          selected.bindCommittedV2Uploads(
            fileIds: ids,
            listOffered: true,
            downloadOffered: true,
            token: token,
            vaultId: vaultId,
            mvk: mvk,
          ),
          false);
      expect(
          selected.forFollowUp(
            prompt: 'open it',
            token: token,
            vaultId: vaultId,
            mvk: mvk,
          ),
          isNull);
    }
    bindOne();
    expect(
        selected.bindCommittedV2Uploads(
          fileIds: ['new-file'],
          listOffered: true,
          downloadOffered: false,
          token: token,
          vaultId: vaultId,
          mvk: mvk,
        ),
        false);
    expect(
        selected.forFollowUp(
          prompt: 'open it',
          token: token,
          vaultId: vaultId,
          mvk: mvk,
        ),
        isNull);
  });

  test('token, vault, key, and new-topic changes invalidate selection', () {
    final selected = ZkPrivateFileSelection();
    void bind() => selected.bindExactResult(
          fileId: 'synthetic-file',
          token: token,
          vaultId: vaultId,
          mvk: mvk,
        );
    bind();
    expect(
        selected.forFollowUp(
          prompt: 'open it',
          token: 'next-session',
          vaultId: vaultId,
          mvk: mvk,
        ),
        isNull);
    bind();
    expect(
        selected.forFollowUp(
          prompt: 'open it',
          token: token,
          vaultId: 'next-vault',
          mvk: mvk,
        ),
        isNull);
    bind();
    expect(
        selected.forFollowUp(
          prompt: 'open it',
          token: token,
          vaultId: vaultId,
          mvk: SecretKey(List<int>.filled(32, 41)),
        ),
        isNull);
    bind();
    expect(
        selected.forFollowUp(
          prompt: 'find my beach video',
          token: token,
          vaultId: vaultId,
          mvk: mvk,
        ),
        isNull);
    expect(
        selected.forFollowUp(
          prompt: 'open it',
          token: token,
          vaultId: vaultId,
          mvk: mvk,
        ),
        isNull);
  });
}
