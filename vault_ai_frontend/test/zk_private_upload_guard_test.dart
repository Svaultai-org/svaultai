import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_private_upload_guard.dart';

void main() {
  final mvk = SecretKey(List<int>.filled(32, 17));

  test('private upload keeps the exact unlocked key and strips prompt', () {
    expect(
        selectV2UploadKey(
          activeMvk: mvk,
          activeVaultId: 'vault-a',
          writerEnabled: true,
          readerEnabled: true,
          requiredPrivateMvk: mvk,
          requiredPrivateVaultId: 'vault-a',
        ),
        same(mvk));
    expect(
        uploadAccompanyingText(
          text: 'private synthetic prompt',
          requiredPrivateMvk: mvk,
        ),
        isNull);
  });

  test('missing or changed MVK cannot fall through to legacy upload', () {
    for (final active in <SecretKey?>[
      null,
      SecretKey(List<int>.filled(32, 17)),
    ]) {
      expect(
          () => selectV2UploadKey(
                activeMvk: active,
                activeVaultId: 'vault-a',
                writerEnabled: true,
                readerEnabled: true,
                requiredPrivateMvk: mvk,
                requiredPrivateVaultId: 'vault-a',
              ),
          throwsStateError);
    }
    expect(
        () => selectV2UploadKey(
              activeMvk: mvk,
              activeVaultId: 'vault-b',
              writerEnabled: true,
              readerEnabled: true,
              requiredPrivateMvk: mvk,
              requiredPrivateVaultId: 'vault-a',
            ),
        throwsStateError);
    expect(
        () => selectV2UploadKey(
              activeMvk: mvk,
              activeVaultId: 'vault-a',
              writerEnabled: false,
              readerEnabled: true,
              requiredPrivateMvk: mvk,
              requiredPrivateVaultId: 'vault-a',
            ),
        throwsStateError);
    // The shared legacy call sites retain their previous routing.
    expect(
        selectV2UploadKey(
          activeMvk: null,
          activeVaultId: null,
          writerEnabled: false,
          readerEnabled: false,
        ),
        isNull);
  });

  test('private attachment call requires V2 and cannot forward prompt', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf('Future<void> _sendZkPrivateAttachments(');
    final end = source.indexOf('Future<void> _sendOnce()', start);
    expect(start, greaterThan(0));
    expect(end, greaterThan(start));
    final privateBody = source.substring(start, end);
    expect(privateBody, contains('requiredPrivateMvk: mvk'));
    expect(privateBody, contains('requiredPrivateVaultId: app.vaultId'));
    expect(privateBody, isNot(contains('accompanyingText: text')));

    final uploadStart =
        source.indexOf('Future<_UploadAttachmentsOutcome> _uploadAttachments(');
    final uploadEnd =
        source.indexOf('Future<void> _sendZkPrivateAttachments(', uploadStart);
    expect(uploadStart, greaterThan(0));
    expect(uploadEnd, greaterThan(uploadStart));
    final uploadBody = source.substring(uploadStart, uploadEnd);
    expect(uploadBody, contains('zk_upload_guard.selectV2UploadKey('));
    expect(uploadBody, contains('zk_upload_guard.uploadAccompanyingText('));
  });
}
