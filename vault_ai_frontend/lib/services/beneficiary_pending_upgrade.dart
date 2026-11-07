// Replaces one unpaired PIN-era invitation without exposing a PIN or key to
// the backend. The old link remains until exact new-row readback and a second
// recent OPAQUE proof complete the atomic retirement.

import 'dart:convert';

import 'package:crypto/crypto.dart';

typedef PendingUpgradePost = Future<Map<String, dynamic>> Function(
    String path, Map<String, dynamic> body);
typedef PendingUpgradeGet = Future<Map<String, dynamic>> Function(String path);

class PendingBeneficiaryUpgradeResult {
  final int newLinkId;
  final String pairingCode;

  const PendingBeneficiaryUpgradeResult({
    required this.newLinkId,
    required this.pairingCode,
  });
}

class PendingBeneficiaryUpgradeClient {
  final PendingUpgradePost post;
  final PendingUpgradeGet get;
  final Future<String> Function() proofProvider;
  final Future<String> Function(String label) encryptLabel;
  final bool Function() accessIsCurrent;

  const PendingBeneficiaryUpgradeClient({
    required this.post,
    required this.get,
    required this.proofProvider,
    required this.encryptLabel,
    required this.accessIsCurrent,
  });

  void _requireAccess() {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
  }

  Future<PendingBeneficiaryUpgradeResult> replaceUnpaired({
    required int oldLinkId,
    required String ownerVisibleLabel,
  }) async {
    if (oldLinkId <= 0 ||
        ownerVisibleLabel.trim().isEmpty ||
        ownerVisibleLabel.length > 60) {
      throw const FormatException('Invalid older invitation');
    }
    _requireAccess();
    final labelCiphertext = await encryptLabel(ownerVisibleLabel);
    _requireAccess();
    final stageProof = await proofProvider();
    _requireAccess();
    if (stageProof.isEmpty) throw StateError('Owner proof unavailable');
    final staged = await post('/beneficiary/zk-upgrade-pending/stage', {
      'old_link_id': oldLinkId,
      'passer_label_ciphertext': labelCiphertext,
      'zk_proof_token': stageProof,
    });
    _requireAccess();
    final newId = staged['new_link_id'];
    final code = staged['pairing_code'];
    final snapshot = staged['old_source_snapshot'];
    if (staged['old_link_id'] != oldLinkId ||
        newId is! int ||
        newId <= 0 ||
        newId == oldLinkId ||
        code is! String ||
        !RegExp(r'^[A-HJ-NP-Z2-9]{3}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$')
            .hasMatch(code) ||
        snapshot is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{43}$').hasMatch(snapshot)) {
      throw const FormatException('Invalid invitation stage');
    }
    final readback =
        await get('/beneficiary/zk-upgrade-pending/$oldLinkId/readback');
    _requireAccess();
    final codeHash =
        sha256.convert(utf8.encode(code.replaceAll('-', ''))).toString();
    final expiry =
        DateTime.tryParse('${readback['pairing_expires_at']}')?.toUtc();
    final receiptExpiry =
        DateTime.tryParse('${readback['receipt_expires_at']}')?.toUtc();
    final receipt = readback['readback_receipt'];
    if (readback['old_link_id'] != oldLinkId ||
        readback['new_link_id'] != newId ||
        readback['old_source_snapshot'] != snapshot ||
        readback['passer_label_ciphertext'] != labelCiphertext ||
        readback['pairing_code_hash'] != codeHash ||
        readback['pairing_protocol'] != 'zk-beneficiary-v2' ||
        readback['status'] != 'pairing_pending' ||
        readback['beneficiary_vault_id'] != null ||
        expiry == null ||
        !expiry.isAfter(DateTime.now().toUtc()) ||
        receiptExpiry == null ||
        !receiptExpiry.isAfter(DateTime.now().toUtc()) ||
        receipt is! String ||
        receipt.isEmpty) {
      throw const FormatException('Invitation readback mismatch');
    }
    final retireProof = await proofProvider();
    _requireAccess();
    if (retireProof.isEmpty) throw StateError('Owner proof unavailable');
    final retired = await post('/beneficiary/zk-upgrade-pending/retire', {
      'old_link_id': oldLinkId,
      'new_link_id': newId,
      'old_source_snapshot': snapshot,
      'readback_receipt': receipt,
      'client_verified_exact_bytes': true,
      'zk_proof_token': retireProof,
    });
    _requireAccess();
    if (retired['retired'] != true ||
        retired['old_link_id'] != oldLinkId ||
        retired['new_link_id'] != newId) {
      throw const FormatException('Invitation retirement unconfirmed');
    }
    // The new code is withheld until the old record is retired and the V2
    // invitation can be used as the sole invitation for this beneficiary.
    return PendingBeneficiaryUpgradeResult(
      newLinkId: newId,
      pairingCode: code,
    );
  }
}
