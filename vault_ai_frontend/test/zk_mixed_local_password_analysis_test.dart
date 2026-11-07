import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_export_client.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/zk_local_password_analysis.dart';

Future<String> _legacyEncrypt(Map<String, dynamic> record) async {
  final box = await AesGcm.with256bits().encrypt(
    utf8.encode(jsonEncode(record)),
    secretKey: SecretKey(List<int>.filled(32, 51)),
    nonce: List<int>.generate(12, (i) => i + 1),
  );
  return base64.encode(<int>[...box.nonce, ...box.cipherText, ...box.mac.bytes]);
}

class _SyntheticExport extends LegacyCiphertextExportClient {
  final String ciphertext;
  bool cleared = false;
  bool missing = false;
  bool extra = false;
  void Function()? onList;

  _SyntheticExport(this.ciphertext)
    : super(
        post: (_, __) async => <String, dynamic>{},
        proofProvider: () async => 'synthetic-proof',
      );

  @override
  Future<List<Map<String, dynamic>>> listItemsBounded({required int maxRecords}) async {
    onList?.call();
    return missing
      ? <Map<String, dynamic>>[]
      : <Map<String, dynamic>>[
          <String, dynamic>{
            'item_id': 7,
            'item_type': 'login',
            'service': 'Synthetic site',
            'ciphertext_chars': ciphertext.length,
          },
          if (extra)
            <String, dynamic>{
              'item_id': 8,
              'item_type': 'login',
              'service': 'Unexpected site',
              'ciphertext_chars': ciphertext.length,
            },
        ];
  }

  @override
  Future<LegacyCiphertextSource> readItemSource({
    required int itemId,
    required int ciphertextChars,
  }) async => LegacyCiphertextSource(
    ciphertext: ciphertext,
    sourceSnapshot: 'A' * 43,
    sourceMetadata: <String, dynamic>{
      'item_type': 'login',
      'service': 'Synthetic site',
    },
  );

  @override
  void clearGrant() {
    cleared = true;
    super.clearGrant();
  }
}

void main() {
  late LegacyCiphertextMigrationCodec codec;
  late _SyntheticExport export;
  late List<Map<String, dynamic>> metadata;

  setUp(() async {
    codec = LegacyCiphertextMigrationCodec(
      legacyKey: SecretKey(List<int>.filled(32, 51)),
      mvk: SecretKey(List<int>.filled(32, 52)),
    );
    export = _SyntheticExport(
      await _legacyEncrypt(<String, dynamic>{
        'category': 'login',
        'title': 'Synthetic site',
        'fields': <String, dynamic>{'password': 'local-password-example-123'},
      }),
    );
    metadata = <Map<String, dynamic>>[
      <String, dynamic>{
        'item_id': 7,
        'is_legacy': true,
        'v2_ready': false,
        'has_v2_payload': true, // staged, but not the active reader
      },
    ];
  });

  Future<({
    LegacyCiphertextExportClient export,
    LegacyCiphertextMigrationCodec codec,
    bool Function() stillCurrent,
    void Function() close,
  })> createSource() async => (
        export: export,
        codec: codec,
        stillCurrent: () => true,
        close: export.clearGrant,
      );

  test(
    'analyzes an older password locally, including a staged V2 copy',
    () async {
      final result = await loadAndAnalyzeMixedZkPasswords(
        fetchMetadata: () async => metadata,
        fetchV2Items: () async => <String, dynamic>{
          'items': [
            <String, dynamic>{'id': 7, 'storage_engine': 'ciphertext'},
          ],
        },
      createLegacySource: createSource,
        stillCurrent: () => true,
      );
      expect(result.analyzedCount, 1);
      expect(
        result.toResultMap().toString(),
        isNot(contains('local-password-example-123')),
      );
      expect(export.cleared, isTrue);
    },
  );

  test('missing older source refuses a partial all-clear', () async {
    export.missing = true;
    await expectLater(
      loadAndAnalyzeMixedZkPasswords(
        fetchMetadata: () async => metadata,
        fetchV2Items: () async => <String, dynamic>{'items': []},
        createLegacySource: createSource,
        stillCurrent: () => true,
      ),
      throwsA(isA<ZkPasswordAnalysisIncomplete>()),
    );
    expect(export.cleared, isTrue);
  });

  test('unaccounted older source refuses a partial all-clear', () async {
    export.extra = true;
    await expectLater(
      loadAndAnalyzeMixedZkPasswords(
        fetchMetadata: () async => metadata,
        fetchV2Items: () async => <String, dynamic>{'items': []},
        createLegacySource: createSource,
        stillCurrent: () => true,
      ),
      throwsA(isA<ZkPasswordAnalysisIncomplete>()),
    );
    expect(export.cleared, isTrue);
  });

  test('session loss after export refuses a result', () async {
    var current = true;
    export.onList = () => current = false;
    await expectLater(
      loadAndAnalyzeMixedZkPasswords(
        fetchMetadata: () async => metadata,
        fetchV2Items: () async => <String, dynamic>{'items': []},
        createLegacySource: createSource,
        stillCurrent: () => current,
      ),
      throwsStateError,
    );
    expect(export.cleared, isTrue);
  });

  test('one-action key loss after export refuses a result', () async {
    var actionCurrent = true;
    export.onList = () => actionCurrent = false;
    await expectLater(
      loadAndAnalyzeMixedZkPasswords(
        fetchMetadata: () async => metadata,
        fetchV2Items: () async => <String, dynamic>{'items': []},
        createLegacySource: () async => (
          export: export,
          codec: codec,
          stillCurrent: () => actionCurrent,
          close: export.clearGrant,
        ),
        stillCurrent: () => true,
      ),
      throwsStateError,
    );
    expect(export.cleared, isTrue);
  });

  test('a fully private vault never asks for an older key or proof', () async {
    var requestedOlderKey = false;
    final result = await loadAndAnalyzeMixedZkPasswords(
      fetchMetadata: () async => <Map<String, dynamic>>[
        <String, dynamic>{
          'item_id': 9,
          'is_legacy': false,
          'has_v2_payload': true,
        },
      ],
      fetchV2Items: () async => <String, dynamic>{'items': [
        <String, dynamic>{
          'id': 9,
          'storage_engine': 'ciphertext',
          'item_type': 'login',
          'fields': <String, dynamic>{'password': 'synthetic-private-123'},
        },
      ]},
      createLegacySource: () async {
        requestedOlderKey = true;
        throw StateError('Older key should not be requested');
      },
      stillCurrent: () => true,
    );
    expect(result.analyzedCount, 1);
    expect(requestedOlderKey, isFalse);
  });

  test('ordinary V2-only analysis still rejects older rows', () {
    expect(
      () => analyzeZkPasswords(metadata: metadata, decryptedItems: const []),
      throwsA(isA<ZkPasswordAnalysisIncomplete>()),
    );
  });
}
