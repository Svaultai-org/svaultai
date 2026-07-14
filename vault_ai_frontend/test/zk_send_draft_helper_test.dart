// Tests for the ZK crypto send-draft ciphertext envelope helper.
//
// Verifies:
//   * legacy vault (no active MVK) → null envelope; falls through
//     to legacy plaintext send
//   * ZK vault → both fields populated; ciphertext decrypts back to
//     the original plaintext draft body
//   * sender_address_lookup_hash is deterministic for the same key
//     + same address; different for different addresses

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_send_draft_helper.dart';

void main() {
  test('returns null when active MVK is absent (legacy vault)', () async {
    final env = await buildZkSendDraftEnvelope(
      activeMvk: null,
      fromAddress: '0xdead',
      destinationAddress: '0xbeef',
      asset: 'ETH',
      amountEth: '0.01',
    );
    expect(env, isNull);
  });

  test('returns ciphertext + hash for a ZK vault', () async {
    final mvk = SecretKey(Uint8List.fromList(
      List<int>.generate(32, (i) => (i * 7 + 3) & 0xFF),
    ));
    final env = await buildZkSendDraftEnvelope(
      activeMvk: mvk,
      fromAddress: '0xSender',
      destinationAddress: '0xDest',
      asset: 'ETH',
      amountEth: '0.5',
    );
    expect(env, isNotNull);
    expect(env!.draftPayloadCiphertext.isNotEmpty, isTrue);
    expect(env.senderAddressLookupHash.isNotEmpty, isTrue);

    // Decrypt back and verify payload.
    final hierarchy = VaultKeyHierarchy(mvk);
    final metaKey = await hierarchy.metadataKey();
    final envelopeBytes = b64urlDecode(env.draftPayloadCiphertext);
    final decrypted = await aesGcmUnwrap(metaKey, envelopeBytes);
    final payload = jsonDecode(utf8.decode(decrypted));
    expect(payload['fromAddress'], '0xSender');
    expect(payload['destinationAddress'], '0xDest');
    expect(payload['asset'], 'ETH');
    expect(payload['amountEth'], '0.5');
  });

  test('sender_address_lookup_hash is stable across calls for same key + addr',
      () async {
    final mvk = SecretKey(Uint8List(32));
    final e1 = await buildZkSendDraftEnvelope(
      activeMvk: mvk,
      fromAddress: '0xABCD',
      destinationAddress: '0xEFAB',
      asset: 'SOL',
      amountSol: '1.0',
    );
    final e2 = await buildZkSendDraftEnvelope(
      activeMvk: mvk,
      fromAddress: '0xABCD',
      destinationAddress: '0xDDDD',
      asset: 'SOL',
      amountSol: '2.0',
    );
    // Same sender → same hash (used for wallet-lock single-flight)
    expect(e1!.senderAddressLookupHash,
        equals(e2!.senderAddressLookupHash));
    // Different sender → different hash
    final e3 = await buildZkSendDraftEnvelope(
      activeMvk: mvk,
      fromAddress: '0xffff',
      destinationAddress: '0xEFAB',
      asset: 'SOL',
      amountSol: '1.0',
    );
    expect(e1.senderAddressLookupHash,
        isNot(equals(e3!.senderAddressLookupHash)));
  });

  test('case-insensitive fromAddress produces same hash (EVM normalization)',
      () async {
    final mvk = SecretKey(Uint8List(32));
    final e1 = await buildZkSendDraftEnvelope(
      activeMvk: mvk,
      fromAddress: '0xABCDef',
      destinationAddress: '0xEFAB',
      asset: 'ETH',
      amountEth: '0.01',
    );
    final e2 = await buildZkSendDraftEnvelope(
      activeMvk: mvk,
      fromAddress: '0xabcdef',
      destinationAddress: '0xEFAB',
      asset: 'ETH',
      amountEth: '0.01',
    );
    expect(e1!.senderAddressLookupHash,
        equals(e2!.senderAddressLookupHash));
  });
}
