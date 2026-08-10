import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/wallet_v2_repository.dart';
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';

WalletV2Envelope envelope(
  Uint8List ciphertext, {
  String id = 'opaque-wallet-record-id',
  String chain = 'evm',
}) =>
    WalletV2Envelope(
      walletRecordId: id,
      chain: chain,
      network: 'qa',
      asset: 'ETH',
      publicAddress: '0x01',
      walletLabel: 'QA',
      payloadCiphertext: ciphertext,
      envelopeVersion: 'v2',
      migrationState: 'v2_verified',
    );

void main() {
  final mvk = SecretKey(List<int>.generate(32, (i) => i));
  const id = 'opaque-wallet-record-id';
  const secret = <String, dynamic>{'privateKeyHex': 'synthetic-zero-balance'};

  test('WalletV2 equality and stable MVK plus record ID', () async {
    final crypto = WalletV2Crypto(mvk);
    final ciphertext = await crypto.encrypt(
      walletRecordId: id,
      chain: 'evm',
      secretPayload: secret,
    );
    expect(await WalletV2Crypto(mvk).decrypt(envelope(ciphertext)), secret);
  });

  test('wrong MVK fails', () async {
    final ciphertext = await WalletV2Crypto(mvk)
        .encrypt(walletRecordId: id, chain: 'evm', secretPayload: secret);
    final wrong = SecretKey(List<int>.generate(32, (i) => i + 1));
    await expectLater(
        WalletV2Crypto(wrong).decrypt(envelope(ciphertext)), throwsA(anything));
  });

  test('wrong record ID or chain AAD fails', () async {
    final ciphertext = await WalletV2Crypto(mvk)
        .encrypt(walletRecordId: id, chain: 'evm', secretPayload: secret);
    await expectLater(
      WalletV2Crypto(mvk).decrypt(envelope(ciphertext, id: 'other-record-id')),
      throwsA(anything),
    );
    await expectLater(
      WalletV2Crypto(mvk).decrypt(envelope(ciphertext, chain: 'solana')),
      throwsA(anything),
    );
  });

  test('other vault domain keys cannot decrypt WalletV2', () async {
    final ciphertext = await WalletV2Crypto(mvk)
        .encrypt(walletRecordId: id, chain: 'evm', secretPayload: secret);
    final hierarchy = VaultKeyHierarchy(mvk);
    final domains = <SecretKey>[
      await hierarchy.credentialKey(),
      await hierarchy.memoryKey(),
      await hierarchy.walletBackupKey(),
      await hierarchy.metadataKey(),
    ];
    for (final domain in domains) {
      final wrongRecordKey =
          await Hkdf(hmac: Hmac.sha256(), outputLength: 32).deriveKey(
        secretKey: domain,
        nonce: utf8.encode(id),
        info: utf8.encode('vaultai.wallet.record.v2'),
      );
      await expectLater(
        aesGcmUnwrapWithAad(wrongRecordKey, ciphertext,
            aad: utf8.encode('svaultai|client_mvk_v2|wallet|$id|evm|v2')),
        throwsA(anything),
      );
    }
  });
}
