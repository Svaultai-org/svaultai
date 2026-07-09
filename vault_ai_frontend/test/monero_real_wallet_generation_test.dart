


import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/services/monero_crypto_primitives.dart';
import 'package:vault_ai_frontend/services/monero_wallet.dart';


Uint8List _fillSeed(int b) {
  return Uint8List.fromList(List<int>.filled(32, b));
}


void main() {
  group('RealMoneroWalletAdapter — end-to-end derivation', () {

    test(
      'deterministic all-zeros seed produces a valid mainnet primary address',
      () async {
        final adapter = RealMoneroWalletAdapter();
        final wallet = await adapter.generate(
          restoreHeight: 3220000,
          encryptForVault: (p) async => 'vault-ct:${p.length}',
          seedForTests: _fillSeed(0),
        );
        expect(wallet.publicAddress.length, 95);
        expect(wallet.publicAddress.substring(0, 1), '4');
        expect(
          moneroPrimaryAddressChecksumValid(wallet.publicAddress),
          true,
        );
        expect(wallet.restoreHeight, 3220000);
        expect(wallet.encryptedWalletSecretPayload.startsWith('vault-ct:'),
            true);
      },
    );

    test(
      'deterministic all-ones seed produces a distinct valid address',
      () async {
        final adapter = RealMoneroWalletAdapter();
        final w0 = await adapter.generate(
          restoreHeight: 3220000,
          encryptForVault: (p) async => p,
          seedForTests: _fillSeed(0),
        );
        final w1 = await adapter.generate(
          restoreHeight: 3220000,
          encryptForVault: (p) async => p,
          seedForTests: _fillSeed(0xFF),
        );
        expect(w0.publicAddress != w1.publicAddress, true);
        expect(
          moneroPrimaryAddressChecksumValid(w0.publicAddress),
          true,
        );
        expect(
          moneroPrimaryAddressChecksumValid(w1.publicAddress),
          true,
        );
      },
    );

    test('two random-seeded wallets produce different valid addresses',
        () async {
      final adapter = RealMoneroWalletAdapter();
      final a = await adapter.generate(
        restoreHeight: 3200000,
        encryptForVault: (p) async => p,
      );
      final b = await adapter.generate(
        restoreHeight: 3200000,
        encryptForVault: (p) async => p,
      );
      expect(a.publicAddress != b.publicAddress, true);
      expect(
        moneroPrimaryAddressChecksumValid(a.publicAddress),
        true,
      );
      expect(
        moneroPrimaryAddressChecksumValid(b.publicAddress),
        true,
      );
      expect(a.publicAddress.length, 95);
      expect(b.publicAddress.length, 95);
    });

    test(
      'plaintext secret payload is passed through encryptForVault, '
      'ciphertext is what is emitted',
      () async {
        final captured = <String>[];
        final adapter = RealMoneroWalletAdapter();
        final w = await adapter.generate(
          restoreHeight: 3220000,
          encryptForVault: (p) async {
            captured.add(p);
            return 'CIPHER:${p.length}';
          },
          seedForTests: _fillSeed(0xAB),
        );
        expect(captured.length, 1);
        expect(w.encryptedWalletSecretPayload, 'CIPHER:${captured[0].length}');
        expect(w.encryptedWalletSecretPayload.startsWith('CIPHER:'), true);
      },
    );

    test('plaintext secret payload never contains "seed:" or a mnemonic key',
        () async {
      String? seenPlaintext;
      final adapter = RealMoneroWalletAdapter();
      await adapter.generate(
        restoreHeight: 3220000,
        encryptForVault: (p) async {
          seenPlaintext = p;
          return 'ct';
        },
        seedForTests: _fillSeed(0x33),
      );
      expect(seenPlaintext, isNotNull);
      expect(seenPlaintext!.contains('mnemonic'), false);
      expect(seenPlaintext!.contains('seed25'), false);
      expect(seenPlaintext!.contains('polyseed'), false);
    });

    test('rejects negative restoreHeight', () async {
      final adapter = RealMoneroWalletAdapter();
      await expectLater(
        adapter.generate(
          restoreHeight: -1,
          encryptForVault: (p) async => p,
          seedForTests: _fillSeed(0),
        ),
        throwsA(isA<MoneroWalletGenerationFailed>()),
      );
    });

    test('adapter reports isAvailable=true and empty unavailableReason', () {
      final adapter = RealMoneroWalletAdapter();
      expect(adapter.isAvailable, true);
      expect(adapter.unavailableReason, isEmpty);
    });
  });
}
