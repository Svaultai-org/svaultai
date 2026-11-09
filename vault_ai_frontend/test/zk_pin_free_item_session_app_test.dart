import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/session_termination.dart';
import 'package:vault_ai_frontend/services/zk_pin_free_item_read_session.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    SessionTermination.instance.resetForTests();
    ZkPinFreeItemReadSession.instance.clear();
    ZkActiveMvk.clear();
  });
  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
    ZkPinFreeItemReadSession.instance.clear();
    ZkActiveMvk.clear();
    SessionTermination.instance.resetForTests();
  });

  test('lock and vault replacement cannot reuse an OPAQUE read offer',
      () async {
    final app = AppState();
    try {
      await app.setSession(
        token: 'first-opaque-session',
        vaultIdValue: 'first-synthetic-vault',
        vaultNameValue: 'First vault',
        vaultHandleValue: 'first-synthetic-handle',
        pinFreeLegacyItemRead: true,
      );
      expect(
          ZkPinFreeItemReadSession.instance
              .activeForToken('first-opaque-session'),
          isTrue);
      app.unlocked = false;
      expect(
          ZkPinFreeItemReadSession.instance
              .activeForToken('first-opaque-session'),
          isFalse);
      expect(
          ZkPinFreeItemReadSession.instance
              .wasOfferedForToken('first-opaque-session'),
          isTrue);
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('first-opaque-session'),
          kEnableKeylessSavedItemRead);

      await app.setSession(
        token: 'second-session',
        vaultIdValue: 'second-synthetic-vault',
        vaultNameValue: 'Second vault',
      );
      expect(
          ZkPinFreeItemReadSession.instance
              .wasOfferedForToken('first-opaque-session'),
          isFalse);
      expect(ZkPinFreeItemReadSession.instance.activeForToken('second-session'),
          isFalse);
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('second-session'),
          isFalse);
      await app.clearSession();
    } finally {
      app.dispose();
    }
  });

  test('unoffered OPAQUE marker follows only its current bearer', () async {
    final app = AppState();
    try {
      await app.setSession(
        token: 'first-opaque-session',
        vaultIdValue: 'first-synthetic-vault',
        vaultNameValue: 'First vault',
        vaultHandleValue: 'first-synthetic-handle',
      );
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('first-opaque-session'),
          kEnableKeylessSavedItemRead);
      await app.setSession(
        token: 'replacement-legacy-session',
        vaultIdValue: 'second-synthetic-vault',
        vaultNameValue: 'Second vault',
      );
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('first-opaque-session'),
          isFalse);
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('replacement-legacy-session'),
          isFalse);
      await app.clearSession();
    } finally {
      app.dispose();
    }
  });

  test('restored OPAQUE token stays fenced before and after validation',
      () async {
    await NativeSecureStore.writeString('session_token', 'restored-opaque');
    await NativeSecureStore.writeString('last_vault_name', 'Restored vault');
    await NativeSecureStore.writeString('last_vault_handle', 'stale-handle');
    final validationStarted = Completer<void>();
    final reply = Completer<Map<String, dynamic>>();
    final app = AppState(sessionValidator: (token) {
      expect(token, 'restored-opaque');
      validationStarted.complete();
      return reply.future;
    });
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{"items":[]}', 200);
      }),
    );
    try {
      final hydration = app.hydrate();
      await validationStarted.future;
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('restored-opaque'),
          isTrue);
      await expectLater(
          client.listVaultSecureItems(
            vaultName: 'Restored vault',
            pin: 'synthetic-pin',
            authToken: 'restored-opaque',
          ),
          throwsStateError);
      reply.complete(<String, dynamic>{
        'vault_id': 'restored-vault-id',
        'vault_handle': 'authoritative-handle',
        'zk': true,
      });
      await hydration;
      expect(app.vaultHandle, 'authoritative-handle');
      await expectLater(
          client.getVaultSecureItem(
            vaultName: 'Restored vault',
            pin: 'synthetic-pin',
            authToken: 'restored-opaque',
            service: 'Synthetic',
            itemType: 'login',
          ),
          throwsStateError);
      expect(requests, isEmpty);
    } finally {
      await app.clearSession();
      app.dispose();
    }
  }, skip: !kEnableKeylessSavedItemRead);

  test('validated legacy session discards a stale persisted handle', () async {
    await NativeSecureStore.writeString('session_token', 'legacy-session');
    await NativeSecureStore.writeString('last_vault_name', 'Older vault');
    await NativeSecureStore.writeString('last_vault_handle', 'stale-handle');
    final app = AppState(
        sessionValidator: (_) async => <String, dynamic>{
              'vault_id': 'older-vault-id',
              'vault_handle': null,
              'zk': false,
            });
    try {
      await app.hydrate();
      expect(app.vaultHandle, isNull);
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('legacy-session'),
          isFalse);
    } finally {
      await app.clearSession();
      app.dispose();
    }
  }, skip: !kEnableKeylessSavedItemRead);

  test('server handle marks a restored token without a cached handle',
      () async {
    await NativeSecureStore.writeString('session_token', 'restored-opaque');
    await NativeSecureStore.writeString('last_vault_name', 'Restored vault');
    final app = AppState(
        sessionValidator: (_) async => <String, dynamic>{
              'vault_id': 'restored-vault-id',
              'vault_handle': 'server-handle',
              'zk': true,
            });
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{"items":[]}', 200);
      }),
    );
    try {
      await app.hydrate();
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('restored-opaque'),
          isTrue);
      await expectLater(
          client.getVaultSecureItem(
            vaultName: 'Restored vault',
            pin: 'synthetic-pin',
            authToken: 'restored-opaque',
            service: 'Synthetic',
            itemType: 'login',
          ),
          throwsStateError);
      expect(requests, isEmpty);
    } finally {
      await app.clearSession();
      app.dispose();
    }
  }, skip: !kEnableKeylessSavedItemRead);

  test('adoption marks the current bearer before another saved-item read',
      () async {
    final app = AppState(
        sessionValidator: (_) async => <String, dynamic>{
              'vault_id': 'adopted-vault-id',
              'vault_handle': null,
              'zk': false,
            });
    final requests = <http.Request>[];
    final client = VaultAIClient(
      baseUrl: 'https://synthetic.example',
      httpClient: MockClient((request) async {
        requests.add(request);
        return http.Response('{"items":[]}', 200);
      }),
    );
    try {
      await app.setSession(
        token: 'adopting-session',
        vaultIdValue: 'adopted-vault-id',
        vaultNameValue: 'Adopted vault',
      );
      expect(
          app.recordAdoptedVaultHandle(
            token: 'adopting-session',
            expectedVaultId: 'adopted-vault-id',
            expectedVaultName: 'Adopted vault',
            handle: 'new-opaque-handle',
          ),
          isTrue);
      // A lagging validation response must not undo the in-session adoption.
      await app.validateCurrentSession();
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('adopting-session'),
          isTrue);
      ZkActiveMvk.clear();
      await expectLater(
          client.listVaultSecureItems(
            vaultName: 'Adopted vault',
            pin: 'synthetic-pin',
            authToken: 'adopting-session',
          ),
          throwsStateError);
      await expectLater(
          client.getVaultSecureItem(
            vaultName: 'Adopted vault',
            pin: 'synthetic-pin',
            authToken: 'adopting-session',
            service: 'Synthetic',
            itemType: 'login',
          ),
          throwsStateError);
      expect(requests, isEmpty);
      await app.setSession(
        token: 'later-legacy-session',
        vaultIdValue: 'later-vault-id',
        vaultNameValue: 'Later vault',
      );
      expect(
          ZkPinFreeItemReadSession.instance
              .privateVaultForToken('later-legacy-session'),
          isFalse);
      await client.listVaultSecureItems(
        vaultName: 'Later vault',
        pin: 'synthetic-pin',
        authToken: 'later-legacy-session',
      );
      expect(requests.map((request) => request.url.path),
          <String>['/list-secure-items']);
    } finally {
      await app.clearSession();
      app.dispose();
    }
  }, skip: !kEnableKeylessSavedItemRead);
}
