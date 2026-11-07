import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/beneficiary_pending_upgrade.dart';

const _code = 'ABC-DEFG-HJKL';
const _snapshot = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _ciphertext = 'synthetic-label-ciphertext';

class _Server {
  bool oldPresent = true;
  bool newPresent = false;
  bool corruptReadback = false;
  bool failSecondProof = false;
  bool current = true;
  int proofCalls = 0;
  String expectedLabel = 'Family';
  final paths = <String>[];

  Future<String> proof() async {
    proofCalls++;
    if (failSecondProof && proofCalls == 2) throw StateError('cancelled');
    return 'opaque-action-proof-$proofCalls';
  }

  Future<Map<String, dynamic>> post(
      String path, Map<String, dynamic> body) async {
    paths.add(path);
    final wire = jsonEncode(body);
    expect(wire, isNot(contains('raw-pin')));
    expect(wire, isNot(contains('private-key')));
    expect(wire, isNot(contains(expectedLabel)));
    if (path.endsWith('/stage')) {
      expect(oldPresent, isTrue);
      expect(body['old_link_id'], 7);
      expect(body['passer_label_ciphertext'], _ciphertext);
      expect(body['zk_proof_token'], 'opaque-action-proof-1');
      newPresent = true;
      return {
        'old_link_id': 7,
        'new_link_id': 8,
        'old_source_snapshot': _snapshot,
        'pairing_code': _code,
      };
    }
    if (path.endsWith('/retire')) {
      expect(oldPresent, isTrue);
      expect(newPresent, isTrue);
      expect(body['client_verified_exact_bytes'], true);
      expect(body['readback_receipt'], 'session-bound-receipt');
      expect(body['zk_proof_token'], 'opaque-action-proof-2');
      oldPresent = false;
      return {'old_link_id': 7, 'new_link_id': 8, 'retired': true};
    }
    throw StateError('Unexpected write');
  }

  Future<Map<String, dynamic>> get(String path) async {
    paths.add(path);
    expect(path, '/beneficiary/zk-upgrade-pending/7/readback');
    expect(oldPresent, isTrue);
    expect(newPresent, isTrue);
    return {
      'old_link_id': 7,
      'new_link_id': 8,
      'old_source_snapshot': _snapshot,
      'passer_label_ciphertext': _ciphertext,
      'pairing_code_hash': corruptReadback
          ? 'changed-hash'
          : sha256.convert(utf8.encode('ABCDEFGHJKL')).toString(),
      'pairing_protocol': 'zk-beneficiary-v2',
      'status': 'pairing_pending',
      'beneficiary_vault_id': null,
      'pairing_expires_at': DateTime.now()
          .toUtc()
          .add(const Duration(minutes: 30))
          .toIso8601String(),
      'readback_receipt': 'session-bound-receipt',
      'receipt_expires_at': DateTime.now()
          .toUtc()
          .add(const Duration(minutes: 10))
          .toIso8601String(),
    };
  }

  PendingBeneficiaryUpgradeClient client() => PendingBeneficiaryUpgradeClient(
        post: post,
        get: get,
        proofProvider: proof,
        encryptLabel: (label) async {
          expect(label, expectedLabel);
          return _ciphertext;
        },
        accessIsCurrent: () => current,
      );
}

void main() {
  test('unused old invitation is offered even without a readable label', () {
    final pending = <String, dynamic>{
      'id': 7,
      'status': 'pairing_pending',
      'is_linked': false,
      'credentials_saved': false,
      'zk_pairing_v2': false,
      'label': null,
    };
    expect(pendingBeneficiaryInvitationCanUpgrade(pending), isTrue);
    expect(
        pendingBeneficiaryInvitationCanUpgrade({
          ...pending,
          'label': 'Encrypted label unavailable',
        }),
        isTrue);
    expect(
        pendingBeneficiaryInvitationCanUpgrade({
          ...pending,
          'is_linked': true,
        }),
        isFalse);
    expect(
        pendingBeneficiaryInvitationCanUpgrade({
          ...pending,
          'credentials_saved': true,
        }),
        isFalse);
    expect(
        pendingBeneficiaryInvitationCanUpgrade({
          ...pending,
          'zk_pairing_v2': true,
        }),
        isFalse);
    expect(
        pendingBeneficiaryInvitationCanUpgrade({
          ...pending,
          'status': 'transfer_pending',
        }),
        isFalse);
    expect(
        pendingBeneficiaryInvitationCanUpgrade({
          ...pending,
          'id': 0,
        }),
        isFalse);
  });

  test('owner-supplied replacement name is encrypted before stage', () async {
    final server = _Server()..expectedLabel = 'Family contact';
    final result = await server.client().replaceUnpaired(
          oldLinkId: 7,
          ownerVisibleLabel: 'Family contact',
        );
    expect(result.pairingCode, _code);
    expect(server.oldPresent, isFalse);
  });

  test('owner sees code only after exact readback and old row retirement',
      () async {
    final server = _Server();
    final result = await server.client().replaceUnpaired(
          oldLinkId: 7,
          ownerVisibleLabel: 'Family',
        );
    expect(result.newLinkId, 8);
    expect(result.pairingCode, _code);
    expect(server.oldPresent, isFalse);
    expect(server.newPresent, isTrue);
    expect(server.paths, [
      '/beneficiary/zk-upgrade-pending/stage',
      '/beneficiary/zk-upgrade-pending/7/readback',
      '/beneficiary/zk-upgrade-pending/retire',
    ]);
  });

  test('changed readback never retires the old invitation', () async {
    final server = _Server()..corruptReadback = true;
    await expectLater(
      server.client().replaceUnpaired(
            oldLinkId: 7,
            ownerVisibleLabel: 'Family',
          ),
      throwsFormatException,
    );
    expect(server.oldPresent, isTrue);
    expect(server.newPresent, isTrue);
    expect(server.proofCalls, 1);
    expect(server.paths,
        isNot(contains('/beneficiary/zk-upgrade-pending/retire')));
  });

  test('cancelled second owner proof keeps the old invitation', () async {
    final server = _Server()..failSecondProof = true;
    await expectLater(
      server.client().replaceUnpaired(
            oldLinkId: 7,
            ownerVisibleLabel: 'Family',
          ),
      throwsStateError,
    );
    expect(server.oldPresent, isTrue);
    expect(server.newPresent, isTrue);
    expect(server.paths,
        isNot(contains('/beneficiary/zk-upgrade-pending/retire')));
  });
}
