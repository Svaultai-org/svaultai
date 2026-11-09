import 'dart:io';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_private_upload_guard.dart';

void main() {
  final mvk = SecretKey(List<int>.filled(32, 17));

  test('signed file-create offer chooses V2; unoffered account keeps legacy',
      () {
    ZkFileUploadMode choose({
      bool offered = false,
      bool signedClient = true,
      bool strict = false,
      bool writer = true,
      bool reader = true,
      bool handle = true,
      bool activeMvk = true,
      bool files = true,
    }) =>
        selectZkFileUploadMode(
          hasFiles: files,
          signedCreateClientEnabled: signedClient,
          signedCreateOffered: offered,
          strictPinFreeFiles: strict,
          writerEnabled: writer,
          readerEnabled: reader,
          hasOpaqueHandle: handle,
          hasActiveMvk: activeMvk,
        );

    expect(choose(offered: true), ZkFileUploadMode.privateV2);
    expect(choose(offered: true, handle: false),
        ZkFileUploadMode.privateV2);
    expect(choose(), ZkFileUploadMode.legacy);
    expect(choose(activeMvk: false), ZkFileUploadMode.legacy);
    expect(choose(files: false, offered: true), ZkFileUploadMode.legacy);
    expect(choose(signedClient: false), ZkFileUploadMode.privateV2);
    expect(choose(strict: true), ZkFileUploadMode.privateV2);
    for (final writerReady in <bool>[false, true]) {
      expect(
        () => choose(offered: true, writer: writerReady, reader: !writerReady),
        throwsStateError,
      );
    }
    expect(() => choose(strict: true, writer: false), throwsStateError);
  });

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

  test('ordinary private send rejects a vanished or switched key', () {
    for (final missingOrSwitched in <({SecretKey? key, String? keyVaultId})>[
      (key: null, keyVaultId: null),
      (key: mvk, keyVaultId: 'vault-b'),
    ]) {
      expect(
          () => requirePrivateV2UploadBinding(
                activeMvk: missingOrSwitched.key,
                activeKeyVaultId: missingOrSwitched.keyVaultId,
                vaultId: 'vault-a',
              ),
          throwsStateError);
    }
    final binding = requirePrivateV2UploadBinding(
      activeMvk: mvk,
      activeKeyVaultId: 'vault-a',
      vaultId: 'vault-a',
    );
    expect(binding.mvk, same(mvk));
    expect(binding.vaultId, 'vault-a');
    // The shared uploader also rejects a key that vanishes after binding.
    expect(
        () => selectV2UploadKey(
              activeMvk: null,
              activeVaultId: null,
              writerEnabled: true,
              readerEnabled: true,
              requiredPrivateMvk: binding.mvk,
              requiredPrivateVaultId: binding.vaultId,
            ),
        throwsStateError);
  });

  test('ordinary attachment send preserves private upload binding', () {
    final source = File('lib/main.dart').readAsStringSync();
    final start = source.indexOf(
        'privateV2Upload = zk_upload_guard.selectZkFileUploadMode(');
    final end =
        source.indexOf('uploadedFileIds = uploadOutcome.uploadedIds;', start);
    expect(start, greaterThan(0));
    expect(end, greaterThan(start));
    final sendBody = source.substring(start, end);
    expect(sendBody, contains('requirePrivateV2UploadBinding('));
    expect(sendBody, contains('requiredPrivateMvk: privateBinding?.mvk'));
    expect(
        sendBody, contains('requiredPrivateVaultId: privateBinding?.vaultId'));
    expect(sendBody, contains('privateV2Upload ? null :'));
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
