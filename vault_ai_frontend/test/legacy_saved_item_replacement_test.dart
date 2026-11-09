import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/legacy_saved_item_replacement.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

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
          expect(jsonEncode(body), isNot(contains('Old title')));
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
            'renamed': false,
            'service_ciphertext': null,
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

  test(
    'verified staged V2 copy can be edited without exposing PIN or fields',
    () async {
      final oldCiphertext = await codec.encodeLegacyItem(<String, dynamic>{
        'category': 'login',
        'title': 'Old title',
        'fields': <String, dynamic>{
          'username': 'synthetic-user',
          'password': 'synthetic-secret',
        },
        'item_id': 42,
      });
      final v2 = await codec.stageItem(
        itemId: 42,
        itemType: 'login',
        service: 'Old title',
        legacyCiphertext: oldCiphertext,
      );
      final stagedSnapshot = List<String>.filled(43, 'b').join();
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
        sourceReader: (_) async => LegacySavedItemSource(
          itemId: 42,
          itemType: 'login',
          service: 'Old title',
          sourceSnapshot: snapshot,
          ciphertext: oldCiphertext,
          stagedSourceSnapshot: stagedSnapshot,
          stagedItemTypeCiphertext: v2.itemTypeCiphertext,
          stagedServiceCiphertext: v2.serviceCiphertext,
          stagedPayloadCiphertext: v2.payloadCiphertext,
        ),
        post: (path, body) async {
          final wire = jsonEncode(body);
          expect(wire, isNot(contains('synthetic-secret')));
          expect(wire, isNot(contains('synthetic-user')));
          expect(wire, isNot(contains('Old title')));
          if (path.endsWith('/stage')) {
            expect(body['staged_source_snapshot'], stagedSnapshot);
            expect(body['client_verified_staged_copy'], true);
            expect(body.containsKey('pin'), false);
            candidate = body['candidate_encrypted_data'] as String;
            return <String, dynamic>{'item_id': 42, 'staged': true};
          }
          expect(path, endsWith('/promote'));
          expect(body['client_verified_exact_content'], true);
          expect(body['zk_proof_token'], startsWith('p1.'));
          return <String, dynamic>{
            'id': 42,
            'item_id': 42,
            'item_type': 'login',
            'service': 'Old title',
            'updated': true,
            'created': false,
            'renamed': false,
            'service_ciphertext': null,
          };
        },
        get: (path) async {
          expect(path, endsWith('/staged'));
          return <String, dynamic>{
            'item_id': 42,
            'source_snapshot': snapshot,
            'candidate_encrypted_data': candidate,
            'readback_receipt': 'receipt',
          };
        },
      );
      final result = await replacement.replace(
        itemId: 42,
        itemType: 'login',
        oldService: 'Old title',
        fields: <String, dynamic>{'username': 'updated-user'},
      );
      expect(result['updated'], true);
      expect(proofCalls, 1);
    },
  );

  test(
    'divergent staged V2 copy stops before network write or proof',
    () async {
      final oldCiphertext = await codec.encodeLegacyItem(<String, dynamic>{
        'category': 'login',
        'title': 'Old title',
        'fields': <String, dynamic>{'username': 'old-user'},
        'item_id': 42,
      });
      final divergent = await codec.encodeLegacyItem(<String, dynamic>{
        'category': 'login',
        'title': 'Old title',
        'fields': <String, dynamic>{'username': 'different-user'},
        'item_id': 42,
      });
      final v2 = await codec.stageItem(
        itemId: 42,
        itemType: 'login',
        service: 'Old title',
        legacyCiphertext: divergent,
      );
      var networkCalls = 0;
      final replacement = LegacySavedItemReplacement(
        legacyKey: legacyKey,
        mvk: mvk,
        requireCurrentSession: () {},
        proofProvider: () async {
          networkCalls++;
          return 'unused';
        },
        sourceReader: (_) async => LegacySavedItemSource(
          itemId: 42,
          itemType: 'login',
          service: 'Old title',
          sourceSnapshot: snapshot,
          ciphertext: oldCiphertext,
          stagedSourceSnapshot: List<String>.filled(43, 'b').join(),
          stagedItemTypeCiphertext: v2.itemTypeCiphertext,
          stagedServiceCiphertext: v2.serviceCiphertext,
          stagedPayloadCiphertext: v2.payloadCiphertext,
        ),
        post: (_, __) async {
          networkCalls++;
          return <String, dynamic>{};
        },
        get: (_) async {
          networkCalls++;
          return <String, dynamic>{};
        },
      );
      await expectLater(
        replacement.replace(
          itemId: 42,
          itemType: 'login',
          oldService: 'Old title',
          fields: <String, dynamic>{'username': 'updated-user'},
        ),
        throwsFormatException,
      );
      expect(networkCalls, 0);
    },
  );

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

  test('rename is rejected before any export or request', () async {
    var networkCalls = 0;
    final replacement = LegacySavedItemReplacement(
      legacyKey: legacyKey,
      mvk: mvk,
      requireCurrentSession: () {},
      proofProvider: () async {
        networkCalls++;
        return 'proof';
      },
      sourceReader: (_) async {
        networkCalls++;
        throw StateError('Must not read source');
      },
      post: (_, __) async {
        networkCalls++;
        throw StateError('Must not post');
      },
      get: (_) async {
        networkCalls++;
        throw StateError('Must not get');
      },
    );
    await expectLater(
      replacement.replace(
        itemId: 42,
        itemType: 'login',
        oldService: 'Old title',
        newService: 'New title',
        fields: <String, dynamic>{'username': 'new'},
      ),
      throwsStateError,
    );
    expect(networkCalls, 0);
  });

  test(
    'flagged legacy rename sends only encrypted title and keeps old label',
    () async {
      final oldCiphertext = await codec.encodeLegacyItem(<String, dynamic>{
        'category': 'login',
        'title': 'Old title',
        'fields': <String, dynamic>{'username': 'owner'},
        'item_id': 42,
      });
      String? candidate;
      String? encryptedTitle;
      String? titleHash;
      var proofCalls = 0;
      var promoted = false;
      final replacement = LegacySavedItemReplacement(
        legacyKey: legacyKey,
        mvk: mvk,
        allowEncryptedRename: true,
        requireCurrentSession: () {},
        proofProvider: () async {
          proofCalls++;
          return 'p1.1.${List<String>.filled(32, 'x').join()}.'
              '${List<String>.filled(43, 'y').join()}';
        },
        sourceReader: (_) async => LegacySavedItemSource(
          itemId: 42,
          itemType: 'login',
          service: 'Old title',
          sourceSnapshot: snapshot,
          ciphertext: oldCiphertext,
        ),
        post: (path, body) async {
          expect(jsonEncode(body), isNot(contains('New title')));
          expect(jsonEncode(body), isNot(contains('Old title')));
          expect(jsonEncode(body), isNot(contains('owner')));
          if (path.endsWith('/stage')) {
            expect(proofCalls, 0);
            candidate = body['candidate_encrypted_data'] as String;
            encryptedTitle = body['new_service_ciphertext'] as String;
            titleHash = body['new_title_lookup_hash'] as String;
            expect(b64urlDecode(titleHash!), hasLength(32));
            expect(
              (await codec.decodeLegacyItem(candidate!))['title'],
              'New title',
            );
            final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
            expect(
              utf8.decode(
                await aesGcmUnwrap(metadataKey, b64urlDecode(encryptedTitle!)),
              ),
              'New title',
            );
            return <String, dynamic>{'item_id': 42, 'staged': true};
          }
          expect(path, endsWith('/promote'));
          expect(body['zk_proof_token'], startsWith('p1.'));
          expect(body['client_verified_exact_content'], true);
          promoted = true;
          return <String, dynamic>{
            'id': 42,
            'item_id': 42,
            'item_type': 'login',
            'service': 'Old title',
            'updated': true,
            'renamed': true,
            'service_ciphertext': encryptedTitle,
          };
        },
        get: (path) async {
          if (path.endsWith('/staged')) {
            expect(promoted, false);
            return <String, dynamic>{
              'item_id': 42,
              'source_snapshot': snapshot,
              'candidate_encrypted_data': candidate,
              'new_service': null,
              'new_service_ciphertext': encryptedTitle,
              'new_title_lookup_hash': titleHash,
              'readback_receipt': 'receipt',
            };
          }
          if (path == '/vault/items/metadata?after_item_id=0&limit=100') {
            expect(promoted, false);
            return <String, dynamic>{
              'records': <Map<String, dynamic>>[
                <String, dynamic>{
                  'item_id': 42,
                  'item_type': 'login',
                  'service': 'Old title',
                  'is_legacy': true,
                },
              ],
              'has_more': false,
            };
          }
          expect(path, '/vault/items/metadata?after_item_id=41&limit=1');
          expect(promoted, true);
          return <String, dynamic>{
            'records': <Map<String, dynamic>>[
              <String, dynamic>{
                'item_id': 42,
                'item_type': 'login',
                'service_ciphertext': encryptedTitle,
                'is_legacy': true,
              },
            ],
          };
        },
      );
      final result = await replacement.replace(
        itemId: 42,
        itemType: 'login',
        oldService: 'Old title',
        newService: 'New title',
        fields: <String, dynamic>{'username': 'owner'},
      );
      expect(result['renamed'], true);
      expect(proofCalls, 1);
    },
  );

  test('rename duplicate is rejected before staging or proof', () async {
    final oldCiphertext = await codec.encodeLegacyItem(<String, dynamic>{
      'category': 'login',
      'title': 'Old title',
      'fields': <String, dynamic>{'username': 'owner'},
      'item_id': 42,
    });
    var proofCalls = 0;
    var posts = 0;
    final replacement = LegacySavedItemReplacement(
      legacyKey: legacyKey,
      mvk: mvk,
      allowEncryptedRename: true,
      requireCurrentSession: () {},
      proofProvider: () async {
        proofCalls++;
        throw StateError('Must not request proof');
      },
      sourceReader: (_) async => LegacySavedItemSource(
        itemId: 42,
        itemType: 'login',
        service: 'Old title',
        sourceSnapshot: snapshot,
        ciphertext: oldCiphertext,
      ),
      post: (_, __) async {
        posts++;
        throw StateError('Must not post');
      },
      get: (_) async => <String, dynamic>{
        'records': <Map<String, dynamic>>[
          <String, dynamic>{
            'item_id': 42,
            'item_type': 'login',
            'service': 'Old title',
            'is_legacy': true,
          },
          <String, dynamic>{
            'item_id': 43,
            'item_type': 'login',
            'service': 'New title',
            'is_legacy': true,
          },
        ],
        'has_more': false,
      },
    );
    await expectLater(
      replacement.replace(
        itemId: 42,
        itemType: 'login',
        oldService: 'Old title',
        newService: ' New  title ',
      ),
      throwsStateError,
    );
    expect(proofCalls, 0);
    expect(posts, 0);
  });

  test(
    'field edit after rename accepts the old-client service response',
    () async {
      final oldCiphertext = await codec.encodeLegacyItem(<String, dynamic>{
        'category': 'login',
        'title': 'Private title',
        'fields': <String, dynamic>{'username': 'old'},
        'item_id': 42,
      });
      String? candidate;
      final replacement = LegacySavedItemReplacement(
        legacyKey: legacyKey,
        mvk: mvk,
        allowEncryptedRename: true,
        requireCurrentSession: () {},
        proofProvider: () async =>
            'p1.1.${List<String>.filled(32, 'x').join()}.'
            '${List<String>.filled(43, 'y').join()}',
        sourceReader: (_) async => LegacySavedItemSource(
          itemId: 42,
          itemType: 'login',
          service: 'Private title',
          sourceSnapshot: snapshot,
          ciphertext: oldCiphertext,
        ),
        post: (path, body) async {
          expect(body, isNot(contains('new_service_ciphertext')));
          expect(body, isNot(contains('new_title_lookup_hash')));
          if (path.endsWith('/stage')) {
            candidate = body['candidate_encrypted_data'] as String;
            return <String, dynamic>{'staged': true};
          }
          return <String, dynamic>{
            'id': 42,
            'item_id': 42,
            'item_type': 'login',
            'service': 'Old client title',
            'updated': true,
            'renamed': false,
            'service_ciphertext': 'preserved-on-server',
          };
        },
        get: (_) async => <String, dynamic>{
          'item_id': 42,
          'source_snapshot': snapshot,
          'candidate_encrypted_data': candidate,
          'new_service_ciphertext': null,
          'new_title_lookup_hash': null,
          'readback_receipt': 'receipt',
        },
      );
      final result = await replacement.replace(
        itemId: 42,
        itemType: 'login',
        oldService: 'Private title',
        fields: <String, dynamic>{'username': 'new'},
      );
      expect(result['updated'], true);
      expect(result['service'], 'Old client title');
    },
  );
}
