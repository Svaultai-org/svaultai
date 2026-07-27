import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show InheritanceRevealLocalKeyStatus, resolveInheritanceRevealLocalKey;

SecretKey _key(int marker) {
  final bytes = Uint8List(32);
  bytes[0] = marker;
  return SecretKey(bytes);
}

Future<int> _marker(SecretKey key) async => (await key.extractBytes()).first;

void main() {
  group('resolveInheritanceRevealLocalKey', () {
    test('beneficiary PIN login on this device uses existing vault key',
        () async {
      var unlockCalled = false;
      var rehydrateCalled = false;
      final sk = _key(7);

      final result = await resolveInheritanceRevealLocalKey(
        vaultId: 'vault-a',
        pin: '123456',
        cachedPinMatches: (_) async => true,
        unlockWithPin: (_) async {
          unlockCalled = true;
          return true;
        },
        currentSk: () => sk,
        currentSkVaultId: () => 'vault-a',
        rehydrateSkWithPin: (_) async {
          rehydrateCalled = true;
          return _key(9);
        },
      );

      expect(result.status, InheritanceRevealLocalKeyStatus.ready);
      expect(await _marker(result.skVault!), 7);
      expect(unlockCalled, isFalse);
      expect(rehydrateCalled, isFalse);
    });

    test('refresh after valid PIN rehydrates missing inheritance key',
        () async {
      var unlockCalled = false;
      var rehydrateCalled = false;

      final result = await resolveInheritanceRevealLocalKey(
        vaultId: 'vault-a',
        pin: '123456',
        cachedPinMatches: (_) async => null,
        unlockWithPin: (_) async {
          unlockCalled = true;
          return true;
        },
        currentSk: () => null,
        currentSkVaultId: () => null,
        rehydrateSkWithPin: (_) async {
          rehydrateCalled = true;
          return _key(11);
        },
      );

      expect(result.status, InheritanceRevealLocalKeyStatus.ready);
      expect(await _marker(result.skVault!), 11);
      expect(unlockCalled, isTrue);
      expect(rehydrateCalled, isTrue);
    });

    test('session without an unlockable local key is blocked safely', () async {
      var rehydrateCalled = false;

      final result = await resolveInheritanceRevealLocalKey(
        vaultId: 'vault-a',
        pin: '999999',
        cachedPinMatches: (_) async => null,
        unlockWithPin: (_) async => false,
        currentSk: () => null,
        currentSkVaultId: () => null,
        rehydrateSkWithPin: (_) async {
          rehydrateCalled = true;
          return _key(12);
        },
      );

      expect(result.status, InheritanceRevealLocalKeyStatus.invalidPin);
      expect(result.skVault, isNull);
      expect(rehydrateCalled, isFalse);
    });

    test('incorrect cached PIN never fetches or rehydrates key', () async {
      var unlockCalled = false;
      var rehydrateCalled = false;

      final result = await resolveInheritanceRevealLocalKey(
        vaultId: 'vault-a',
        pin: '000000',
        cachedPinMatches: (_) async => false,
        unlockWithPin: (_) async {
          unlockCalled = true;
          return true;
        },
        currentSk: () => _key(1),
        currentSkVaultId: () => 'vault-a',
        rehydrateSkWithPin: (_) async {
          rehydrateCalled = true;
          return _key(2);
        },
      );

      expect(result.status, InheritanceRevealLocalKeyStatus.invalidPin);
      expect(result.skVault, isNull);
      expect(unlockCalled, isFalse);
      expect(rehydrateCalled, isFalse);
    });

    test('missing or corrupt beneficiary private key fails closed', () async {
      final result = await resolveInheritanceRevealLocalKey(
        vaultId: 'vault-a',
        pin: '123456',
        cachedPinMatches: (_) async => true,
        unlockWithPin: (_) async => true,
        currentSk: () => null,
        currentSkVaultId: () => null,
        rehydrateSkWithPin: (_) async => null,
      );

      expect(result.status, InheritanceRevealLocalKeyStatus.missingLocalKey);
      expect(result.skVault, isNull);
    });

    test('stale key from another vault is ignored', () async {
      final result = await resolveInheritanceRevealLocalKey(
        vaultId: 'vault-a',
        pin: '123456',
        cachedPinMatches: (_) async => true,
        unlockWithPin: (_) async => true,
        currentSk: () => _key(3),
        currentSkVaultId: () => 'vault-b',
        rehydrateSkWithPin: (_) async => _key(4),
      );

      expect(result.status, InheritanceRevealLocalKeyStatus.ready);
      expect(await _marker(result.skVault!), 4);
    });
  });

  group('_beneficiaryRevealCredentials source contract', () {
    late String mainSource;

    setUpAll(() {
      mainSource = File('lib/main.dart').readAsStringSync();
    });

    test('resolves the local inheritance key before backend retrieval', () {
      final idx = mainSource.indexOf(
        'Future<void> _beneficiaryRevealCredentials',
      );
      expect(idx, greaterThan(-1));
      final window =
          mainSource.substring(idx, (idx + 6500).clamp(0, mainSource.length));

      final resolveIdx = window.indexOf('resolveInheritanceRevealLocalKey');
      final retrieveIdx = window.indexOf('retrieveInheritanceCredentials');
      expect(resolveIdx, greaterThan(-1));
      expect(retrieveIdx, greaterThan(-1));
      expect(
        resolveIdx,
        lessThan(retrieveIdx),
        reason: 'wrong PIN or missing local key must stop before ciphertext '
            'is fetched from the backend',
      );
    });

    test('uses a vault-scoped active sk_vault, not any process key', () {
      final idx = mainSource.indexOf(
        'Future<void> _beneficiaryRevealCredentials',
      );
      final window =
          mainSource.substring(idx, (idx + 6500).clamp(0, mainSource.length));
      expect(window.contains('_activeInheritanceSkForVault(vaultId)'), isTrue);
      expect(window.contains('currentSkVaultId'), isTrue);
      expect(
        mainSource.contains('Please log out and log back in with your PIN'),
        isFalse,
      );
    });
  });

  group('backend inherited credential retrieve contract', () {
    test('retrieve endpoint returns encrypted package fields only', () {
      final source = File(
        '../vault_ai_backend/routes/inheritance_release_routes.py',
      ).readAsStringSync();
      final idx = source.indexOf('return RetrievedCredentialPackage(');
      expect(idx, greaterThan(-1));
      final window =
          source.substring(idx, (idx + 1400).clamp(0, source.length));

      for (final field in const [
        'encrypted_payload',
        'payload_nonce',
        'wrapped_key',
        'wrapping_ephemeral_pk',
        'wrapping_nonce',
      ]) {
        expect(window.contains(field), isTrue);
      }
      for (final forbidden in const [
        'username=',
        'password=',
        'pin=',
        'decrypted',
        'plaintext',
      ]) {
        expect(window.contains(forbidden), isFalse);
      }
    });
  });
}
