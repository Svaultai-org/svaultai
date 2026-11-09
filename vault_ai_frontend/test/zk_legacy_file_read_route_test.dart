import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_legacy_file_read_route.dart';

void main() {
  ZkLegacyFileReadRoute route({
    bool availableV2 = false,
    bool requireReadyV2 = false,
    bool requirePinFreeChat = false,
    bool signedPrivateChatOffered = false,
    bool strictPinFreeFiles = false,
    bool signedLegacyDownloadOffered = false,
  }) =>
      selectZkLegacyFileReadRoute(
        availableV2: availableV2,
        requireReadyV2: requireReadyV2,
        requirePinFreeChat: requirePinFreeChat,
        signedPrivateChatOffered: signedPrivateChatOffered,
        strictPinFreeFiles: strictPinFreeFiles,
        signedLegacyDownloadOffered: signedLegacyDownloadOffered,
      );

  test('strict older-file read uses a signed owner-proof offer', () {
    expect(
      route(strictPinFreeFiles: true, signedLegacyDownloadOffered: true),
      ZkLegacyFileReadRoute.proofOnly,
    );
    expect(route(strictPinFreeFiles: true), ZkLegacyFileReadRoute.unavailable);
  });

  test('ordinary legacy access is unchanged without a signed offer', () {
    expect(route(), ZkLegacyFileReadRoute.notApplicable);
  });

  test('signed download offer selects proof reader with strict flag off', () {
    final token = base64Url
        .encode(<int>[3, 6, ...List<int>.filled(48, 7)])
        .replaceAll('=', '');
    expect(signedFileDownloadOfferedForToken(token), isTrue);
    expect(signedFileDownloadOfferedForToken('ordinary-legacy-token'), isFalse);
    expect(
      route(
        signedLegacyDownloadOffered: signedFileDownloadOfferedForToken(token),
      ),
      ZkLegacyFileReadRoute.proofOnly,
    );
    expect(
      route(availableV2: true, signedLegacyDownloadOffered: true),
      ZkLegacyFileReadRoute.notApplicable,
    );
  });

  test('private chat still requires a signed older-file proof offer', () {
    expect(
      route(requirePinFreeChat: true, signedLegacyDownloadOffered: true),
      ZkLegacyFileReadRoute.proofOnly,
    );
    expect(
      route(signedPrivateChatOffered: true),
      ZkLegacyFileReadRoute.unavailable,
    );
  });

  test('ready-V2-only request never opens an older file', () {
    expect(
      route(
        requireReadyV2: true,
        strictPinFreeFiles: true,
        signedLegacyDownloadOffered: true,
      ),
      ZkLegacyFileReadRoute.notApplicable,
    );
    expect(
      route(
        availableV2: true,
        strictPinFreeFiles: true,
        signedLegacyDownloadOffered: true,
      ),
      ZkLegacyFileReadRoute.notApplicable,
    );
  });

  test(
    'strict route is selected before the raw-PIN download fallback',
    () async {
      final source = await File('lib/main.dart').readAsString();
      final start = source.indexOf('_fetchVaultFile({');
      final end = source.indexOf('_fetchProofOnlyLegacyFile({', start);
      expect(start, isNonNegative);
      expect(end, greaterThan(start));
      final body = source.substring(start, end);
      final selection = body.indexOf('selectZkLegacyFileReadRoute(');
      final rawPin = body.indexOf(
        'final pin = await _VaultCrypto.currentPinOrThrow();',
      );
      expect(selection, isNonNegative);
      expect(rawPin, isNonNegative);
      expect(selection, lessThan(rawPin));
      expect(
        body,
        contains(
          'signedLegacyDownloadOffered: '
          'pinFreeLegacyDownloadOffered',
        ),
      );
      expect(body, contains('signedFileDownloadOfferedForToken(authToken)'));
      expect(body, contains('strictPinFreeFiles: pinFreeZkFile'));
      final proofEnd = source.indexOf('_fetchRelatedFilesEnvelope(', end);
      expect(proofEnd, greaterThan(end));
      final proofBody = source.substring(end, proofEnd);
      expect(proofBody, isNot(contains('downloadVaultFile(')));
      expect(proofBody, isNot(contains('getDownloadManifest(')));
      expect(proofBody, isNot(contains('currentPinOrThrow(')));
      expect(proofBody, contains('signedFileDownloadOfferedForToken(authToken)'));
    },
  );
}
