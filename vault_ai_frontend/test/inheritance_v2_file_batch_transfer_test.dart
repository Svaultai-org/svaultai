import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/inheritance_v2_file_batch_transfer.dart';

Map<String, dynamic> page(List<Map<String, dynamic>> files,
        {String? next, String owner = 'synthetic-owner'}) =>
    <String, dynamic>{
      'owner_vault_id': owner,
      'beneficiary_link_id': 17,
      'files': files,
      'next_after_file_id': next,
    };

Map<String, dynamic> file(String id, {int version = 0}) => <String, dynamic>{
      'file_id': id,
      'total_bytes': 4,
      'chunk_size': 4,
      'chunk_count': 1,
      'name_version': version,
    };

void main() {
  test('copies a paged inventory once and rechecks before reporting', () async {
    final calls = <String>[];
    var pass = 0;
    final result = await copyReleasedV2FileInventory(
      linkId: 17,
      ownerVaultId: 'synthetic-owner',
      accessIsCurrent: () => true,
      fetchPage: (after) async {
        calls.add('list:$pass:$after');
        if (after.isEmpty) return page([file('a')], next: 'a');
        pass++;
        return page([file('b')]);
      },
      expectedTargetFileId: (id) async => 'beneficiary-$id',
      copyFile: (id) async {
        calls.add('copy:$id');
        return {'file_id': 'beneficiary-$id', 'status': 'published'};
      },
    );
    expect(result.copiedFiles, 2);
    expect(result.copiedBytes, 8);
    expect(calls, [
      'list:0:',
      'list:0:a',
      'copy:a',
      'copy:b',
      'list:1:',
      'list:1:a',
    ]);
  });

  test('late owner rename prevents a batch-complete result', () async {
    var renamed = false;
    var copies = 0;
    await expectLater(
      copyReleasedV2FileInventory(
        linkId: 17,
        ownerVaultId: 'synthetic-owner',
        accessIsCurrent: () => true,
        fetchPage: (_) async => page([file('a', version: renamed ? 1 : 0)]),
        expectedTargetFileId: (id) async => 'beneficiary-$id',
        copyFile: (_) async {
          copies++;
          renamed = true;
          return {'file_id': 'beneficiary-a', 'status': 'published'};
        },
      ),
      throwsStateError,
    );
    expect(copies, 1);
  });

  test('bad source scope or page order stops before target writes', () async {
    for (final badPage in [
      page([file('a')], owner: 'another-owner'),
      page([file('b'), file('a')]),
      page([file('a')], next: 'wrong-cursor'),
    ]) {
      var copies = 0;
      await expectLater(
        copyReleasedV2FileInventory(
          linkId: 17,
          ownerVaultId: 'synthetic-owner',
          accessIsCurrent: () => true,
          fetchPage: (_) async => badPage,
          expectedTargetFileId: (id) async => 'target-$id',
          copyFile: (_) async {
            copies++;
            return {'file_id': 'target', 'status': 'published'};
          },
        ),
        throwsFormatException,
      );
      expect(copies, 0);
    }
  });

  test('revoked access or a copy error never reports completion', () async {
    var active = true;
    var copies = 0;
    await expectLater(
      copyReleasedV2FileInventory(
        linkId: 17,
        ownerVaultId: 'synthetic-owner',
        accessIsCurrent: () => active,
        fetchPage: (_) async => page([file('a'), file('b')]),
        expectedTargetFileId: (id) async => 'target-$id',
        copyFile: (id) async {
          copies++;
          if (id == 'a') active = false;
          return {'file_id': 'target-$id', 'status': 'published'};
        },
      ),
      throwsStateError,
    );
    expect(copies, 1);
  });

  test('wrong target ID cannot masquerade as a copied source file', () async {
    await expectLater(
      copyReleasedV2FileInventory(
        linkId: 17,
        ownerVaultId: 'synthetic-owner',
        accessIsCurrent: () => true,
        fetchPage: (_) async => page([file('a')]),
        expectedTargetFileId: (id) async => 'expected-$id',
        copyFile: (_) async => {
          'file_id': 'unrelated-target',
          'status': 'published',
        },
      ),
      throwsFormatException,
    );
  });
}
