import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_private_chat.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_saved_item_view.dart';

void main() {
  const older = ZkLocalChatRecord(
    kind: ZkLocalChatKind.savedItem,
    id: '41',
    title: 'Synthetic recovery note',
    itemType: 'note',
    searchText: 'note',
    legacyProofRequired: true,
  );

  test('an exact follow-up opens only the local saved-item selection', () {
    final found = ZkLocalChatRouter.resolve(
      prompt: 'find my recovery note',
      savedItems: const [older],
      files: const [],
    );
    expect(found.selection, older);
    expect(ZkPrivateChatSavedItemView.shouldOpen(found, enabled: true), false);
    final followUp = ZkLocalChatRouter.resolve(
      prompt: 'show it',
      savedItems: const [older],
      files: const [],
      previousSelection: found.selection,
    );
    expect(followUp.maySendToGeneralAi, false);
    expect(
      ZkPrivateChatSavedItemView.shouldOpen(followUp, enabled: true),
      true,
    );
    expect(
      ZkPrivateChatSavedItemView.shouldOpen(followUp, enabled: false),
      false,
    );
    expect(
      ZkPrivateChatSavedItemView.shouldOpen(
        const ZkLocalChatResult(ZkLocalChatDisposition.general),
        enabled: true,
      ),
      false,
    );
  });

  test('older selection uses only the injected owner-proof reader', () async {
    var oldReads = 0;
    var v2Reads = 0;
    final view = await ZkPrivateChatSavedItemView.read(
      selection: older,
      legacyProofOffered: true,
      accessIsCurrent: () => true,
      readLegacy: (id) async {
        oldReads++;
        expect(id, 41);
        return {
          'id': 41,
          'service': 'Synthetic recovery note',
          'item_type': 'note',
          'storage_engine': 'legacy_compatibility',
          'fields': {'text': 'synthetic local-only value'},
        };
      },
      readV2: (_, __, ___) async {
        v2Reads++;
        throw StateError('V2 reader must not be used');
      },
    );
    expect(oldReads, 1);
    expect(v2Reads, 0);
    expect(view.id, 41);
    expect(view.fields['text'], 'synthetic local-only value');
  });

  test('missing owner-proof offer never invokes either reader', () async {
    var reads = 0;
    await expectLater(
      ZkPrivateChatSavedItemView.read(
        selection: older,
        legacyProofOffered: false,
        accessIsCurrent: () => true,
        readLegacy: (_) async {
          reads++;
          return {};
        },
        readV2: (_, __, ___) async {
          reads++;
          return {};
        },
      ),
      throwsStateError,
    );
    expect(reads, 0);
  });

  test('changed identity cannot reveal a different saved item', () async {
    var reads = 0;
    await expectLater(
      ZkPrivateChatSavedItemView.read(
        selection: older,
        legacyProofOffered: true,
        accessIsCurrent: () => true,
        readLegacy: (_) async {
          reads++;
          return {
            'id': 41,
            'service': 'Another note',
            'item_type': 'note',
            'storage_engine': 'legacy_compatibility',
            'fields': {'text': 'should remain hidden'},
          };
        },
        readV2: (_, __, ___) async => {},
      ),
      throwsFormatException,
    );
    expect(reads, 1);
  });

  test('V2 uses exact MVK reader and rejects a stale session', () async {
    const v2 = ZkLocalChatRecord(
      kind: ZkLocalChatKind.savedItem,
      id: '9',
      title: 'Synthetic login',
      itemType: 'login',
    );
    var current = true;
    var legacyReads = 0;
    await expectLater(
      ZkPrivateChatSavedItemView.read(
        selection: v2,
        legacyProofOffered: false,
        accessIsCurrent: () => current,
        readLegacy: (_) async {
          legacyReads++;
          return {};
        },
        readV2: (id, title, itemType) async {
          expect((id, title, itemType), (9, 'Synthetic login', 'login'));
          current = false;
          return {
            'id': 9,
            'service': 'Synthetic login',
            'item_type': 'login',
            'storage_engine': 'ciphertext',
            'fields': {'password': 'must not reveal after lock'},
          };
        },
      ),
      throwsStateError,
    );
    expect(legacyReads, 0);
  });

  test('chat reveal wiring never calls the PIN-bearing item or chat route',
      () async {
    final source = await File('lib/main.dart').readAsString();
    final start = source.indexOf('Future<void> _openZkChatSelectedSavedItem(');
    final end =
        source.indexOf('Future<void> _sendZkPrivateAttachments(', start);
    expect(start, isNonNegative);
    expect(end, greaterThan(start));
    final body = source.substring(start, end);
    expect(body, contains('getZkVaultSecureItemOnly('));
    expect(body, contains('_readLegacyZkSavedItem(app, id)'));
    expect(body, isNot(contains('getVaultSecureItem(')));
    expect(body, isNot(contains('currentPinOrThrow(')));
    expect(body, isNot(contains('/chat')));
  });
}
