import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/file_v2_repository.dart';
import 'package:vault_ai_frontend/services/upload_queue.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  tearDown(() {
    FileV2Repository.clear();
    ZkActiveMvk.clear();
  });

  test('logout/login cannot reuse the prior File V2 key owner', () async {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 1)),
      vaultId: 'vault-a',
      vaultHandle: 'VLT-A',
    );
    final prior = FileV2Repository.current();
    expect(prior, isNotNull);

    // This is the same ordering used by AppState.clearSession.
    ZkActiveMvk.clear();
    FileV2Repository.clear();
    expect(FileV2Repository.current(), isNull);

    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 2)),
      vaultId: 'vault-a',
      vaultHandle: 'VLT-A',
    );
    final rehydrated = FileV2Repository.current();
    expect(rehydrated, isNotNull);
    expect(identical(prior, rehydrated), isFalse);

    final ciphertext = await rehydrated!.encryptMetadata(
      fileId: 'file-after-login',
      filename: 'juli',
    );
    final metadata =
        await rehydrated.decryptMetadata('file-after-login', ciphertext);
    expect(metadata.filename, 'juli');
  });

  test('vault switch rotates repository even without an intermediate read', () {
    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 3)),
      vaultId: 'vault-a',
      vaultHandle: 'VLT-A',
    );
    final first = FileV2Repository.current();

    ZkActiveMvk.set(
      mvk: SecretKey(List<int>.filled(32, 4)),
      vaultId: 'vault-b',
      vaultHandle: 'VLT-B',
    );
    final second = FileV2Repository.current();
    expect(identical(first, second), isFalse);
  });

  test('one upload queue job keeps one File V2 identity across retry',
      () async {
    var calls = 0;
    final ids = <String>[];
    final queue = UploadQueueController(
      maxAttempts: 2,
      action: (job, bytes, progress) async {
        final id = job.fileV2Id ??= 'file-${job.id}';
        ids.add(id);
        calls += 1;
        if (calls == 1) {
          throw const TransientUploadException('uncertain response');
        }
        return UploadResult(fileId: id);
      },
    );
    queue.enqueue(UploadJob(
      id: 'att-stable',
      name: 'juli.jpg',
      kind: 'file',
      size: 3,
      readBytes: () async => Uint8List.fromList([1, 2, 3]),
    ));
    await queue.waitForIdle();
    expect(ids, ['file-att-stable', 'file-att-stable']);
    expect(queue.uploadedCount, 1);
    queue.dispose();
  });
}
