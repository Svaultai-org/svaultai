// Ciphertext-first outgoing-history helper.
//
// Called by the ETH/Solana/TRON send panels immediately after a
// successful broadcast. Encrypts the outcome payload (destination,
// amount, asset, signature, outcome status text) under the active
// vault's metadata subkey and computes a keyed signature lookup
// hash so the server can dedup / re-poll without seeing the raw
// signature.
//
// Fire-and-forget from the panel — a failure never blocks the
// success UI. The row is eventually caught by lazy migration if
// this call fails.
//
// Contains no crypto — composes vault_key_hierarchy primitives.

import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

import 'vault_key_hierarchy.dart';

class ZkOutgoingHistoryEnvelope {
  final String signatureLookupHash;
  final String outcomePayloadCiphertext;
  const ZkOutgoingHistoryEnvelope({
    required this.signatureLookupHash,
    required this.outcomePayloadCiphertext,
  });
}

Future<ZkOutgoingHistoryEnvelope?> buildZkOutgoingHistoryEnvelope({
  required SecretKey? activeMvk,
  required String signature,
  required String senderAddress,
  required String destinationAddress,
  required String asset,
  required String amount,
  required String outcome,
  String? feeAmount,
  Map<String, dynamic> extra = const {},
}) async {
  if (activeMvk == null) return null;

  final hierarchy = VaultKeyHierarchy(activeMvk);
  final metaKey = await hierarchy.metadataKey();
  final walletLookup = await hierarchy.walletLockLookupKey();

  final payload = <String, dynamic>{
    'signature': signature,
    'senderAddress': senderAddress,
    'destinationAddress': destinationAddress,
    'asset': asset,
    'amount': amount,
    'outcome': outcome,
    if (feeAmount != null) 'feeAmount': feeAmount,
    ...extra,
  };
  final ct = await aesGcmWrap(
    metaKey, Uint8List.fromList(utf8.encode(jsonEncode(payload))),
  );
  final sigHash = await keyedLookupHash(
    walletLookup, utf8.encode(signature),
  );
  return ZkOutgoingHistoryEnvelope(
    signatureLookupHash: b64urlEncode(sigHash),
    outcomePayloadCiphertext: b64urlEncode(ct),
  );
}
