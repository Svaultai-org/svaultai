import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/native_secure_store.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_active_sk_vault.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';

class _App extends AppState {
  @override
  Future<void> refreshVaultStats() async {}
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    NativeSecureStore.useSharedPreferencesForTesting = true;
  });
  tearDown(() => NativeSecureStore.useSharedPreferencesForTesting = false);

  testWidgets(
      'private Logins view, copy and confirmed delete need no PIN cache',
      (tester) async {
    String? copiedValue;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copiedValue = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
    await tester.binding.setSurfaceSize(const Size(1200, 900));
    final app = _App()
      ..displayName = 'QA'
      ..billingLoadState = BillingLoadState.loaded
      ..billingIncludedBytes = kVaultStorageLimitBytes
      ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
    await app.setSession(
      token: 'synthetic-session',
      vaultIdValue: 'synthetic-vault',
      vaultNameValue: 'Synthetic vault',
      vaultHandleValue: 'synthetic-handle',
    );
    final mvk = SecretKey(List<int>.filled(32, 59));
    ZkActiveMvk.set(
      mvk: mvk,
      vaultId: app.vaultId!,
      vaultHandle: app.vaultHandle!,
    );
    ZkActiveSkVault.set(
      skVault: SecretKey(List<int>.filled(32, 61)),
      vaultId: app.vaultId!,
    );
    VaultCryptoRegistry.clear(reason: 'private_saved_item_ui_test');
    st.SessionTermination.instance.bindSession(app.sessionToken!);
    PrivateZkPinTransportSession.bind(app.sessionToken!);
    app.markUnlocked();
    expect(app.unlocked, isTrue);
    setApiClientDeviceId('synthetic-device');
    final key = await VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String value) async =>
        b64urlEncode(await aesGcmWrap(key, utf8.encode(value)));
    final encrypted = <String, dynamic>{
      'item_id': 42,
      'item_type_ciphertext': await wrap('login'),
      'service_ciphertext': await wrap('Synthetic account'),
      'payload_ciphertext': await wrap(jsonEncode({
        'fields': {
          'username': 'synthetic-user',
          'password': 'synthetic-secret'
        },
      })),
    };
    final secondEncrypted = <String, dynamic>{
      'item_id': 43,
      'item_type_ciphertext': await wrap('login'),
      'service_ciphertext': await wrap('Second account'),
      'payload_ciphertext': await wrap(jsonEncode({
        'fields': {'username': 'second-user', 'password': 'second-secret'},
      })),
    };
    final legacyType = await wrap('login');
    final legacyService = await wrap('Older account');
    var exists = true;
    var secondExists = true;
    final requests = <http.Request>[];
    final mock = MockClient((request) async {
      requests.add(request);
      switch ('${request.method} ${request.url.path}') {
        case 'GET /vault/ciphertext/vault-items':
          return http.Response(
              jsonEncode([
                if (exists) encrypted,
                if (secondExists) secondEncrypted,
              ]),
              200);
        case 'GET /vault/items/metadata':
          return http.Response(
              jsonEncode({
                'records': [
                  {
                    'item_id': 77,
                    'item_type_ciphertext': legacyType,
                    'service_ciphertext': legacyService,
                    'is_legacy': true,
                    'has_v2_payload': false,
                  },
                ],
                'has_more': false,
                'next_after_item_id': 77,
              }),
              200);
        case 'DELETE /vault/ciphertext/vault-items/42':
          exists = false;
          return http.Response('{"status":"deleted","item_id":42}', 200);
        case 'DELETE /vault/ciphertext/vault-items/43':
          secondExists = false;
          return http.Response('{"status":"deleted","item_id":43}', 200);
        case 'GET /folders':
          return http.Response('{"path":"","folders":[],"files":[]}', 200);
        case 'GET /vault/files/metadata':
          return http.Response(
              '{"records":[],"has_more":false,"next_after_file_id":""}', 200);
        case 'GET /vault/file-v2':
          return http.Response('{"files":[]}', 200);
        default:
          return http.Response('{}', 404);
      }
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
        expect(app.unlocked, isTrue);
        expect(find.byType(ChatDashboardPage), findsOneWidget);
        await tester.tap(find.byIcon(Icons.menu_rounded));
        await tester.pumpAndSettle();
        final logins = find.byKey(const Key('sidebar_section_logins'));
        await tester.ensureVisible(logins);
        await tester.tap(logins);
        await tester.pumpAndSettle();

        final legacyCard = find.byKey(const ValueKey('secure_item_card_id_77'));
        expect(legacyCard, findsOneWidget);
        await tester.tap(find.descendant(
          of: legacyCard,
          matching: find.widgetWithText(OutlinedButton, 'View'),
        ));
        await tester.pumpAndSettle();
        expect(find.textContaining('needs migration'), findsWidgets);
        expect(find.byKey(const Key('secure_item_detail_copy_username')),
            findsNothing);

        final v2Card = find.byKey(const ValueKey('secure_item_card_id_42'));
        await tester.tap(find.descendant(
          of: v2Card,
          matching: find.widgetWithText(OutlinedButton, 'View'),
        ));
        await tester.pumpAndSettle();
        expect(find.textContaining('synthetic-user'), findsWidgets);
        await tester
            .tap(find.byKey(const Key('secure_item_detail_copy_username')));
        await tester.pumpAndSettle();
        expect(copiedValue, 'synthetic-user');
        await tester.tap(find.byKey(const Key('secure_item_detail_delete')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('chat_composer_field')), findsOneWidget);
        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
        await tester.enterText(
            find.byKey(const Key('chat_composer_field')), 'yes');
        await tester.pump();
        final send = tester.widget<InkWell>(find.descendant(
          of: find.byKey(const Key('composer_send_button')),
          matching: find.byType(InkWell),
        ));
        expect(send.onTap, isNotNull);
        send.onTap!();
        await tester.pumpAndSettle();
        expect(exists, isFalse);
        expect(requests.where((request) => request.method == 'DELETE'),
            hasLength(1));
        Future<void> sendChat(String text) async {
          await tester.enterText(
              find.byKey(const Key('chat_composer_field')), text);
          await tester.pump();
          final button = tester.widget<InkWell>(find.descendant(
            of: find.byKey(const Key('composer_send_button')),
            matching: find.byType(InkWell),
          ));
          button.onTap!();
          await tester.pumpAndSettle();
        }

        await sendChat('Show my Second account login');
        ChatMessageList chat() =>
            tester.widget<ChatMessageList>(find.byType(ChatMessageList));
        expect(chat().messages.last.text,
            contains('Here is your "Second account" login'));
        await sendChat('Delete my Second account login');
        expect(chat().messages.last.text,
            contains('Permanently delete the "Second account"'));
        await sendChat('yes');
        expect(secondExists, isFalse);
        expect(requests.where((request) => request.method == 'DELETE'),
            hasLength(2));
        expect(tester.takeException(), isNull);
      }, () => mock);
      for (final request in requests) {
        expect(request.url.host, 'localhost');
        expect(request.body, isNot(contains('"pin"')));
        expect(request.body, isNot(contains('synthetic-secret')));
      }
      expect(
          requests.any((request) => <String>{
                '/get-secure-item',
                '/delete-secure-item',
                '/list-secure-items',
              }.contains(request.url.path)),
          isFalse);
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      app.unlocked = false;
      app.dispose();
      ZkActiveMvk.clear();
      ZkActiveSkVault.clear();
      PrivateZkPinTransportSession.clear();
      VaultCryptoRegistry.clear(reason: 'private_saved_item_ui_cleanup');
      setApiClientDeviceId('');
      await tester.binding.setSurfaceSize(null);
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null);
    }
  }, skip: !(kPrivateOnlyUnlockEnabled && kEnableKeylessSavedItemRead));
}
