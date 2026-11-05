import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

class _App extends AppState {
  int statsRefreshCalls = 0;

  @override
  Future<void> refreshVaultStats() async {
    statsRefreshCalls++;
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('com.llfbandit.record/messages'),
      (_) async => null,
    );
  });
  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('com.llfbandit.record/messages'),
      null,
    );
  });

  testWidgets('manual Create and Edit keep every saved-item request PIN-free',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final app = _App()
      ..sessionToken = 'synthetic-write-session'
      ..vaultId = 'synthetic-write-vault'
      ..vaultName = 'Synthetic write vault'
      ..vaultHandle = 'synthetic-write-handle'
      ..displayName = 'QA'
      ..authed = true
      ..billingLoadState = BillingLoadState.loaded
      ..billingIncludedBytes = kVaultStorageLimitBytes
      ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
    final oldPlatform = debugDefaultTargetPlatformOverride;
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await tester.runAsync(() => deriveAndInstallCryptoContext(
            vaultId: app.vaultId!,
            vaultName: app.vaultName!,
            pin: '123456',
            pinSaltBase64: base64Encode(List<int>.filled(16, 7)),
            iterations: 1,
            source: 'synthetic-private-write-ui',
          ));
    } finally {
      debugDefaultTargetPlatformOverride = oldPlatform;
    }
    final mvk = SecretKey(List<int>.filled(32, 71));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: app.vaultId!,
      vaultHandle: app.vaultHandle!,
    );
    app.unlocked = true;
    setApiClientDeviceId('synthetic-write-device');
    final rows = <Map<String, dynamic>>[];
    final requests = <http.Request>[];
    var nextId = 51;
    final mock = MockClient((request) async {
      requests.add(request);
      final path = request.url.path;
      if (request.method == 'GET' && path == '/vault/items/metadata') {
        return http.Response(
            jsonEncode(<String, dynamic>{
              'records': <Map<String, dynamic>>[
                for (final row in rows)
                  <String, dynamic>{
                    'item_id': row['item_id'],
                    'item_type_ciphertext': row['item_type_ciphertext'],
                    'service_ciphertext': row['service_ciphertext'],
                    'is_legacy': false,
                    'has_v2_payload': true,
                  },
              ],
              'has_more': false,
              'next_after_item_id': rows.isEmpty ? 0 : rows.last['item_id'],
            }),
            200);
      }
      if (request.method == 'GET' && path == '/vault/ciphertext/vault-items') {
        return http.Response(jsonEncode(rows), 200);
      }
      if (request.method == 'POST' && path == '/vault/ciphertext/vault-items') {
        final body = Map<String, dynamic>.from(jsonDecode(request.body) as Map);
        final id = body['item_id'] as int? ?? nextId++;
        final prior = rows.where((row) => row['item_id'] == id).toList();
        rows.removeWhere((row) => row['item_id'] == id);
        rows.add(<String, dynamic>{
          ...body,
          'item_id': id,
          'title_indexed': true,
          'title_revision':
              prior.isEmpty ? 0 : (prior.single['title_revision'] as int) + 1,
        });
        return http.Response(
            jsonEncode(<String, dynamic>{
              'item_id': id,
              'created': body['item_id'] == null,
            }),
            200);
      }
      if (request.method == 'POST' && path == '/list-files') {
        return http.Response('{"files":[]}', 200);
      }
      if (request.method == 'GET' && path == '/folders') {
        return http.Response('{"path":"","folders":[],"files":[]}', 200);
      }
      return http.Response('{"detail":"unexpected_fixture_route"}', 599);
    });
    try {
      await http.runWithClient(() async {
        await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
          value: app,
          child: MaterialApp(
            theme: ThemeData.dark(useMaterial3: true),
            locale: const Locale('en'),
            localizationsDelegates: AppLocalizations.localizationsDelegates,
            supportedLocales: AppLocalizations.supportedLocales,
            routes: {'/pin': (_) => const Text('Synthetic PIN route')},
            home: const ChatDashboardPage(),
          ),
        ));
        await tester.pumpAndSettle();
        requests.clear(); // Only the explicit Create/Edit flow is measured.
        final statsBeforeSave = app.statsRefreshCalls;
        await tester.tap(find.byKey(const Key('top_nav_create_button')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('create_choice_login')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('secure_item_edit_title')),
            'Synthetic account');
        await tester.enterText(
            find.byKey(const Key('secure_item_edit_username')),
            'synthetic-user');
        await tester.enterText(
            find.byKey(const Key('secure_item_edit_password')),
            'synthetic-secret-marker');
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();
        expect(find.byType(LoginsPage), findsOneWidget);
        expect(rows, hasLength(1));

        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
        final edit = find.widgetWithText(OutlinedButton, 'Edit').first;
        await tester.ensureVisible(edit);
        await tester.pumpAndSettle();
        await tester.tap(edit);
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('secure_item_edit_title')),
            'Synthetic renamed account');
        await tester.enterText(
            find.byKey(const Key('secure_item_edit_password')),
            'synthetic-updated-secret-marker');
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();
        expect(rows, hasLength(1));
        expect(app.statsRefreshCalls, statsBeforeSave);
        final writes = requests.where((request) =>
            request.method == 'POST' &&
            request.url.path == '/vault/ciphertext/vault-items');
        expect(writes, hasLength(2));
        for (final request in requests) {
          expect(request.body, isNot(contains('"pin"')));
          expect(request.body, isNot(contains('123456')));
          expect(request.body, isNot(contains('synthetic-secret-marker')));
          expect(request.body, isNot(contains('Synthetic account')));
          expect(request.headers['x-device-id'], 'synthetic-write-device');
        }
        expect(
            requests.any((r) => <String>{
                  '/list-secure-items',
                  '/get-secure-item',
                  '/update-secure-item',
                  '/vault-stats',
                  '/chat',
                }.contains(r.url.path)),
            isFalse);
        expect(tester.takeException(), isNull);
      }, () => mock);
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      app.unlocked = false;
      app.dispose();
      ZkActiveMvk.clear();
      VaultCryptoRegistry.clear(reason: 'synthetic-private-write-ui-cleanup');
      setApiClientDeviceId('');
      await tester.binding.setSurfaceSize(null);
    }
  }, skip: !(kEnableKeylessSavedItemRead && kEnableKeylessSavedItemWrite));
}
