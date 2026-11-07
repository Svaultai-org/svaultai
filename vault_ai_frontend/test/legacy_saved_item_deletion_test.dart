import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/legacy_saved_item_deletion.dart';

void main() {
  final source = LegacySavedItemDeleteSource(
    itemId: 17,
    itemType: 'login',
    service: 'Synthetic Login',
    sourceSnapshot: List.filled(43, 'A').join(),
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
}
