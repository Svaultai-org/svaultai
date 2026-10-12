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
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

const _first = 'synthetic-file-first';
const _second = 'synthetic-file-second';
const _name = 'same-name.txt';

class _App extends AppState {
  @override
  Future<void> refreshVaultStats() async {}
}

class _Files {
  final rows = <Map<String, dynamic>>[
    for (final id in [_first, _second])
      {
        'id': id,
        'file_name': _name,
        'content_type': 'text/plain',
        'file_size': 4,
        'asset_type': 'file'
      },
  ];
  final deletes = <http.Request>[];
  Completer<void>? deleteGate;
  bool fail = false;
  bool revoked = false;

  Future<http.Response> respond(http.Request request) async {
    if (request.url.host != '127.0.0.1' || request.url.port != 1) {
      throw StateError('Foreign destination refused');
    }
    Object data;
    switch ('${request.method} ${request.url.path}') {
      case 'POST /list-files':
        data = {'files': rows.map((r) => Map<String, dynamic>.of(r)).toList()};
        break;
      case 'GET /folders':
        data = {'path': '', 'folders': [], 'files': rows};
        break;
      case 'POST /list-secure-items':
        data = {'items': []};
        break;
      case 'GET /vault/ciphertext/vault-items':
        data = [];
        break;
      case 'POST /manage/file/delete':
        deletes.add(request);
        await deleteGate?.future;
        if (revoked) {
          return http.Response('{"detail":{"code":"session_revoked"}}', 401);
        }
        if (fail) return http.Response('{}', 503);
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        rows.removeWhere((r) => r['id'] == body['file_id']);
        data = {'deleted': true};
        break;
      default:
        throw StateError('Unexpected synthetic request: ${request.url.path}');
    }
    return http.Response(jsonEncode(data), 200,
        headers: {'content-type': 'application/json'});
  }
}

Future<_App> _fixture() async {
  final app = _App()
    ..sessionToken = 'synthetic-file-token'
    ..vaultId = 'synthetic-file-vault'
    ..vaultName = 'Synthetic file vault'
    ..vaultHandle = 'synthetic-file-handle'
    ..displayName = 'QA'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
  // Install the synthetic fixture with the portable PBKDF implementation.
  // Android UI/controller variants below do not claim to test native KDF/FFI.
  final platform = debugDefaultTargetPlatformOverride;
  debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
  try {
    await deriveAndInstallCryptoContext(
      vaultId: app.vaultId!,
      vaultName: app.vaultName!,
      pin: '123456',
      pinSaltBase64: base64Encode(List.filled(16, 5)),
      iterations: 1,
      source: 'file-delete-regression-fixture',
    );
  } finally {
    debugDefaultTargetPlatformOverride = platform;
  }
  ZkActiveMvk.set(
      mvk: SecretKey(List.filled(32, 5)),
      vaultId: app.vaultId!,
      vaultHandle: app.vaultHandle!);
  app.unlocked = true;
  return app;
}

Widget _dashboard(_App app) => ChangeNotifierProvider<AppState>.value(
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

Future<void> _files(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.menu_rounded));
  await tester.pumpAndSettle();
  final tile = find.byKey(const ValueKey('sidebar_section_files'));
  await tester.ensureVisible(tile);
  await tester.tap(tile);
  await tester.pumpAndSettle();
}

Future<void> _select(WidgetTester tester, String id) async {
  await _files(tester);
  expect(
      find.byKey(const ValueKey('files_file_delete_$_first')), findsOneWidget);
  expect(
      find.byKey(const ValueKey('files_file_delete_$_second')), findsOneWidget);
  await tester.tap(find.byKey(ValueKey('files_file_delete_$id')));
  await tester.pumpAndSettle();
  expect(find.text('Permanently delete the "$_name" file? Reply yes or no.'),
      findsWidgets);
}

Future<void> _send(WidgetTester tester, String text,
    {bool settle = true}) async {
  await tester.enterText(find.byKey(const Key('chat_composer_field')), text);
  await tester.pump();
  await tester.tap(find.byKey(const Key('composer_send_button')));
  if (settle) {
    await tester.pumpAndSettle();
  } else {
    await tester.pump(const Duration(milliseconds: 30));
  }
}

Future<void> _withDashboard(
    WidgetTester tester, Future<void> Function(_App, _Files) action) async {
  await tester.binding.setSurfaceSize(const Size(430, 932));
  final app = (await tester.runAsync(_fixture))!;
  final files = _Files();
  setApiClientDeviceId('synthetic-file-device');
  try {
    await http.runWithClient(() async {
      await tester.pumpWidget(_dashboard(app));
      await tester.pumpAndSettle();
      await action(app, files);
      expect(tester.takeException(), isNull);
    }, () => MockClient(files.respond));
  } finally {
    files.deleteGate?.complete();
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    app.unlocked = false;
    app.dispose();
    ZkActiveMvk.clear();
    VaultCryptoRegistry.clear(reason: 'file-delete-regression-cleanup');
    setApiClientDeviceId('');
    await tester.binding.setSurfaceSize(null);
  }
}

final _platforms =
    TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android});

void main() {
  setUp(() {
    st.SessionTermination.instance.resetForTests();
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'),
            (_) async => null);
  });
  tearDown(() {
    st.SessionTermination.instance.resetForTests();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'), null);
  });

  testWidgets('Files delete confirms and deletes only selected same-name ID',
      (tester) async {
    await _withDashboard(tester, (app, files) async {
      await _select(tester, _second);
      expect(files.deletes, isEmpty);
      await _send(tester, 'yes');
      expect(files.deletes, hasLength(1));
      final request = files.deletes.single;
      expect(request.headers['Authorization'], 'Bearer synthetic-file-token');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body['file_id'], _second);
      expect(body['vault_name'], '');
      expect(files.rows.map((r) => r['id']), [_first]);
      await _files(tester);
      expect(find.byKey(const ValueKey('files_file_card_$_first')),
          findsOneWidget);
      expect(
          find.byKey(const ValueKey('files_file_card_$_second')), findsNothing);
    });
  }, variant: _platforms);

  testWidgets('Cancel keeps both duplicate-name files without a delete request',
      (tester) async {
    await _withDashboard(tester, (app, files) async {
      await _select(tester, _second);
      await _send(tester, 'no');
      expect(files.deletes, isEmpty);
      expect(files.rows, hasLength(2));
      await _files(tester);
      expect(find.byKey(const ValueKey('files_file_card_$_first')),
          findsOneWidget);
      expect(find.byKey(const ValueKey('files_file_card_$_second')),
          findsOneWidget);
    });
  }, variant: _platforms);

  for (final change in ['token', 'key', 'device', 'generation']) {
    testWidgets('Changed $change after file confirmation cannot issue deletion',
        (tester) async {
      await _withDashboard(tester, (app, files) async {
        await _select(tester, _second);
        switch (change) {
          case 'token':
            app.sessionToken = 'synthetic-replacement-token';
            break;
          case 'key':
            ZkActiveMvk.set(
                mvk: SecretKey(List.filled(32, 8)),
                vaultId: app.vaultId!,
                vaultHandle: app.vaultHandle!);
            break;
          case 'device':
            setApiClientDeviceId('synthetic-replacement-device');
            break;
          case 'generation':
            await st.SessionTermination.instance
                .handle(st.SessionTerminationCode.revoked);
            break;
        }
        await _send(tester, 'yes');
        expect(files.deletes, isEmpty);
        expect(files.rows, hasLength(2));
        expect(
            find.text(
                'Your session changed. Select the file again before deleting.'),
            findsOneWidget);
      });
    }, variant: _platforms);
  }

  testWidgets('Rapid confirmation sends only one selected-ID delete',
      (tester) async {
    await _withDashboard(tester, (app, files) async {
      await _select(tester, _second);
      files.deleteGate = Completer<void>();
      await _send(tester, 'yes', settle: false);
      await tester.tap(find.byKey(const Key('composer_send_button')));
      await tester.pump();
      expect(files.deletes, hasLength(1));
      files.deleteGate!.complete();
      files.deleteGate = null;
      await tester.pumpAndSettle();
      expect(files.rows.map((r) => r['id']), [_first]);
    });
  }, variant: _platforms);

  testWidgets('Late old-session response cannot remove rows or claim success',
      (tester) async {
    await _withDashboard(tester, (app, files) async {
      await _select(tester, _second);
      files.deleteGate = Completer<void>();
      await _send(tester, 'yes', settle: false);
      expect(files.deletes, hasLength(1));
      app.sessionToken = 'synthetic-replacement-token';
      files.deleteGate!.complete();
      files.deleteGate = null;
      await tester.pumpAndSettle();
      expect(find.text('Deleted "$_name" permanently.'), findsNothing);
      final state = tester.state(find.byType(ChatDashboardPage)) as dynamic;
      expect((state.vaultFiles as List).length, 2,
          reason: 'A late old-session response must not mutate local rows.');
      // The accepted old authorized request may finish on the server, but the
      // stale result must not modify the currently displayed client inventory.
      await tester.tap(find.byIcon(Icons.menu_rounded));
      await tester.pumpAndSettle();
      final tile = find.byKey(const ValueKey('sidebar_section_files'));
      await tester.ensureVisible(tile);
      await tester.tap(tile);
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('files_file_card_$_first')),
          findsOneWidget);
    });
  }, variant: _platforms);

  testWidgets('Failed delete retains both rows and permits an exact-ID retry',
      (tester) async {
    await _withDashboard(tester, (app, files) async {
      await _select(tester, _second);
      files.fail = true;
      await _send(tester, 'yes');
      expect(files.rows, hasLength(2));
      expect(find.text('I could not delete "$_name". Nothing was changed.'),
          findsOneWidget);
      files.fail = false;
      await _select(tester, _second);
      await _send(tester, 'yes');
      expect(files.deletes, hasLength(2));
      expect(files.deletes.map((r) => (jsonDecode(r.body) as Map)['file_id']),
          [_second, _second]);
      expect(files.rows.map((r) => r['id']), [_first]);
    });
  }, variant: _platforms);

  for (final change in ['token', 'key', 'device']) {
    testWidgets(
        'Late coded401 after $change change cannot terminate new access',
        (tester) async {
      await _withDashboard(tester, (app, files) async {
        var terminations = 0;
        st.SessionTermination.instance.setHandler((_) async {
          terminations++;
        });
        await _select(tester, _second);
        files.revoked = true;
        files.deleteGate = Completer<void>();
        await _send(tester, 'yes', settle: false);
        expect(files.deletes, hasLength(1));
        switch (change) {
          case 'token':
            app.sessionToken = 'synthetic-replacement-token';
            break;
          case 'key':
            ZkActiveMvk.set(
                mvk: SecretKey(List.filled(32, 8)),
                vaultId: app.vaultId!,
                vaultHandle: app.vaultHandle!);
            break;
          case 'device':
            setApiClientDeviceId('synthetic-replacement-device');
            break;
        }
        files.deleteGate!.complete();
        files.deleteGate = null;
        await tester.pumpAndSettle();
        expect(st.SessionTermination.instance.isTerminated, isFalse);
        expect(terminations, 0);
        expect(files.rows, hasLength(2));
        final state = tester.state(find.byType(ChatDashboardPage)) as dynamic;
        expect((state.vaultFiles as List).length, 2);
        expect(find.text('Deleted "$_name" permanently.'), findsNothing);
      });
    }, variant: _platforms);
  }

  testWidgets('Current-session coded401 still invokes canonical termination',
      (tester) async {
    await _withDashboard(tester, (app, files) async {
      var terminations = 0;
      st.SessionTermination.instance.setHandler((_) async {
        terminations++;
      });
      await _select(tester, _second);
      files.revoked = true;
      await _send(tester, 'yes');
      expect(files.deletes, hasLength(1));
      expect(st.SessionTermination.instance.isTerminated, isTrue);
      expect(terminations, 1);
      expect(files.rows, hasLength(2));
    });
  }, variant: _platforms);

  test('A stale response lease prevents file API dispatch entirely', () async {
    var requests = 0;
    await http.runWithClient(() async {
      await expectLater(
        const VaultAIClient(baseUrl: 'http://127.0.0.1:1').deleteVaultFile(
          vaultName: 'Synthetic vault',
          fileId: _second,
          pin: '123456',
          authToken: 'synthetic-token',
          responseIsCurrent: () => false,
        ),
        throwsStateError,
      );
    },
        () => MockClient((request) async {
              requests++;
              return http.Response(
                  '{"detail":{"code":"session_revoked"}}', 401);
            }));
    expect(requests, 0);
    expect(st.SessionTermination.instance.isTerminated, isFalse);
  });
}
