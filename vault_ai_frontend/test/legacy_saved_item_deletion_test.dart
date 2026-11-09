import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_saved_item_deletion.dart';

void main() {
  test(
    'staged legacy copy takes proof-bound deletion, never V2-only delete',
    () {
      expect(
        savedItemDeleteStorage(<String, dynamic>{
          'is_legacy': true,
          'has_v2_payload': true,
        }),
        SavedItemDeleteStorage.legacy,
      );
      expect(
        savedItemDeleteStorage(<String, dynamic>{
          'is_legacy': true,
          'has_v2_payload': false,
        }),
        SavedItemDeleteStorage.legacy,
      );
      expect(
        savedItemDeleteStorage(<String, dynamic>{
          'is_legacy': false,
          'has_v2_payload': true,
        }),
        SavedItemDeleteStorage.ciphertext,
      );
      expect(
        () => savedItemDeleteStorage(<String, dynamic>{}),
        throwsStateError,
      );
    },
  );

  test('staged deletion requires encrypted and legacy labels to agree', () {
    final source = <String, dynamic>{
      'item_type': 'login',
      'service': 'Synthetic',
      'item_type_ciphertext': 'synthetic-type-cipher',
    };
    final listing = <String, dynamic>{...source};
    expect(
      () => requireStagedLegacyDeleteIdentity(
        source: source,
        listing: listing,
        itemType: 'login',
        service: 'Synthetic',
      ),
      returnsNormally,
    );
    for (final mismatch in <Map<String, dynamic>>[
      {...source, 'service': 'Different'},
      {...source, 'item_type_ciphertext': null},
    ]) {
      expect(
        () => requireStagedLegacyDeleteIdentity(
          source: mismatch,
          listing: listing,
          itemType: 'login',
          service: 'Synthetic',
        ),
        throwsFormatException,
      );
    }
    expect(
      () => requireStagedLegacyDeleteIdentity(
        source: source,
        listing: {...listing, 'item_type': 'Different'},
        itemType: 'login',
        service: 'Synthetic',
      ),
      throwsFormatException,
    );
  });
  final source = LegacySavedItemDeleteSource(
    itemId: 17,
    itemType: 'login',
    service: 'Synthetic Login',
    sourceSnapshot: List.filled(43, 'A').join(),
    deleteSnapshot: List.filled(43, 'B').join(),
  );

  test('confirmed deletion sends only snapshot and one-use proof', () async {
    final sent = <String, dynamic>{};
    var reads = 0;
    var proofs = 0;
    final deletion = LegacySavedItemDeletion(
      sourceReader: (id) async {
        reads++;
        expect(id, 17);
        return source;
      },
      proofProvider: () async {
        proofs++;
        return 'zk-proof-token';
      },
      post: (path, body) async {
        expect(path, '/vault/items/legacy-ciphertext/17/delete');
        sent.addAll(body);
        return {'status': 'deleted', 'item_id': 17};
      },
      requireCurrentSession: () {},
    );
    await deletion.delete(
      itemId: 17,
      itemType: 'login',
      service: 'Synthetic Login',
      userConfirmed: true,
    );
    expect(reads, 1);
    expect(proofs, 1);
    expect(sent, {
      'source_snapshot': List.filled(43, 'A').join(),
      'delete_snapshot': List.filled(43, 'B').join(),
      'zk_proof_token': 'zk-proof-token',
      'confirm': true,
    });
    expect(sent.containsKey('pin'), false);
    expect(sent.containsKey('service'), false);
    expect(sent.containsKey('vault_name'), false);
  });

  test('cancel or changed identity makes no delete request', () async {
    var reads = 0;
    var proofs = 0;
    var posts = 0;
    final deletion = LegacySavedItemDeletion(
      sourceReader: (_) async {
        reads++;
        return source;
      },
      proofProvider: () async {
        proofs++;
        return 'zk-proof-token';
      },
      post: (_, __) async {
        posts++;
        return {};
      },
      requireCurrentSession: () {},
    );
    await expectLater(
      deletion.delete(
        itemId: 17,
        itemType: 'login',
        service: 'Synthetic Login',
        userConfirmed: false,
      ),
      throwsFormatException,
    );
    expect(reads, 0);
    await expectLater(
      deletion.delete(
        itemId: 17,
        itemType: 'login',
        service: 'Different Login',
        userConfirmed: true,
      ),
      throwsFormatException,
    );
    expect(reads, 1);
    expect(proofs, 0);
    expect(posts, 0);
  });

  test('older export without a delete snapshot fails closed before proof', () async {
    var proofs = 0;
    var posts = 0;
    final deletion = LegacySavedItemDeletion(
      sourceReader: (_) async => LegacySavedItemDeleteSource(
        itemId: 17, itemType: 'login', service: 'Synthetic Login',
        sourceSnapshot: List.filled(43, 'A').join(), deleteSnapshot: '',
      ),
      proofProvider: () async { proofs++; return 'zk-proof-token'; },
      post: (_, __) async { posts++; return {}; },
      requireCurrentSession: () {},
    );
    await expectLater(
      deletion.delete(itemId: 17, itemType: 'login',
          service: 'Synthetic Login', userConfirmed: true),
      throwsFormatException,
    );
    expect(proofs, 0);
    expect(posts, 0);
  });
}
