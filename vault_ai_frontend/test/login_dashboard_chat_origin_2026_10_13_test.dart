import 'dart:async';
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
import 'package:vault_ai_frontend/services/release_feature_contract.dart';
import 'package:vault_ai_frontend/services/session_termination.dart'
    as sessions;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart'
    as hierarchy;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';

class _App extends AppState {
  // Do not connect billing in this isolated saved-login fixture. Stats and
  // inventory use the real implementation and actual encrypted HTTP protocol.
  @override
  Future<void> refreshBilling() async {}
}

class _Fixture {
  final rows = <Map<String, dynamic>>[];
  final legacyRows = <Map<String, dynamic>>[];
  final requests = <http.Request>[];
  final mvk = SecretKey(List<int>.filled(32, 9));
  late AppState app;
  int chatCalls = 0;
  int nextId = 100;
  bool failInventory = false;
  Completer<void>? pendingSave;

  Future<void> unlock() async {
    app = _App()
      ..sessionToken = 'synthetic-login-count-token'
      ..vaultId = 'synthetic-login-count-vault'
      ..vaultName = 'Synthetic login count'
      ..vaultHandle = 'synthetic-login-count-handle'
      ..displayName = 'QA'
      ..authed = true
      ..billingLoadState = BillingLoadState.loaded
      ..billingIncludedBytes = kVaultStorageLimitBytes
      ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
    final requestedPlatform = debugDefaultTargetPlatformOverride;
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      // Software PBKDF2 only seeds this Mac VM fixture; the requested platform
      // is restored before widget rendering. This is not a store-device test.
      await deriveAndInstallCryptoContext(
        vaultId: app.vaultId!,
        vaultName: app.vaultName!,
        pin: '123456',
        pinSaltBase64: base64Encode(List<int>.filled(16, 9)),
        iterations: 1,
        source: 'login-dashboard-regression-fixture',
      );
    } finally {
      debugDefaultTargetPlatformOverride = requestedPlatform;
    }
    ZkActiveMvk.set(
        mvk: mvk, vaultId: app.vaultId!, vaultHandle: app.vaultHandle!);
    app.unlocked = true;
    setApiClientDeviceId('synthetic-login-count-device');
  }

  Future<void> row(int id, String title, String type,
      {String username = 'synthetic-user'}) async {
    final key = await hierarchy.VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String text) async => hierarchy
        .b64urlEncode(await hierarchy.aesGcmWrap(key, utf8.encode(text)));
    rows.add({
      'item_id': id,
      'item_type_ciphertext': await wrap(type),
      'service_ciphertext': await wrap(title),
      'payload_ciphertext': await wrap(jsonEncode({
        'fields': {
          'username': username,
          'password': 'synthetic-secret'
        },
      })),
    });
  }

  Future<http.Response> respond(http.Request request) async {
    if (request.url.host != 'localhost' || request.url.port != 8000) {
      throw StateError('External destinations are blocked in this fixture');
    }
    requests.add(request);
    final route = '${request.method} ${request.url.path}';
    Object result;
    switch (route) {
      case 'POST /vault-stats':
        // Ciphertext item types are unreadable on the server, so its legacy
        // login statistic remains zero even after a real encrypted save.
        result = {'login_count': 0, 'file_count': 2, 'storage_used_bytes': 40};
        break;
      case 'POST /list-files':
        result = {'files': []};
        break;
      case 'GET /folders':
        result = {'path': '', 'folders': [], 'files': []};
        break;
      case 'POST /list-secure-items':
        result = {'items': legacyRows};
        break;
      case 'GET /vault/ciphertext/vault-items':
        if (failInventory) return http.Response('{}', 503);
        result = rows;
        break;
      case 'POST /vault/ciphertext/vault-items':
        await pendingSave?.future;
        final body = Map<String, dynamic>.from(jsonDecode(request.body) as Map);
        final id = (body['item_id'] as num?)?.toInt() ?? nextId++;
        rows.removeWhere((row) => row['item_id'] == id);
        rows.add({...body, 'item_id': id});
        result = {'item_id': id, 'created': body['item_id'] == null};
        break;
      case 'POST /vault/ciphertext/vault-items/generated-drafts/finalize':
        final body = jsonDecode(request.body) as Map;
        expect(body.keys.toSet(), {'item_id', 'draft_id'});
        result = {'finalized': true};
        break;
      case 'POST /chat':
        chatCalls++;
        final Object reply = chatCalls == 1
            ? {
                'type': 'vault_chat_card',
                'schema': 'vault_chat_response_v1',
                'message': '',
                'intent': 'vault_generated_login_create_draft',
                'card': {
                  'schema': 'vault_chat_router_v1',
                  'cardType': 'vault_generated_login_card',
                  'view': 'create_draft',
                  'data': {
                    'view': 'create_draft',
                    'service': 'Chat service',
                    'username': 'synthetic-chat-user',
                    'password': 'synthetic-chat-secret',
                    'draft_id': 'synthetic-draft-1',
                    'actions': ['save', 'cancel'],
                  },
                },
              }
            : 'Draft cancelled.';
        final encrypted = await encryptWithContext(
          plaintext: reply is String ? reply : jsonEncode(reply),
          context: VaultCryptoRegistry.current!,
        );
        return http.Response('data: $encrypted\n\n', 200,
            headers: {'content-type': 'text/event-stream'});
      default:
        if (request.method == 'DELETE' &&
            request.url.path.startsWith('/vault/ciphertext/vault-items/')) {
          final id = int.parse(request.url.pathSegments.last);
          rows.removeWhere((row) => row['item_id'] == id);
          result = {'deleted': true};
          break;
        }
        throw StateError('Unexpected isolated saved-login operation: $route');
    }
    return http.Response(jsonEncode(result), 200,
        headers: {'content-type': 'application/json'});
  }

  Future<T> run<T>(Future<T> Function() action) =>
      http.runWithClient(action, () => MockClient(respond));

  void dispose() {
    app.unlocked = false;
    app.dispose();
    ZkActiveMvk.clear();
    VaultCryptoRegistry.clear(reason: 'saved-login-fixture-cleanup');
    setApiClientDeviceId('');
  }
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
  await tester.pump(const Duration(seconds: 5));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('chat_composer_field')), text);
  await tester.pump();
  await tester.tap(find.byKey(const Key('composer_send_button')));
  await tester.pumpAndSettle();
}

Future<void> _section(WidgetTester tester, String section) async {
  await tester.pump(const Duration(seconds: 5));
  await tester.pumpAndSettle();
  await tester.tap(find.byIcon(Icons.menu_rounded));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(ValueKey('sidebar_section_$section')));
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
            (_) async => null);
  });
  tearDown(() {
    sessions.SessionTermination.instance.reset();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'), null);
  });

  test(
      'decrypted count excludes notes/wallets and survives legacy stats refresh',
      () async {
    final f = _Fixture();
    await f.unlock();
    final app = f.app;
    try {
      app.applyBackendStats({'login_count': 0, 'file_count': 7});
      app.applyLoginInventoryCount(const [
        VaultLoginItem(service: 'Login', itemType: 'login'),
        VaultLoginItem(service: 'Credential', itemType: 'credential'),
        VaultLoginItem(service: 'Note', itemType: 'private_note'),
        VaultLoginItem(service: 'Wallet', itemType: 'crypto_wallet_account'),
      ], authToken: app.sessionToken!, requestVaultName: app.vaultName!);
      expect(app.loginCount, 2);
      app.applyBackendStats({'login_count': 0, 'file_count': 8});
      expect(app.loginCount, 2);
      expect(app.fileCount, 8);
      app.applyLoginInventoryCount(const [],
          authToken: app.sessionToken!, requestVaultName: app.vaultName!);
      expect(app.loginCount, 0);
    } finally {
      f.dispose();
    }
  });

  test('late inventory cannot alter another session or locked vault', () async {
    final f = _Fixture();
    await f.unlock();
    final app = f.app
      ..loginCount = 9
      ..unlocked = false;
    try {
      app.applyLoginInventoryCount(const [],
          authToken: app.sessionToken!, requestVaultName: app.vaultName!);
      expect(app.loginCount, 9, reason: 'locked inventory must not apply');
      app.unlocked = true;
      app.applyLoginInventoryCount(const [],
          authToken: 'old-token', requestVaultName: app.vaultName!);
      app.applyLoginInventoryCount(const [],
          authToken: app.sessionToken!, requestVaultName: 'Old vault');
      expect(app.loginCount, 9);
      app.applyBackendStats({'login_count': 3});
      expect(app.loginCount, 3,
          reason: 'new session can still use initial legacy stats');
    } finally {
      f.dispose();
    }
  });

  testWidgets(
      'Saved logins dashboard quick action opens all five encrypted logins without chat',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    await tester.runAsync(() async {
      for (var id = 101; id <= 105; id++) {
        await f.row(id, 'Dashboard Service ${id - 100}', 'login');
      }
    });
    final originalRows =
        f.rows.map((row) => Map<String, dynamic>.from(row)).toList();
    try {
      await f.run(() async {
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        expect(f.app.loginCount, 5);
        await _section(tester, 'dashboard');
        final quickAction =
            find.widgetWithText(OutlinedButton, 'Saved logins');
        await tester.ensureVisible(quickAction);
        await tester.pumpAndSettle();
        expect(quickAction.hitTestable(), findsOneWidget);
        await tester.tap(quickAction);
        await tester.pumpAndSettle();
        expect(find.byType(LoginsPage), findsOneWidget);
        expect(find.byKey(const Key('logins_page')), findsOneWidget);
        expect(find.byKey(const Key('chat_composer_field')), findsNothing);
        final page = tester.widget<LoginsPage>(find.byType(LoginsPage));
        expect(page.logins, hasLength(5));
        expect(page.logins.map((item) => item.itemId),
            unorderedEquals(['101', '102', '103', '104', '105']));
        for (var id = 101; id <= 105; id++) {
          expect(find.byKey(ValueKey('secure_item_card_id_$id')), findsOneWidget);
          expect(find.text('Dashboard Service ${id - 100}'), findsOneWidget);
        }
        expect(find.text('No saved login matches "".'), findsNothing);
        expect(f.requests.where((request) => request.url.path == '/chat'),
            isEmpty);
        expect(f.rows, originalRows);
        // The collection quick action must preserve named retrieval in chat.
        await _section(tester, 'chat');
        await _send(tester, 'Show my Dashboard Service 3 login');
        final chat =
            tester.widget<ChatMessageList>(find.byType(ChatMessageList));
        final card = chat.messages.last.payload?['card'] as Map;
        final login = (card['data'] as Map)['login'] as Map;
        expect('${login['id']}', '103');
        expect(login['title'], 'Dashboard Service 3');
        expect((login['fields'] as Map)['username'], 'synthetic-user');
        expect(f.requests.where((request) => request.url.path == '/chat'),
            isEmpty);
        expect(f.rows, originalRows);
        expect(tester.takeException(), isNull);
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  },
      variant:
          TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android}));


  testWidgets(
      'deleted specific login cannot retrieve or delete a shorter surviving title',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    await tester.runAsync(() async {
      await f.row(201, 'QA-TEST iPhone', 'login',
          username: 'as-iPhone-edited');
      await f.row(202, 'QA-TEST iPhone Final', 'login',
          username: 'final-specific-user');
      await f.row(203, 'NordVPN', 'login', username: 'nord-specific-user');
      await f.row(204, 'Facebook', 'login', username: 'facebook-specific-user');
    });
    final originalSurvivors = f.rows
        .where((row) => row['item_id'] != 202)
        .map((row) => Map<String, dynamic>.from(row))
        .toList();
    ChatMessageList chat() =>
        tester.widget<ChatMessageList>(find.byType(ChatMessageList));
    Map latestLogin() {
      final card = chat().messages.last.payload!['card'] as Map;
      return (card['data'] as Map)['login'] as Map;
    }
    try {
      await f.run(() async {
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        await _send(tester, 'Show my QA-TEST iPhone Final login');
        expect('${latestLogin()['id']}', '202');
        expect((latestLogin()['fields'] as Map)['username'],
            'final-specific-user');
        await _send(tester, 'Delete my QA-TEST iPhone Final login');
        expect(chat().messages.last.text,
            'Permanently delete the "QA-TEST iPhone Final" login? Reply yes or no.');
        await _send(tester, 'yes');
        expect(f.rows, originalSurvivors);
        final deletes = f.requests.where((request) => request.method == 'DELETE');
        expect(deletes, hasLength(1));
        expect(deletes.single.url.path, '/vault/ciphertext/vault-items/202');
        for (final action in const ['Show', 'Delete']) {
          await _send(tester, '$action my QA-TEST iPhone Final login');
          expect(chat().messages.last.text,
              'No saved login matches "QA-TEST iPhone Final".');
          expect(chat().messages.last.payload, isNull);
          expect(find.text('as-iPhone-edited'), findsNothing);
          expect(f.rows, originalSurvivors);
          expect(f.requests.where((request) => request.method == 'DELETE'),
              hasLength(1));
        }
        for (final expected in const [
          ['QA-TEST iPhone', '201', 'as-iPhone-edited'],
          ['nord vpn', '203', 'nord-specific-user'],
          ['Facebook', '204', 'facebook-specific-user'],
        ]) {
          await _send(tester, 'Show my ${expected[0]} login');
          expect('${latestLogin()['id']}', expected[1]);
          expect((latestLogin()['fields'] as Map)['username'], expected[2]);
        }
        expect(f.rows, originalSurvivors);
        expect(f.requests.where((request) => request.url.path == '/chat'),
            isEmpty);
        expect(tester.takeException(), isNull);
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  },
      variant:
          TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android}));

  testWidgets(
      'actual encrypted inventory counts mixed logins on load and reload',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    await tester.runAsync(() async {
      await f.row(1, 'Ciphertext login', 'login');
      await f.row(2, 'Ciphertext credential', 'credential');
      await f.row(3, 'Private note', 'private_note');
      await f.row(4, 'Internal wallet', 'crypto_wallet_account');
    });
    f.legacyRows.addAll([
      {'id': 1, 'service': 'Ciphertext login', 'item_type': 'login'},
      {'id': 5, 'service': 'Legacy login', 'item_type': 'login'},
    ]);
    try {
      await f.run(() async {
        expect(zkV2CredentialWriteEnabled, isFalse,
            reason: 'ship-mode credential-v2 write flag stays disabled');
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        expect(f.app.loginCount, 3,
            reason: 'same persisted ID is not counted twice');
        await _section(tester, 'dashboard');
        expect(find.text('Vault overview'), findsOneWidget);
        expect(find.text('3'), findsOneWidget);
        f.app.applyBackendStats({'login_count': 0, 'file_count': 2});
        await tester.pumpAndSettle();
        expect(find.text('3'), findsOneWidget);
        await _section(tester, 'logins');
        expect(find.byKey(const Key('secure_item_card_id_5')), findsOneWidget);
        // External reload removes one login; unchanged file count still comes
        // from server stats. A failed inventory read must retain last count.
        f.rows.removeWhere((row) => row['item_id'] == 2);
        await tester.tap(find.widgetWithText(OutlinedButton, 'Refresh'));
        await tester.pumpAndSettle();
        expect(f.app.loginCount, 2);
        f.failInventory = true;
        await tester.tap(find.widgetWithText(OutlinedButton, 'Refresh'));
        await tester.pumpAndSettle();
        expect(f.app.loginCount, 2);
        expect(f.app.fileCount, 2);
        // A fresh unlocked session has no in-memory count cache. Loading the
        // persisted encrypted/legacy inventory must rebuild the same count.
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pumpAndSettle();
        f.app.unlocked = false;
        f.app.dispose();
        VaultCryptoRegistry.clear(reason: 'synthetic-login-reopen');
        f.failInventory = false;
        await tester.runAsync(f.unlock);
        expect(f.app.loginCount, 0);
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        expect(f.app.loginCount, 2);
        await _section(tester, 'dashboard');
        expect(find.text('2'), findsNWidgets(2),
            reason: 'restored Logins and unchanged Files both count two');
        expect(tester.takeException(), isNull);
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  });

  testWidgets(
      'chat Save stays in chat, resolves once and updates dashboard count',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    try {
      await f.run(() async {
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        await _send(tester, 'Create a Chat service login');
        final save =
            find.byKey(const Key('vault_chat_card_generated_login_save'));
        expect(save, findsOneWidget);
        f.pendingSave = Completer<void>();
        await tester.ensureVisible(save);
        await tester.pumpAndSettle();
        await tester.tap(save);
        await tester.tap(save);
        await tester.pump();
        f.pendingSave!.complete();
        await tester.pumpAndSettle();
        expect(
            f.requests.where((r) =>
                r.method == 'POST' &&
                r.url.path == '/vault/ciphertext/vault-items'),
            hasLength(1));
        expect(f.rows, hasLength(1));
        expect(f.app.loginCount, 1);
        expect(find.byKey(const Key('chat_composer_field')), findsOneWidget,
            reason: 'chat-origin save must not navigate to Logins');
        expect(find.text('Login saved securely.'), findsWidgets);
        expect(find.byKey(const Key('vault_chat_card_generated_login_save')),
            findsNothing);
        expect(find.byKey(const Key('vault_chat_card_generated_login_cancel')),
            findsNothing);
        await f.app.refreshVaultStats();
        await tester.pumpAndSettle();
        expect(f.app.loginCount, 1,
            reason: 'legacy count=0 must not erase encrypted count');
        await _section(tester, 'dashboard');
        expect(find.text('1'), findsOneWidget);
        await _section(tester, 'chat');
        expect(find.byKey(const Key('vault_chat_card_generated_login_save')),
            findsNothing,
            reason: 'parent one-shot state survives section remount');
        await _send(tester, 'Show my Chat service login');
        expect(find.text('synthetic-chat-user'), findsWidgets);
        expect(f.requests.where((r) => r.url.path == '/chat'), hasLength(1),
            reason:
                'saved credential retrieval is local and does not resubmit draft');
        expect(tester.takeException(), isNull);
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  },
      variant:
          TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android}));

  testWidgets('chat Cancel is one-shot and neither writes nor increments count',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    try {
      await f.run(() async {
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        await _send(tester, 'Create a Chat service login');
        final cancel =
            find.byKey(const Key('vault_chat_card_generated_login_cancel'));
        await tester.ensureVisible(cancel);
        await tester.pumpAndSettle();
        await tester.tap(cancel);
        await tester.tap(cancel);
        await tester.pumpAndSettle();
        expect(f.rows, isEmpty);
        expect(f.app.loginCount, 0);
        expect(
            f.requests.where((r) =>
                r.method == 'POST' &&
                r.url.path == '/vault/ciphertext/vault-items'),
            isEmpty);
        expect(f.chatCalls, 2,
            reason: 'one create and one draft cancellation only');
        expect(find.byKey(const Key('chat_composer_field')), findsOneWidget);
        expect(find.byKey(const Key('vault_chat_card_generated_login_save')),
            findsNothing);
        expect(find.byKey(const Key('vault_chat_card_generated_login_cancel')),
            findsNothing);
        expect(tester.takeException(), isNull);
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  });

  testWidgets(
      'manual Create retains Logins navigation; edit/delete refresh actual count',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    try {
      await f.run(() async {
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('top_nav_create_button')));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('create_choice_login')));
        await tester.pumpAndSettle();
        await tester.enterText(
            find.byKey(const Key('secure_item_edit_title')), 'Manual service');
        await tester.enterText(
            find.byKey(const Key('secure_item_edit_username')),
            'synthetic-manual-user');
        await tester.enterText(
            find.byKey(const Key('secure_item_edit_password')),
            'synthetic-manual-secret');
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();
        expect(find.byType(LoginsPage), findsOneWidget);
        expect(f.app.loginCount, 1);
        expect(f.rows, hasLength(1));
        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
        final edit = find.widgetWithText(OutlinedButton, 'Edit').first;
        await tester.ensureVisible(edit);
        await tester.pumpAndSettle();
        await tester.tap(edit);
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('secure_item_edit_title')),
            'Manual service edited');
        await tester.tap(find.byKey(const Key('secure_item_edit_save')));
        await tester.pumpAndSettle();
        expect(find.text('Manual Service Edited'), findsOneWidget);
        expect(f.app.loginCount, 1);
        expect(f.rows, hasLength(1));
        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
        final remove = find.widgetWithText(OutlinedButton, 'Delete').first;
        await tester.ensureVisible(remove);
        await tester.pumpAndSettle();
        await tester.tap(remove);
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('chat_composer_field')), findsOneWidget);
        await _send(tester, 'yes');
        expect(f.rows, isEmpty);
        expect(f.app.loginCount, 0);
        await _section(tester, 'dashboard');
        expect(find.text('0'), findsOneWidget);
        expect(f.app.fileCount, 2);
        expect(tester.takeException(), isNull);
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump();
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  });
}
