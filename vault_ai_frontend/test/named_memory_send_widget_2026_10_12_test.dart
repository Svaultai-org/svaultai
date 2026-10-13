import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/session_termination.dart'
    as sessions;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart'
    as hierarchy;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

const _phrase =
    'Save a new memory with title QA-TEST-B1-memory and content: QA-TEST B1 content alpha';

class _FixtureApp extends AppState {
  @override
  Future<void> refreshVaultStats() async {}
}

Future<AppState> _fixture() async {
  final app = _FixtureApp()
    ..sessionToken = 'synthetic-named-memory-token'
    ..vaultId = 'synthetic-named-memory-vault'
    ..vaultName = 'Synthetic named memory'
    ..vaultHandle = 'synthetic-named-memory-handle'
    ..displayName = 'QA'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
  // This VM is not an Android native runtime. Use the real software PBKDF2
  // only to seed this synthetic fixture, then restore the requested platform
  // before rendering. The assertions cover widget dispatch/AES-GCM, not
  // native OPAQUE or a store-delivered installation.
  final requestedPlatform = debugDefaultTargetPlatformOverride;
  debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
  try {
    await deriveAndInstallCryptoContext(
      vaultId: app.vaultId!,
      vaultName: app.vaultName!,
      pin: '123456',
      pinSaltBase64: base64Encode(List.filled(16, 4)),
      iterations: 1,
      source: 'named-memory-regression-fixture',
    );
  } finally {
    debugDefaultTargetPlatformOverride = requestedPlatform;
  }
  ZkActiveMvk.set(
    mvk: SecretKey(List.filled(32, 4)),
    vaultId: app.vaultId!,
    vaultHandle: app.vaultHandle!,
  );
  app.unlocked = true;
  return app;
}

Widget _dashboard(AppState app) => ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        theme: ThemeData.dark(useMaterial3: true),
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        routes: {'/pin': (_) => const Text('Synthetic PIN route')},
        home: const ChatDashboardPage(),
      ),
    );

Future<void> _send(WidgetTester tester, String text) async {
  // Let the preceding save-confirmation toast finish; do not tap through
  // an overlay or suppress a failed hit test to make this fixture pass.
  await tester.pump(const Duration(seconds: 5));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('chat_composer_field')), text);
  await tester.pump();
  await tester.tap(find.byKey(const Key('composer_send_button')));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    sessions.SessionTermination.instance.reset();
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
    sessions.SessionTermination.instance.reset();
  });

  testWidgets(
    'real Send saves an encrypted named memory once, recalls it and warns on duplicate',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(430, 932));
      final app = (await tester.runAsync(_fixture))!;
      final requests = <String>[];
      final records = <Map<String, dynamic>>[];
      setApiClientDeviceId('synthetic-named-memory-device');
      try {
        await http.runWithClient(() async {
          await tester.pumpWidget(_dashboard(app));
          await tester.pumpAndSettle();
          expect(find.text('Synthetic PIN route'), findsNothing);
          await _send(tester, _phrase);
          expect(records, hasLength(1));
          final key = await tester.runAsync(() =>
              hierarchy.VaultKeyHierarchy(ZkActiveMvk.current()!).memoryKey());
          final plaintext = await tester.runAsync(() => hierarchy.aesGcmUnwrap(
                key!,
                hierarchy.b64urlDecode(
                    records.single['payload_ciphertext'] as String),
              ));
          final payload =
              jsonDecode(utf8.decode(plaintext!)) as Map<String, dynamic>;
          expect(payload['title'], 'QA-TEST-B1-memory');
          expect(payload['value'], 'QA-TEST B1 content alpha');
          expect(payload.containsKey('username'), isFalse);
          expect(payload.containsKey('password'), isFalse);
          expect(records.single['replace_existing'], isFalse);
          expect(requests.where((r) => r.contains('/chat')), isEmpty);
          expect(find.textContaining('Memory saved securely.'), findsOneWidget);

          await _send(tester, 'What do you remember about QA-TEST-B1-memory?');
          expect(
              find.textContaining(
                  'I remember "QA-TEST-B1-memory": QA-TEST B1 content alpha'),
              findsOneWidget);
          expect(records, hasLength(1));
          expect(requests.where((r) => r.contains('/chat')), isEmpty);

          final ciphertext = records.single['payload_ciphertext'];
          await _send(tester, _phrase);
          expect(records, hasLength(1));
          expect(records.single['payload_ciphertext'], ciphertext);
          expect(
              find.textContaining('A memory with this title already exists.'),
              findsOneWidget);
          expect(
              requests
                  .where((r) => r == 'POST /vault/ciphertext/vault-ai-memory'),
              hasLength(1));
          await _send(tester,
              'Save a memory titled Too long with content: ${'C' * 501}');
          expect(find.textContaining('Use the Memory page for longer notes.'),
              findsOneWidget);
          expect(records, hasLength(1));
          expect(records.single['payload_ciphertext'], ciphertext);
          await _send(tester, 'Create a memory titled Incomplete');
          expect(
              find.text(
                  'Add a memory title and content first. Nothing was saved.'),
              findsOneWidget);
          expect(records, hasLength(1));
          expect(requests.where((r) => r.contains('/chat')), isEmpty);
          expect(tester.takeException(), isNull);
        },
            () => MockClient((request) async {
                  final route = '${request.method} ${request.url.path}';
                  requests.add(route);
                  final Object body;
                  switch (route) {
                    case 'POST /list-files':
                      body = {'files': []};
                      break;
                    case 'GET /folders':
                      body = {'path': '', 'folders': [], 'files': []};
                      break;
                    case 'POST /list-secure-items':
                      body = {'items': []};
                      break;
                    case 'GET /vault/ciphertext/vault-items':
                      body = [];
                      break;
                    case 'GET /vault/ciphertext/vault-ai-memory':
                      body = records
                          .map((r) => <String, dynamic>{
                                'memory_id': r['memory_id'],
                                'memory_type': r['memory_type'],
                                'payload_ciphertext': r['payload_ciphertext'],
                              })
                          .toList();
                      break;
                    case 'POST /vault/ciphertext/vault-ai-memory':
                      records.add(Map<String, dynamic>.from(
                          jsonDecode(request.body) as Map));
                      body = {
                        'memory_id': records.last['memory_id'],
                        'duplicate': false
                      };
                      break;
                    default:
                      throw StateError(
                          'Unexpected in-process fixture request: $route');
                  }
                  return http.Response(jsonEncode(body), 200,
                      headers: {'content-type': 'application/json'});
                }));
      } finally {
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pump();
        app.unlocked = false;
        app.dispose();
        ZkActiveMvk.clear();
        VaultCryptoRegistry.clear(reason: 'named-memory-regression-cleanup');
        setApiClientDeviceId('');
        await tester.binding.setSurfaceSize(null);
      }
    },
    variant:
        TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android}),
  );
}
