import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_active_sk_vault.dart';
import 'package:provider/provider.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
    ZkActiveMvk.clear();
    ZkActiveSkVault.clear();
    VaultCryptoRegistry.clear(reason: 'private_unlock_test');
  });

  tearDown(() {
    NativeSecureStore.useSharedPreferencesForTesting = false;
    ZkActiveMvk.clear();
    ZkActiveSkVault.clear();
    VaultCryptoRegistry.clear(reason: 'private_unlock_test');
  });

  test('private build requires all keyless feature gates', () {
    expect(kPrivateOnlyUnlockEnabled, isTrue);
    expect(kZkPrivateOnlyClientReady, isTrue);
    expect(kPrivateOnlyTransportRejectPin, isTrue);
    expect(
        legacyAuthFallbackPermitted(
          opaqueLookupMissed: true,
          isHandle: false,
        ),
        isFalse);
  });

  for (final origin in ZkPrivateUnlockOrigin.values) {
    test('${origin.name} OPAQUE result retains MVK/Sk without a PIN context',
        () async {
      final app = AppState();
      final mvk = SecretKey(List<int>.filled(32, 11));
      final sk = SecretKey(List<int>.filled(32, 22));
      const token = 'synthetic-session';
      const vaultId = 'synthetic-vault';
      const vaultName = 'Synthetic vault';
      const handle = 'VLT-synthetic';
      try {
        await app.setSession(
          token: token,
          vaultIdValue: vaultId,
          vaultNameValue: vaultName,
          vaultHandleValue: handle,
        );
        installZkPrivateOnlyUnlockKeys(
          app: app,
          origin: origin,
          sessionToken: token,
          vaultId: vaultId,
          vaultName: vaultName,
          vaultHandle: handle,
          mvk: mvk,
          skVault: sk,
        );
        app.markUnlocked();
        expect(app.unlocked, isTrue);
        expect(identical(ZkActiveMvk.current(), mvk), isTrue);
        expect(identical(ZkActiveSkVault.current(), sk), isTrue);
        expect(VaultCryptoRegistry.current, isNull);
        expect(zkPrivateUnlockCredentialStateForTesting(), {
          'pin_cache_entries': 0,
          'legacy_key_entries': 0,
          'has_pbkdf2_context': false,
        });
        expect(
            await app.applyFreshKdfMetadata(
              pinSaltBase64: 'unused',
              iterations: 100000,
            ),
            isFalse);

        final sent = <http.Request>[];
        final client = VaultAIClient(
          baseUrl: 'https://synthetic.invalid',
          httpClient: MockClient((request) async {
            sent.add(request);
            return http.Response('[]', 200);
          }),
        );
        final items = await client.listZkVaultItemsOnly(authToken: token);
        expect(items['items'], isEmpty);
        expect(sent, hasLength(1));
        expect(sent.single.url.path, '/vault/ciphertext/vault-items');
        expect(sent.single.body.contains('pin'), isFalse);

        await expectLater(
          client.authLogin(vaultName: vaultName, pin: '123456'),
          throwsStateError,
        );
        expect(sent, hasLength(1),
            reason: 'A legacy PIN request must stop before HTTP.');
      } finally {
        await app.clearSession();
        app.dispose();
      }
    });
  }

  test('private install rejects a superseded session without publishing keys',
      () async {
    final app = AppState();
    try {
      await app.setSession(
        token: 'current-token',
        vaultIdValue: 'current-vault',
        vaultNameValue: 'Current vault',
        vaultHandleValue: 'VLT-current',
      );
      expect(
        () => installZkPrivateOnlyUnlockKeys(
          app: app,
          origin: ZkPrivateUnlockOrigin.login,
          sessionToken: 'old-token',
          vaultId: 'current-vault',
          vaultName: 'Current vault',
          vaultHandle: 'VLT-current',
          mvk: SecretKey(List<int>.filled(32, 33)),
          skVault: SecretKey(List<int>.filled(32, 44)),
        ),
        throwsStateError,
      );
      expect(ZkActiveMvk.current(), isNull);
      expect(ZkActiveSkVault.current(), isNull);
      expect(app.unlocked, isFalse);
    } finally {
      await app.clearSession();
      app.dispose();
    }
  });

  test('post-login list and stats refresh errors do not revoke private unlock',
      () async {
    final app = AppState();
    try {
      await app.setSession(
        token: 'refresh-token',
        vaultIdValue: 'refresh-vault',
        vaultNameValue: 'Refresh vault',
        vaultHandleValue: 'VLT-refresh',
      );
      installZkPrivateOnlyUnlockKeys(
        app: app,
        origin: ZkPrivateUnlockOrigin.login,
        sessionToken: 'refresh-token',
        vaultId: 'refresh-vault',
        vaultName: 'Refresh vault',
        vaultHandle: 'VLT-refresh',
        mvk: SecretKey(List<int>.filled(32, 55)),
        skVault: SecretKey(List<int>.filled(32, 66)),
      );
      app.markUnlocked();
      await app.refreshAvailableVaults();
      await app.refreshNotifications();
      await app.refreshVaultStats();
      expect(app.unlocked, isTrue);
      expect(
          zkPrivateUnlockCredentialStateForTesting()['pin_cache_entries'], 0);
    } finally {
      await app.clearSession();
      app.dispose();
    }
  });

  testWidgets('private dashboard opens Files and Logins without a PIN request',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(1200, 900));
    final app = AppState();
    final requests = <http.Request>[];
    try {
      await app.setSession(
        token: 'dashboard-token',
        vaultIdValue: 'dashboard-vault',
        vaultNameValue: 'Dashboard vault',
        vaultHandleValue: 'VLT-dashboard',
      );
      installZkPrivateOnlyUnlockKeys(
        app: app,
        origin: ZkPrivateUnlockOrigin.login,
        sessionToken: 'dashboard-token',
        vaultId: 'dashboard-vault',
        vaultName: 'Dashboard vault',
        vaultHandle: 'VLT-dashboard',
        mvk: SecretKey(List<int>.filled(32, 77)),
        skVault: SecretKey(List<int>.filled(32, 88)),
      );
      app.markUnlocked();
      final mock = MockClient((request) async {
        requests.add(request);
        switch (request.url.path) {
          case '/vault/ciphertext/vault-items':
            return http.Response('[]', 200);
          case '/vault/items/metadata':
            return http.Response(
                '{"records":[],"has_more":false,"next_after_item_id":0}', 200);
          case '/vault/files/metadata':
            return http.Response(
                '{"records":[],"has_more":false,"next_after_file_id":""}', 200);
          case '/vault/file-v2':
            return http.Response('{"files":[]}', 200);
          case '/folders':
            return http.Response('{"path":"","folders":[],"files":[]}', 200);
          default:
            return http.Response('{}', 404);
        }
      });
      await http.runWithClient(() async {
        await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
          value: app,
          child: MaterialApp(
            theme: ThemeData.dark(useMaterial3: true),
            locale: const Locale('en'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            home: const ChatDashboardPage(),
          ),
        ));
        await tester.pumpAndSettle();
        await tester.tap(find.byIcon(Icons.menu_rounded));
        await tester.pumpAndSettle();
        final files = find.byKey(const Key('sidebar_section_files'));
        await tester.ensureVisible(files);
        await tester.tap(files);
        await tester.pumpAndSettle();
        expect(app.unlocked, isTrue);
        await tester.tap(find.byIcon(Icons.menu_rounded));
        await tester.pumpAndSettle();
        final logins = find.byKey(const Key('sidebar_section_logins'));
        await tester.ensureVisible(logins);
        await tester.tap(logins);
        await tester.pumpAndSettle();
        expect(app.unlocked, isTrue);
      }, () => mock);
      expect(requests.any((r) => r.body.contains('"pin"')), isFalse);
      expect(requests.any((r) => r.url.path == '/list-files'), isFalse);
      expect(requests.any((r) => r.url.path == '/list-secure-items'), isFalse);
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await app.clearSession();
      app.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  });

  test('nested and multipart raw PIN fields fail before transport', () {
    expect(
      () => assertPrivateOnlyPinFreeBody('{"pin":"123456"}'),
      throwsStateError,
    );
    expect(
      () => assertPrivateOnlyPinFreeBody({
        'records': [
          {
            'credential': {'PIN': '123456'}
          }
        ]
      }),
      throwsStateError,
    );
    expect(
      () => assertPrivateOnlyPinFreeBody({'pin': ''}),
      throwsStateError,
    );
    expect(
      () => assertPrivateOnlyPinFreeBody({'pin_salt': 'public salt'}),
      returnsNormally,
    );
  });
}
