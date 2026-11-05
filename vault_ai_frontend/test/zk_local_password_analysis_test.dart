import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/zk_local_password_analysis.dart';

Map<String, dynamic> meta(int id, {bool legacy = false}) => {
      'item_id': id,
      'is_legacy': legacy,
      'has_v2_payload': true,
    };

Map<String, dynamic> item(int id, String password) => {
      'id': id,
      'storage_engine': 'ciphertext',
      'item_type': 'login',
      'fields': {'password': password},
    };

void main() {
  test('analyzes MVK V2 items locally and returns counts only', () {
    final result = analyzeZkPasswords(
      metadata: [meta(1), meta(2), meta(3)],
      decryptedItems: [
        item(1, 'synthetic-reused-password'),
        item(2, 'synthetic-reused-password'),
        item(3, '123456'),
      ],
    );
    expect(result.analyzedCount, 3);
    expect(result.reusedGroups, 1);
    expect(result.weak, greaterThanOrEqualTo(1));
    final serialized = result.toResultMap().toString();
    expect(serialized, isNot(contains('synthetic-reused-password')));
    expect(serialized, isNot(contains('123456')));
    expect(result.toResultMap()['has_more'], false);
  });

  test('fails closed while any legacy or staged item remains', () {
    expect(
      () => analyzeZkPasswords(
        metadata: [meta(1), meta(2, legacy: true)],
        decryptedItems: [item(1, 'synthetic-one'), item(2, 'synthetic-two')],
      ),
      throwsA(isA<ZkPasswordAnalysisIncomplete>()),
    );
    expect(
      () => analyzeZkPasswords(
        metadata: [
          meta(1),
          {...meta(2), 'has_v2_payload': false}
        ],
        decryptedItems: [item(1, 'synthetic-one'), item(2, 'synthetic-two')],
      ),
      throwsA(isA<ZkPasswordAnalysisIncomplete>()),
    );
  });

  test('fails closed on missing, duplicated, or malformed V2 readback', () {
    for (final items in <List<Map<String, dynamic>>>[
      [item(1, 'synthetic-one')],
      [item(1, 'synthetic-one'), item(1, 'synthetic-one')],
      [
        item(1, 'synthetic-one'),
        {
          'id': 2,
          'storage_engine': 'ciphertext',
          'item_type': 'login',
          'fields': {'password': 123},
        },
      ],
    ]) {
      expect(
        () => analyzeZkPasswords(
          metadata: [meta(1), meta(2)],
          decryptedItems: items,
        ),
        throwsA(isA<ZkPasswordAnalysisIncomplete>()),
      );
    }
  });

  test('non-login V2 records are covered but not scored', () {
    final result = analyzeZkPasswords(
      metadata: [meta(1), meta(2)],
      decryptedItems: [
        item(1, 'synthetic-one'),
        {'id': 2, 'storage_engine': 'ciphertext', 'item_type': 'note'},
      ],
    );
    expect(result.analyzedCount, 1);
  });

  test('credential records share reuse counts with login records', () {
    final credential = item(2, 'synthetic-shared-password')
      ..['item_type'] = 'credential';
    final result = analyzeZkPasswords(
      metadata: [meta(1), meta(2)],
      decryptedItems: [item(1, 'synthetic-shared-password'), credential],
    );
    expect(result.analyzedCount, 2);
    expect(result.reusedGroups, 1);
  });

  test('loader uses only private inventory and V2 item callbacks', () async {
    final calls = <String>[];
    final result = await loadAndAnalyzeZkPasswords(
      fetchMetadata: () async {
        calls.add('metadata');
        return [meta(1)];
      },
      fetchV2Items: () async {
        calls.add('v2');
        return {
          'items': [item(1, 'synthetic-password')]
        };
      },
      stillCurrent: () => true,
    );
    expect(calls, ['metadata', 'v2']);
    expect(result.analyzedCount, 1);
  });

  test('loader stops before V2 fetch when vault session changes', () async {
    var current = true;
    var v2Called = false;
    await expectLater(
      loadAndAnalyzeZkPasswords(
        fetchMetadata: () async {
          current = false;
          return [meta(1)];
        },
        fetchV2Items: () async {
          v2Called = true;
          return {
            'items': [item(1, 'synthetic-password')]
          };
        },
        stillCurrent: () => current,
      ),
      throwsStateError,
    );
    expect(v2Called, false);
  });
}
