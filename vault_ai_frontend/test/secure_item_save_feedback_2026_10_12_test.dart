import 'dart:async';
import 'dart:convert';

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
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/secure_item_detail.dart';

import 'login_duplicate_identity_2026_10_12_test.dart' as identity;

const _duplicateMessage =
    'A saved item already uses this title. Choose a different title or edit it.';
const _genericMessage =
    'Could not save this item. Check your connection and try again.';
const _errorKey = Key('secure_item_edit_save_error');
const _saveKey = Key('secure_item_edit_save');

class _FixtureApp extends AppState {
  @override
  Future<void> refreshVaultStats() async {}
}

class _TransportFailureFixture extends identity.Fixture {
  @override
  Future<http.Response> respond(http.Request request) async {
    if (request.url.host != '127.0.0.1' || request.url.port != 9) {
      throw StateError('Foreign fixture destination blocked');
    }
    if (request.method == 'POST' &&
        (request.url.path == '/vault/ciphertext/vault-items' ||
            request.url.path == '/update-secure-item')) {
      writes.add(request);
      return http.Response('{"detail":"synthetic-private-raw-error"}', 503);
    }
    return super.respond(request);
  }
}

Widget _localized(Widget home) => MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      locale: const Locale('en'),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      routes: {'/pin': (_) => const Text('Synthetic PIN route')},
      home: home,
    );

Future<void> _openDialog(WidgetTester tester,
    {required SecureItemEditSaveHandler onSave,
    Size size = const Size(360, 640)}) async {
  await tester.binding.setSurfaceSize(size);
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(_localized(Scaffold(
    body: Builder(
        builder: (context) => TextButton(
              key: const Key('open_synthetic_editor'),
              onPressed: () => showSecureItemEditDialog(
                context,
                title: 'QA duplicate',
                itemType: 'login',
                dialogTitle: 'New Login',
                initialFields: const {
                  'username': 'synthetic-new-username',
                  'password': 'synthetic-new-password',
                  'custom label': 'synthetic-custom-value',
                },
                onSave: onSave,
              ),
              child: const Text('Open synthetic editor'),
            )),
  )));
  await tester.tap(find.byKey(const Key('open_synthetic_editor')));
  await tester.pumpAndSettle();
}

void _expectFieldsRetained(WidgetTester tester) {
  TextField field(String key) => tester.widget<TextField>(find.byKey(Key(key)));
  expect(field('secure_item_edit_title').controller!.text, 'QA duplicate');
  expect(field('secure_item_edit_username').controller!.text,
      'synthetic-new-username');
  expect(field('secure_item_edit_password').controller!.text,
      'synthetic-new-password');
  expect(field('secure_item_edit_password').obscureText, isTrue);
  expect(field('secure_item_custom_label_0').controller!.text, 'custom label');
  expect(field('secure_item_custom_value_0').controller!.text,
      'synthetic-custom-value');
  expect(field('secure_item_custom_value_0').obscureText, isTrue);
}

Future<void> _settleSave(WidgetTester tester) async {
  await tester.pump();
  for (var attempt = 0; attempt < 100; attempt++) {
    await tester
        .runAsync(() => Future<void>.delayed(const Duration(milliseconds: 5)));
    await tester.pump();
    final save = find.byKey(_saveKey);
    if (save.evaluate().isEmpty ||
        tester.widget<TextButton>(save).onPressed != null) {
      await tester.pumpAndSettle();
      return;
    }
  }
  fail('Synthetic save did not settle within the bounded fixture wait');
}

Future<void> _withDashboard(WidgetTester tester, identity.Fixture fixture,
    Future<void> Function() action) async {
  await tester.binding.setSurfaceSize(const Size(430, 932));
  final previousPlatform = debugDefaultTargetPlatformOverride;
  debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
  final app = _FixtureApp()
    ..sessionToken = 'synthetic-editor-token'
    ..vaultId = 'synthetic-editor-vault'
    ..vaultName = 'Synthetic editor vault'
    ..vaultHandle = 'synthetic-editor-handle'
    ..displayName = 'QA'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
  await tester.runAsync(() => deriveAndInstallCryptoContext(
        vaultId: app.vaultId!,
        vaultName: app.vaultName!,
        pin: '123456',
        pinSaltBase64: base64Encode(List.filled(16, 4)),
        iterations: 1,
        source: 'editor-feedback-regression-fixture',
      ));
  fixture.unlock();
  app.unlocked = true;
  setApiClientDeviceId('synthetic-editor-device');
  try {
    await http.runWithClient(() async {
      await tester.pumpWidget(ChangeNotifierProvider<AppState>.value(
        value: app,
        child: _localized(const ChatDashboardPage()),
      ));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('top_nav_create_button')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('create_choice_login')));
      await tester.pumpAndSettle();
      expect(find.byType(SecureItemEditDialog), findsOneWidget);
      await tester.enterText(
          find.byKey(const Key('secure_item_edit_title')), 'QA duplicate');
      await tester.enterText(find.byKey(const Key('secure_item_edit_username')),
          'synthetic-new-username');
      await tester.enterText(find.byKey(const Key('secure_item_edit_password')),
          'synthetic-new-password');
      await action();
    },
        () => MockClient((request) async {
              // Intercept every actual-dashboard request in process. Never send it.
              final expected = Uri.parse(backendBaseUrl);
              if (request.url.scheme != expected.scheme ||
                  request.url.host != expected.host ||
                  request.url.port != expected.port) {
                throw StateError('Foreign fixture destination blocked');
              }
              if (request.method == 'POST' &&
                  request.url.path == '/list-files') {
                return http.Response('{"files":[]}', 200);
              }
              if (request.method == 'GET' && request.url.path == '/folders') {
                return http.Response(
                    '{"path":"","folders":[],"files":[]}', 200);
              }
              final local = http.Request(
                  request.method,
                  request.url
                      .replace(scheme: 'http', host: '127.0.0.1', port: 9))
                ..headers.addAll(request.headers)
                ..body = request.body;
              return fixture.respond(local);
            }));
    expect(tester.takeException(), isNull);
  } finally {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    app.unlocked = false;
    app.dispose();
    ZkActiveMvk.clear();
    VaultCryptoRegistry.clear(reason: 'editor-feedback-fixture-cleanup');
    setApiClientDeviceId('');
    debugDefaultTargetPlatformOverride = previousPlatform;
    await tester.binding.setSurfaceSize(null);
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'),
            (_) async => null);
  });
  tearDown(() {
    ZkActiveMvk.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'), null);
  });

  testWidgets(
      'actual Create Login duplicate stays visible inside modal without a write',
      (tester) async {
    final fixture = identity.Fixture();
    await tester.runAsync(() => fixture.row(11, title: 'QA duplicate'));
    final before = jsonEncode(fixture.rows);
    await _withDashboard(tester, fixture, () async {
      await tester.tap(find.byKey(_saveKey));
      await _settleSave(tester);
      expect(fixture.writes, isEmpty);
      expect(jsonEncode(fixture.rows), before);
      expect(find.byType(SecureItemEditDialog), findsOneWidget);
      expect(
          find
              .descendant(
                  of: find.byType(AlertDialog),
                  matching: find.text(_duplicateMessage))
              .hitTestable(),
          findsOneWidget);
      expect(
          tester
              .widget<TextField>(
                  find.byKey(const Key('secure_item_edit_password')))
              .controller!
              .text,
          'synthetic-new-password');
      expect(
          tester.widget<TextButton>(find.byKey(_saveKey)).onPressed, isNotNull);
    });
  });

  testWidgets(
      'short login dialog shows safe duplicate error and retains masked fields',
      (tester) async {
    await _openDialog(tester,
        onSave: (
                {required oldTitle,
                required itemType,
                required newTitle,
                required fields}) async =>
            throw const SavedItemConflictException(duplicate: true));
    await tester.tap(find.byKey(_saveKey));
    await _settleSave(tester);
    expect(find.text(_duplicateMessage).hitTestable(), findsOneWidget);
    expect(find.byKey(_errorKey).hitTestable(), findsOneWidget);
    final alertSemantics = tester.widget<Semantics>(find
        .ancestor(of: find.byKey(_errorKey), matching: find.byType(Semantics))
        .first);
    expect(alertSemantics.properties.liveRegion, isTrue);
    _expectFieldsRetained(tester);
    expect(tester.takeException(), isNull);
  });

  for (final entry in {
    'update requirement': (
      identity.Fixture()
        ..rejectCiphertextWrite = true
        ..legacyConflictCode = 'update_app_required',
      savedItemUpdateRequiredMessage
    ),
    'transport error': (_TransportFailureFixture(), _genericMessage),
  }.entries) {
    testWidgets('actual Create Login ${entry.key} is visible without fallback',
        (tester) async {
      final fixture = entry.value.$1;
      await _withDashboard(tester, fixture, () async {
        await tester.tap(find.byKey(_saveKey));
        await _settleSave(tester);
        expect(fixture.writes.length, 1);
        expect(fixture.rows, isEmpty);
        expect(
            find
                .descendant(
                    of: find.byType(AlertDialog),
                    matching: find.text(entry.value.$2))
                .hitTestable(),
            findsOneWidget);
        expect(
            find.textContaining('synthetic-private-raw-error'), findsNothing);
        expect(find.text('Login saved'), findsNothing);
        expect(tester.widget<TextButton>(find.byKey(_saveKey)).onPressed,
            isNotNull);
      });
    });
  }

  for (final entry in {
    'update required': (
      const SavedItemUpdateRequiredException(),
      savedItemUpdateRequiredMessage
    ),
    'ambiguous item': (
      const SavedItemConflictException(),
      'More than one saved item has this title. Select the specific item from Logins.'
    ),
    'transport failure': (
      StateError('synthetic-private-raw-error'),
      _genericMessage
    ),
  }.entries) {
    testWidgets('${entry.key} is visible in dialog with safe fixed copy',
        (tester) async {
      await _openDialog(tester,
          onSave: (
                  {required oldTitle,
                  required itemType,
                  required newTitle,
                  required fields}) async =>
              throw entry.value.$1);
      await tester.tap(find.byKey(_saveKey));
      await _settleSave(tester);
      expect(find.text(entry.value.$2).hitTestable(), findsOneWidget);
      expect(find.textContaining('synthetic-private-raw-error'), findsNothing);
      _expectFieldsRetained(tester);
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('false result is visible and successful retry closes once',
      (tester) async {
    var saves = 0;
    final pending = Completer<bool>();
    await _openDialog(tester, onSave: (
        {required oldTitle,
        required itemType,
        required newTitle,
        required fields}) async {
      saves++;
      return saves == 1 ? false : pending.future;
    });
    await tester.tap(find.byKey(_saveKey));
    await _settleSave(tester);
    expect(find.text(_genericMessage).hitTestable(), findsOneWidget);
    _expectFieldsRetained(tester);
    await tester.tap(find.byKey(_saveKey));
    await tester.pump();
    expect(find.byKey(_errorKey), findsNothing);
    expect(tester.widget<TextButton>(find.byKey(_saveKey)).onPressed, isNull);
    await tester.tap(find.byKey(_saveKey));
    await tester.pump();
    expect(saves, 2);
    pending.complete(true);
    await tester.pumpAndSettle();
    expect(find.byType(SecureItemEditDialog), findsNothing);
    expect(saves, 2);
    expect(tester.takeException(), isNull);
  });

  testWidgets('late failed save after dialog disposal does not render or pop',
      (tester) async {
    final pending = Completer<bool>();
    await _openDialog(tester,
        onSave: (
                {required oldTitle,
                required itemType,
                required newTitle,
                required fields}) =>
            pending.future);
    await tester.tap(find.byKey(_saveKey));
    await tester.pump();
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    pending.completeError(StateError('synthetic-private-raw-error'));
    await tester.pumpAndSettle();
    expect(find.byKey(_errorKey), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
