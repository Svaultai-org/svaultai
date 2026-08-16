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

    test(
        'production legacy-login then handle rehydrate sequence gates '
        'ciphertext retrieval until sk_vault is restored', () async {
      final events = <String>[];
      SecretKey? activeSk;
      String? activeSkVaultId;

      final result = await resolveInheritanceRevealLocalKey(
        vaultId: 'beneficiary-vault',
        pin: '123456',
        cachedPinMatches: (_) async {
          events.add('pin_cache_missing');
          return null;
        },
        unlockWithPin: (candidatePin) async {
          expect(candidatePin, '123456');
          events.add('legacy_auth_login_succeeded');
          return true;
        },
        currentSk: () => activeSk,
        currentSkVaultId: () => activeSkVaultId,
        rehydrateSkWithPin: (candidatePin) async {
          expect(candidatePin, '123456');
          events
            ..add('zk_username_init_401')
            ..add('stored_vlt_handle_login_init_succeeded')
            ..add('opaque_finish_login_succeeded')
            ..add('zk_login_finalize_called');
          activeSk = _key(21);
          activeSkVaultId = 'beneficiary-vault';
          return activeSk;
        },
      );

      expect(result.status, InheritanceRevealLocalKeyStatus.ready);
      expect(result.reason, 'rehydrated_sk_ready');
      expect(await _marker(result.skVault!), 21);
      events.add('ciphertext_retrieval_allowed');

      expect(events, [
        'pin_cache_missing',
        'legacy_auth_login_succeeded',
        'zk_username_init_401',
        'stored_vlt_handle_login_init_succeeded',
        'opaque_finish_login_succeeded',
        'zk_login_finalize_called',
        'ciphertext_retrieval_allowed',
      ]);
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

    test('repair rotation exits before backend ciphertext retrieval', () {
      final idx = mainSource.indexOf(
        'Future<void> _beneficiaryRevealCredentials',
      );
      expect(idx, greaterThan(-1));
      final window =
          mainSource.substring(idx, (idx + 8500).clamp(0, mainSource.length));

      final repairIdx = window.indexOf('_repairInheritanceZkAfterPin');
      final needsOwnerIdx = window.indexOf('requiresOwnerReencryption');
      final returnAfterNeedsOwnerIdx = window.indexOf('return;', needsOwnerIdx);
      final retrieveIdx = window.indexOf('retrieveInheritanceCredentials');

      expect(repairIdx, greaterThan(-1));
      expect(needsOwnerIdx, greaterThan(repairIdx));
      expect(returnAfterNeedsOwnerIdx, greaterThan(needsOwnerIdx));
      expect(retrieveIdx, greaterThan(returnAfterNeedsOwnerIdx));
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

    test('auth hydration preserves server and legacy-adopted vault handles',
        () {
      expect(mainSource.contains("me['vault_handle']"), isTrue);
      expect(
        mainSource.contains(
          "NativeSecureStore.writeString('last_vault_handle', handle)",
        ),
        isTrue,
      );
      expect(
        mainSource.contains('legacy_adopt.readCachedVaultHandle()'),
        isTrue,
      );
    });

    test('PIN reauth forwards the typed OPAQUE vault handle into session state',
        () {
      expect(mainSource.contains('loginResult.vaultHandle'), isTrue);
      expect(
        mainSource.contains('vaultHandleValue: loginResult.vaultHandle'),
        isTrue,
      );
    });

    test('PIN reauth restores and publishes ZK sk_vault when handle exists',
        () {
      final idx = mainSource.indexOf(
        'Future<LoginResult?> _restoreZkSessionKeysAfterPin',
      );
      expect(idx, greaterThan(-1));
      final window =
          mainSource.substring(idx, (idx + 4200).clamp(0, mainSource.length));
      expect(window.contains('ZkAuthService(_zkHttpPost)'), isTrue);
      expect(window.contains('vaultHandle: loginId.vaultHandle'), isTrue);
      expect(window.contains('zk_sk_store.ZkActiveSkVault.set('), isTrue);
      expect(window.contains('expected_role'), isTrue);

      final verifyIdx = mainSource.indexOf('Future<bool> verifyPin');
      final verifyWindow = mainSource.substring(
        verifyIdx,
        (verifyIdx + 5200).clamp(0, mainSource.length),
      );
      expect(
        verifyWindow.contains('_restoreZkSessionKeysAfterPin('),
        isTrue,
      );
      expect(
        verifyWindow.contains('restoreZkSessionKeys &&'),
        isTrue,
      );
      expect(
        verifyWindow.contains("reason: 'verify_pin'"),
        isTrue,
      );
    });

    test('reveal path explicitly asks verifyPin to restore sk_vault', () {
      final idx = mainSource.indexOf(
        'Future<void> _beneficiaryRevealCredentials',
      );
      expect(idx, greaterThan(-1));
      final window =
          mainSource.substring(idx, (idx + 2300).clamp(0, mainSource.length));
      expect(
        window.contains('restoreZkSessionKeys: true'),
        isTrue,
      );
    });

    test('ZK login stores backend-authenticated handle, not guessed handle',
        () {
      final src = File('lib/services/zk_auth_service.dart').readAsStringSync();
      final idx = src.indexOf('Future<LoginResult> loginVault');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 7000).clamp(0, src.length));
      expect(
        window.contains("finalizeResponse['vault_handle'] as String?"),
        isTrue,
      );
      expect(window.contains('vaultHandle: authenticatedHandle'), isTrue);
    });

    test('ZK auth POSTs include current device id for finalize', () {
      final idx =
          mainSource.indexOf('Future<Map<String, dynamic>> _zkHttpPost');
      expect(idx, greaterThan(-1));
      final window =
          mainSource.substring(idx, (idx + 1100).clamp(0, mainSource.length));
      expect(window.contains('apiClientDeviceId()'), isTrue);
      expect(window.contains("headers['X-Device-Id']"), isTrue);
      expect(window.contains("path == '/auth/zk-login-finalize'"), isTrue);
      expect(window.contains("'device_id'"), isTrue);
    });

    test('successful ZK login and unlock store the result vaultHandle', () {
      final occurrences =
          'vaultHandleValue: loginResult.vaultHandle'.allMatches(mainSource);
      expect(occurrences.length, greaterThanOrEqualTo(2));
      expect(mainSource.contains('vaultHandleValue: loginResult.displayName'),
          isFalse);
    });

    test('account switch clears vaultHandle; ordinary logout retains auth hint',
        () {
      final idx = mainSource.indexOf('Future<void> clearSession');
      expect(idx, greaterThan(-1));
      final window =
          mainSource.substring(idx, (idx + 4200).clamp(0, mainSource.length));
      expect(window.contains('rememberedVaultHandle'), isTrue);
      expect(window.contains('vaultHandle = rememberedVaultHandle'), isTrue);
      expect(
        window.contains("NativeSecureStore.deleteString('last_vault_handle')"),
        isTrue,
      );
      expect(mainSource.contains('clearSession(keepLastVaultName: false)'),
          isTrue);
    });

    test('reveal rehydrate falls back to legacy adoption handle cache', () {
      final idx = mainSource.indexOf(
        'Future<SecretKey?> _rehydrateInheritanceSkVault',
      );
      expect(idx, greaterThan(-1));
      final window =
          mainSource.substring(idx, (idx + 2200).clamp(0, mainSource.length));
      expect(window.contains('cachedAdoptedHandle'), isTrue);
      expect(window.contains('_nonEmptyTrimmed(app.vaultHandle)'), isTrue);
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
