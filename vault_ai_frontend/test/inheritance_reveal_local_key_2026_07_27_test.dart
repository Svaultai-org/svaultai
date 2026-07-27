import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart'
    show
        InheritanceRevealLocalKeyStatus,
        resolveInheritanceRevealLocalKey,
        selectInheritanceRevealLoginIdentifier;

SecretKey _key(int marker) {
  final bytes = Uint8List(32);
  bytes[0] = marker;
  return SecretKey(bytes);
}

Future<int> _marker(SecretKey key) async => (await key.extractBytes()).first;

void main() {
  group('selectInheritanceRevealLoginIdentifier', () {
    test('production refresh path prefers stored VLT handle over stale name',
        () {
      final selected = selectInheritanceRevealLoginIdentifier(
        vaultName: 'Friendly display name',
        lastVaultName: 'Friendly display name',
        vaultHandle: 'VLT-0000-0000-0000-0000-0000-0000',
      );

      expect(selected.vaultName, isNull);
      expect(selected.vaultHandle, 'VLT-0000-0000-0000-0000-0000-0000');
      expect(selected.source, 'stored_vault_handle');
    });

    test('legacy cached VLT value in lastVaultName rehydrates by handle', () {
      final selected = selectInheritanceRevealLoginIdentifier(
        vaultName: null,
        lastVaultName: 'VLT-1111-1111-1111-1111-1111-1111',
        vaultHandle: null,
      );

      expect(selected.vaultName, isNull);
      expect(selected.vaultHandle, 'VLT-1111-1111-1111-1111-1111-1111');
      expect(selected.source, 'name_is_vault_handle');
    });

    test('falls back to vault name only when no handle is available', () {
      final selected = selectInheritanceRevealLoginIdentifier(
        vaultName: 'chosen',
        lastVaultName: 'chosen',
        vaultHandle: null,
      );

      expect(selected.vaultName, 'chosen');
      expect(selected.vaultHandle, isNull);
      expect(selected.source, 'vault_name');
    });
  });

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

    test('legacy authLogin verifyPin path can unlock then rehydrate', () async {
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
          return _key(15);
        },
      );

      expect(result.status, InheritanceRevealLocalKeyStatus.ready);
      expect(result.reason, 'rehydrated_sk_ready');
      expect(await _marker(result.skVault!), 15);
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
      expect(result.reason, 'missing_sk_after_rehydrate');
      expect(result.skVault, isNull);
    });

    test('mismatched active key without rehydrate fails safely', () async {
      final result = await resolveInheritanceRevealLocalKey(
        vaultId: 'vault-a',
        pin: '123456',
        cachedPinMatches: (_) async => true,
        unlockWithPin: (_) async => true,
        currentSk: () => _key(3),
        currentSkVaultId: () => 'vault-b',
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

    test('missing-key fallback is specific and actionable', () {
      expect(
        mainSource
            .contains('Could not restore this device\\\'s inheritance key'),
        isTrue,
      );
      expect(
        mainSource.contains('Unlock this beneficiary vault with your PIN'),
        isTrue,
      );
    });

    test('safe reveal diagnostics never log PINs, keys, ciphertext, or tokens',
        () {
      final lines = mainSource
          .split('\n')
          .where((line) =>
              line.contains('inheritanceRevealDiag(') ||
              line.contains('[inheritance-reveal-diag]') ||
              line.contains('vault_fpr') ||
              line.contains('expected_vault_fpr') ||
              line.contains('actual_vault_fpr') ||
              line.contains('id_source') ||
              line.contains('active_sk_present'))
          .join('\n');

      for (final allowed in const [
        'branch=',
        'vault_fpr',
        'expected_vault_fpr',
        'actual_vault_fpr',
        'id_source',
        'active_sk_present',
      ]) {
        expect(lines.contains(allowed), isTrue);
      }
      for (final forbidden in const [
        'pin:',
        'pin=',
        'token',
        'ciphertext',
        'encrypted_payload',
        'wrapped_key',
        'decrypted',
        'password',
      ]) {
        expect(lines.contains(forbidden), isFalse);
      }
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
