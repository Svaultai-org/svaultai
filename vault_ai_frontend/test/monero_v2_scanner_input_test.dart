import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/monero_crypto_primitives.dart';
import 'package:vault_ai_frontend/services/monero_ed25519.dart';
import 'package:vault_ai_frontend/services/monero_v2_scanner_input.dart';

String _hex(List<int> bytes) =>
    bytes.map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();

void main() {
  final spend = scRed32(Uint8List.fromList(List<int>.filled(32, 7)));
  final view = moneroDerivePrivateViewKey(spend);
  final publicSpend = moneroDerivePublicKey(spend);
  final publicView = moneroDerivePublicKey(view);
  final address = buildMoneroPrimaryAddress(
    publicSpendKey: publicSpend,
    publicViewKey: publicView,
  );
  Map<String, dynamic> backup() => {
        'schema': 'monero_wallet_secret_v1',
        'privateSpendKeyHex': _hex(spend),
        'privateViewKeyHex': _hex(view),
        'publicSpendKeyHex': _hex(publicSpend),
        'publicViewKeyHex': _hex(publicView),
        'restoreHeight': 3000000,
      };

  test('verified V2 backup supplies actual view-only scan keys', () async {
    final input = await moneroScannerInputFromVerifiedV2Secret(
      secret: jsonEncode(backup()),
      publicAddress: address,
    );
    expect(input.privateViewKey, orderedEquals(view));
    expect(input.publicSpendKey, orderedEquals(publicSpend));
    expect(input.privateViewKey.every((byte) => byte == 0), isFalse);
    expect(input.restoreHeight, 3000000);
    expect(input.publicAddress, address);
    expect(input.toString(), 'MoneroScannerInput(<redacted>)');
    input.wipe();
    expect(input.privateViewKey.every((byte) => byte == 0), isTrue);
  });

  test('mismatched address and altered keys cannot start a scan', () async {
    await expectLater(
      moneroScannerInputFromVerifiedV2Secret(
        secret: jsonEncode(backup()),
        publicAddress: 'wrong-address',
      ),
      throwsFormatException,
    );
    final altered = backup()..['privateViewKeyHex'] = '00' * 32;
    await expectLater(
      moneroScannerInputFromVerifiedV2Secret(
        secret: jsonEncode(altered),
        publicAddress: address,
      ),
      throwsFormatException,
    );
  });

  test('restore height must be a bounded integer', () async {
    for (final invalid in <Object>[-1, 100000001, '3000000']) {
      final altered = backup()..['restoreHeight'] = invalid;
      await expectLater(
        moneroScannerInputFromVerifiedV2Secret(
          secret: jsonEncode(altered),
          publicAddress: address,
        ),
        throwsFormatException,
      );
    }
  });
}
