import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_saved_item_replacement.dart';

void main() {
  final legacyKey = SecretKey(List<int>.filled(32, 7));
  final mvk = SecretKey(List<int>.filled(32, 8));
  final codec = LegacyCiphertextMigrationCodec(legacyKey: legacyKey, mvk: mvk);
  final snapshot = List<String>.filled(43, 'a').join();

  test(
    'edits locally, verifies staged bytes, then promotes with OPAQUE proof',
    () async {
      final old = <String, dynamic>{
        'category': 'login',
        'title': 'Old title',
        'fields': <String, dynamic>{
          'username': 'old-user',
          'password': 'preserved-secret',
        },
        'notes': 'keep note',
        'item_id': 42,
        'schema': 3,
      };
      final oldCiphertext = await codec.encodeLegacyItem(old);
      final requests = <String>[];
      String? candidate;
      var proofCalls = 0;
      final replacement = LegacySavedItemReplacement(
        legacyKey: legacyKey,
        mvk: mvk,
        requireCurrentSession: () {},
        proofProvider: () async {
          proofCalls++;
          return 'p1.1.${List<String>.filled(32, 'x').join()}.'
              '${List<String>.filled(43, 'y').join()}';
        },
        sourceReader: (id) async {
          expect(id, 42);
          return LegacySavedItemSource(
            itemId: 42,
            itemType: 'login',
            service: 'Old title',
            sourceSnapshot: snapshot,
            ciphertext: oldCiphertext,
          );
        },
        post: (path, body) async {
          requests.add(path);
          expect(jsonEncode(body), isNot(contains('preserved-secret')));
          expect(jsonEncode(body), isNot(contains('synthetic-pin-marker')));
          if (path.endsWith('/stage')) {
            expect(body['source_snapshot'], snapshot);
            expect(body.containsKey('new_service'), isFalse);
            candidate = body['candidate_encrypted_data'] as String;
            final decoded = await codec.decodeLegacyItem(candidate!);
            expect(decoded['title'], 'Old title');
            expect(decoded['notes'], 'keep note');
            expect(decoded['schema'], 3);
            expect(decoded['fields'], <String, dynamic>{
              'username': 'new-user',
              'password': 'preserved-secret',
            });
            expect(proofCalls, 0);
            return <String, dynamic>{
              'item_id': 42,
              'staged': true,
              'active_item_unchanged': true,
            };
          }
          expect(path, endsWith('/promote'));
          expect(body['client_verified_exact_content'], true);
          expect(body['source_snapshot'], snapshot);
          expect(body['readback_receipt'], 'receipt');
          expect(body['zk_proof_token'], startsWith('p1.'));
          expect(proofCalls, 1);
          return <String, dynamic>{
            'id': 42,
            'item_id': 42,
            'item_type': 'login',
            'service': 'Old title',
            'updated': true,
            'created': false,
          };
        },
        get: (path) async {
          requests.add(path);
          expect(path, endsWith('/staged'));
          expect(proofCalls, 0);
          return <String, dynamic>{
            'item_id': 42,
            'source_snapshot': snapshot,
            'candidate_encrypted_data': candidate,
            'new_service': null,
            'readback_receipt': 'receipt',
          };
        },
      );
      final result = await replacement.replace(
        itemId: 42,
        itemType: 'login',
        oldService: 'Old title',
        fields: <String, dynamic>{'username': 'new-user'},
      );
      expect(result['updated'], true);
      expect(requests, <String>[
        '/vault/items/legacy-ciphertext/42/replace/stage',
        '/vault/items/legacy-ciphertext/42/replace/staged',
        '/vault/items/legacy-ciphertext/42/replace/promote',
      ]);
    },
  );

  test('rename refuses before staging a candidate', () async {
    var requestedSource = false;
    final replacement = LegacySavedItemReplacement(
      legacyKey: legacyKey,
      mvk: mvk,
      requireCurrentSession: () {},
      proofProvider: () async => 'unused',
      sourceReader: (_) async {
        requestedSource = true;
        throw StateError('must not read source');
      },
      post: (_, __) async => throw StateError('must not stage'),
      get: (_) async => throw StateError('must not read staged candidate'),
    );
    await expectLater(
      replacement.replace(
        itemId: 42,
        itemType: 'login',
        oldService: 'Old title',
        newService: 'New title',
        fields: <String, dynamic>{'username': 'new-user'},
      ),
      throwsStateError,
    );
    expect(requestedSource, isFalse);
  });

  test('mismatched staged bytes never request a promotion proof', () async {
    final oldCiphertext = await codec.encodeLegacyItem(<String, dynamic>{
      'category': 'login',
      'title': 'Old title',
      'fields': <String, dynamic>{'username': 'old-user'},
      'item_id': 42,
    });
    var proofCalls = 0;
    var promotes = 0;
    final replacement = LegacySavedItemReplacement(
      legacyKey: legacyKey,
      mvk: mvk,
      requireCurrentSession: () {},
      proofProvider: () async {
        proofCalls++;
        return 'proof';
      },
      sourceReader: (_) async => LegacySavedItemSource(
        itemId: 42,
        itemType: 'login',
        service: 'Old title',
        sourceSnapshot: snapshot,
        ciphertext: oldCiphertext,
      ),
      post: (path, body) async {
        if (path.endsWith('/promote')) promotes++;
        return <String, dynamic>{'staged': true};
      },
      get: (_) async => <String, dynamic>{
        'item_id': 42,
        'source_snapshot': snapshot,
        'candidate_encrypted_data': oldCiphertext,
        'new_service': null,
        'readback_receipt': 'receipt',
      },
    );
    await expectLater(
      replacement.replace(
        itemId: 42,
        itemType: 'login',
        oldService: 'Old title',
        fields: <String, dynamic>{'username': 'new-user'},
      ),
      throwsFormatException,
    );
    expect(proofCalls, 0);
    expect(promotes, 0);
  });
}
