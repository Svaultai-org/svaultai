// ZK ciphertext-first envelope for crypto send drafts.
//
// Called by the ETH/Solana/TRON send panels before POSTing to
// /crypto/wallet/{asset}/send/draft (or the network-scoped
// sibling). Given the plaintext draft metadata and the active MVK,
// returns the pair (draftPayloadCiphertext, senderAddressLookupHash)
// that the API-client method attaches to the request body.
//
// Fails safe: returns null when the vault key cache does not have
// an active key for the caller. The caller then falls back to
// legacy plaintext-only send.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';

class ZkSendDraftEnvelope {
  final String draftPayloadCiphertext;
  final String senderAddressLookupHash;
  const ZkSendDraftEnvelope({
    required this.draftPayloadCiphertext,
    required this.senderAddressLookupHash,
  });
}

/// Build the ciphertext + keyed hash a ZK send-draft POST needs.
///
/// Returns null when [activeMvk] is null. The panel then omits the
/// two ciphertext fields and the server accepts the legacy plaintext
/// draft path — used only for un-adopted legacy vaults.
Future<ZkSendDraftEnvelope?> buildZkSendDraftEnvelope({
  required SecretKey? activeMvk,
  required String fromAddress,
  required String destinationAddress,
  required String asset,
  String? amountEth,
  String? amountSol,
  String? amountUsdt,
  Map<String, dynamic> extra = const {},
}) async {
  if (activeMvk == null) return null;

  final hierarchy = VaultKeyHierarchy(activeMvk);
  final metaKey = await hierarchy.metadataKey();
  final walletLookup = await hierarchy.walletLockLookupKey();

  final payload = <String, dynamic>{
    'fromAddress': fromAddress,
    'destinationAddress': destinationAddress,
    'asset': asset,
    if (amountEth != null) 'amountEth': amountEth,
    if (amountSol != null) 'amountSol': amountSol,
    if (amountUsdt != null) 'amountUsdt': amountUsdt,
    ...extra,
  };
  final payloadBytes = Uint8List.fromList(utf8.encode(jsonEncode(payload)));
  final ct = await aesGcmWrap(metaKey, payloadBytes);
  final senderHash = await keyedLookupHash(
    walletLookup, utf8.encode(fromAddress.toLowerCase()),
  );

  return ZkSendDraftEnvelope(
    draftPayloadCiphertext: b64urlEncode(ct),
    senderAddressLookupHash: b64urlEncode(senderHash),
  );
}
