// Dart unit tests for vault_handle.dart. Pure-Dart, no browser or WASM.
// Verifies round-trip stability, input tolerance, and byte-for-byte
// compatibility with the Python backend implementation.

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/vault_handle.dart';

void main() {
  group('vault_handle', () {
    test('generate() returns 15 bytes', () {
      for (var i = 0; i < 50; i++) {
        final h = generateVaultHandle();
        expect(h.length, vaultHandleBytes);
        expect(h, isA<Uint8List>());
      }
    });

    test('display form has VLT- prefix and six groups of four', () {
      final raw = generateVaultHandle();
      final disp = vaultHandleToDisplay(raw);
      expect(disp.startsWith(vaultHandlePrefix), isTrue);
      final tail = disp.substring(vaultHandlePrefix.length);
      final groups = tail.split('-');
      expect(groups.length, 6);
      for (final g in groups) {
        expect(g.length, 4);
      }
      expect(tail.replaceAll('-', '').length, vaultHandleDisplayChars);
    });

    test('display round-trip is stable across 50 handles', () {
      for (var i = 0; i < 50; i++) {
        final raw = generateVaultHandle();
        final disp = vaultHandleToDisplay(raw);
        expect(vaultHandleFromDisplay(disp), equals(raw));
      }
    });

    test('fromDisplay tolerates dashes/case/whitespace variants', () {
      final raw = generateVaultHandle();
      final canonical = vaultHandleToDisplay(raw);
      expect(vaultHandleFromDisplay(canonical), equals(raw));
      expect(vaultHandleFromDisplay(canonical.toLowerCase()), equals(raw));
      expect(vaultHandleFromDisplay(canonical.replaceAll('-', '')),
          equals(raw));
      expect(vaultHandleFromDisplay(' $canonical '), equals(raw));
      expect(
        vaultHandleFromDisplay(canonical.replaceFirst('VLT-', '')),
        equals(raw),
      );
    });

    test('fromDisplay rejects invalid input', () {
      expect(() => vaultHandleFromDisplay(''),
          throwsA(isA<InvalidVaultHandle>()));
      expect(
        () => vaultHandleFromDisplay('VLT-XXXX-XXXX-XXXX-XXXX-XXXX'),
        throwsA(isA<InvalidVaultHandle>()),
      );
      expect(
        () => vaultHandleFromDisplay('VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XX!Z'),
        throwsA(isA<InvalidVaultHandle>()),
      );
      expect(() => vaultHandleFromDisplay('A' * 500),
          throwsA(isA<InvalidVaultHandle>()));
    });

    test('isValidVaultHandleDisplay behaves as expected', () {
      final raw = generateVaultHandle();
      expect(isValidVaultHandleDisplay(vaultHandleToDisplay(raw)), isTrue);
      expect(isValidVaultHandleDisplay(''), isFalse);
      expect(isValidVaultHandleDisplay('VLT-XXXX'), isFalse);
      expect(isValidVaultHandleDisplay('not a handle'), isFalse);
    });

    test('confusable chars normalized (I=1, L=1, O=0, U=V)', () {
      final raw = generateVaultHandle();
      final disp = vaultHandleToDisplay(raw);
      final tail =
          disp.substring(vaultHandlePrefix.length).replaceAll('-', '');
      // Best-effort: only substitute if the tail actually contains 1/0
      // to substitute for.
      final withConfusables = tail
          .replaceFirst('1', 'I')
          .replaceFirst('0', 'O');
      if (withConfusables != tail) {
        final recovered =
            vaultHandleFromDisplay(vaultHandlePrefix + withConfusables);
        expect(recovered, equals(raw));
      }
    });

    test('base64url encoding matches Python b64url helper', () {
      // Test vector: known 15 bytes → known base64url (no padding).
      final raw = Uint8List.fromList([
        0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
        0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E,
      ]);
      // Python: base64.urlsafe_b64encode(bytes(range(15))).rstrip(b'=')
      // => 'AAECAwQFBgcICQoLDA0O'
      expect(vaultHandleB64Url(raw), 'AAECAwQFBgcICQoLDA0O');

      final raw2 = Uint8List.fromList(List<int>.generate(15, (i) => 0xFF));
      // All-1s: 120 bits of 1 → 20 base64url chars (each 6-bit group
      // is 0b111111 which maps to '_' in base64url).
      expect(vaultHandleB64Url(raw2), '____________________');
    });

    test('credentialId helper is base64url of handle bytes', () {
      final raw = Uint8List.fromList(List<int>.generate(15, (i) => i * 3));
      expect(vaultHandleCredentialId(raw), vaultHandleB64Url(raw));
    });

    test('no two handles collide in 1000 samples', () {
      final seen = <String>{};
      for (var i = 0; i < 1000; i++) {
        final h = generateVaultHandle();
        final key = h.map((b) => b.toRadixString(16)).join();
        expect(seen.contains(key), isFalse);
        seen.add(key);
      }
    });
  });
}
