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
import 'package:vault_ai_frontend/services/saved_file_rename.dart';
import 'package:vault_ai_frontend/services/session_termination.dart'
    as sessions;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart'
    as hierarchy;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/ui/saved_file_rename_dialog.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

class _App extends AppState {
  @override
  Future<void> refreshBilling() async {}
}

class _Fixture {
  final mvk = SecretKey(List<int>.filled(32, 31));
  final rows = <Map<String, dynamic>>[];
  final writes = <Map<String, dynamic>>[];
  final requests = <http.Request>[];
  late AppState app;
  Completer<void>? pending;
  Completer<void>? pendingFiles;
  Completer<void>? pendingFolder;
  bool failWrite = false;
  bool badAck = false;

  Future<void> unlock() async {
    app = _App()
      ..sessionToken = 'synthetic-file-token'
      ..vaultId = 'synthetic-file-vault'
      ..vaultName = 'Synthetic file vault'
      ..vaultHandle = 'synthetic-file-handle'
      ..displayName = 'QA'
      ..authed = true
      ..billingLoadState = BillingLoadState.loaded
      ..billingIncludedBytes = kVaultStorageLimitBytes
      ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
    final previous = debugDefaultTargetPlatformOverride;
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await deriveAndInstallCryptoContext(
        vaultId: app.vaultId!,
        vaultName: app.vaultName!,
        pin: '123456',
        pinSaltBase64: base64Encode(List<int>.filled(16, 31)),
        iterations: 1,
        source: 'isolated-file-rename-fixture',
      );
    } finally {
      debugDefaultTargetPlatformOverride = previous;
    }
    ZkActiveMvk.set(
        mvk: mvk, vaultId: app.vaultId!, vaultHandle: app.vaultHandle!);
    app.unlocked = true;
    setApiClientDeviceId('synthetic-file-device');
    final key = await hierarchy.VaultKeyHierarchy(mvk).metadataKey();
    Future<String> wrap(String value) async => hierarchy
        .b64urlEncode(await hierarchy.aesGcmWrap(key, utf8.encode(value)));
    for (final id in ['file-a', 'file-b']) {
      rows.add({
        'id': id,
        'file_name': null,
        'saved_name': null,
        'content_type': null,
        'file_name_ciphertext': await wrap('QA duplicate.txt'),
        'content_type_ciphertext': await wrap('text/plain'),
        'file_size': 352,
        'needs_naming': true,
        'relative_path': 'qa/nested/$id.txt',
        'encrypted_file_data': 'synthetic-content-$id',
      });
    }
  }

  Future<http.Response> respond(http.Request request) async {
    if (request.url.host != 'localhost' || request.url.port != 8000) {
      throw StateError('External destinations blocked');
    }
    requests.add(request);
    Object response;
    switch ('${request.method} ${request.url.path}') {
      case 'POST /vault-stats':
        response = {'file_count': rows.length, 'storage_used_bytes': 704};
        break;
      case 'POST /list-files':
        response = {
          'files': rows.map((row) => Map<String, dynamic>.from(row)).toList(),
        };
        await pendingFiles?.future;
        break;
      case 'GET /folders':
        response = {
          'path': '',
          'folders': [],
          'files': rows.map((row) => Map<String, dynamic>.from(row)).toList(),
        };
        await pendingFolder?.future;
        break;
      case 'POST /list-secure-items':
        response = {'items': []};
        break;
      case 'GET /vault/ciphertext/vault-items':
        response = [];
        break;
      case 'GET /vault/ciphertext/vault-ai-memory':
        response = [];
        break;
      case 'POST /vault/ciphertext/uploaded-files':
        final body = Map<String, dynamic>.from(jsonDecode(request.body) as Map);
        expect(body.keys.toSet(), {'file_id', 'saved_name_ciphertext'});
        expect(body.values, isNot(contains('123456')));
        writes.add(body);
        await pending?.future;
        if (failWrite) return http.Response('{}', 503);
        final index = rows.indexWhere((row) => row['id'] == body['file_id']);
        expect(index, greaterThanOrEqualTo(0));
        rows[index] = {
          ...rows[index],
          'saved_name_ciphertext': body['saved_name_ciphertext'],
          'needs_naming': false,
        };
        response = {
          'file_id': badAck ? 'wrong-id' : body['file_id'],
          'updated_columns': ['saved_name_ciphertext'],
        };
        break;
      default:
        throw StateError(
            'Unexpected isolated operation: ${request.method} ${request.url.path}');
    }
    return http.Response(jsonEncode(response), 200,
        headers: {'content-type': 'application/json'});
  }

  Future<T> run<T>(Future<T> Function() action) =>
      http.runWithClient(action, () => MockClient(respond));

  Future<String> savedName(int index) async {
    final key = await hierarchy.VaultKeyHierarchy(mvk).metadataKey();
    return utf8.decode(await hierarchy.aesGcmUnwrap(
        key,
        hierarchy
            .b64urlDecode(rows[index]['saved_name_ciphertext'] as String)));
  }

  void dispose() {
    app.unlocked = false;
    app.dispose();
    ZkActiveMvk.clear();
    VaultCryptoRegistry.clear(reason: 'file-rename-fixture-cleanup');
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
        home: const ChatDashboardPage(),
      ),
    );

Future<void> _section(WidgetTester tester, String section) async {
  await tester.pump(const Duration(seconds: 5));
  await tester.pumpAndSettle();
  await tester.tap(find.byIcon(Icons.menu_rounded));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(ValueKey('sidebar_section_$section')));
  await tester.pumpAndSettle();
}

Future<void> _send(WidgetTester tester, String text) async {
  await tester.pump(const Duration(seconds: 5));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('chat_composer_field')), text);
  await tester.pump();
  await tester.tap(find.byKey(const Key('composer_send_button')));
  await tester.pumpAndSettle();
}

Future<void> _rename(WidgetTester tester, String id, String name) async {
  await tester.tap(find.byKey(ValueKey('files_file_rename_$id')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('saved_file_rename_name')), name);
  await tester.tap(find.byKey(const Key('saved_file_rename_save')));
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
    ZkActiveMvk.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            const MethodChannel('com.llfbandit.record/messages'), null);
  });

  test('name validation rejects empty, controls, and overlong input', () {
    for (final name in ['', '   ', 'line\nbreak', 'nul\u0000name', 'x' * 121]) {
      expect(savedFileNameValidationError(name), isNotNull);
    }
    expect(savedFileNameValidationError('  QA photo 🗝️  '), isNull);
    expect(normalizeSavedFileName('  QA photo  '), 'QA photo');
  });

  test('chat parser requires explicit targets and preserves names', () {
    expect(
        parseSavedFileRenameCommand('Rename QA photo to QA Photo Edited')
            ?.target,
        'QA photo');
    final quoted = parseSavedFileRenameCommand(
        'rename file "Road to home.txt" to "Road Edited"');
    expect(quoted?.target, 'Road to home.txt');
    expect(quoted?.name, 'Road Edited');
    expect(parseSavedFileRenameCommand('rename it to anything'), isNull);
    expect(
        parseSavedFileRenameCommand('rename my Netflix login to work'), isNull);
    expect(parseSavedFileRenameCommand('rename memory One to Two'), isNull);
    expect(parseSavedFileRenameCommand('rename file One to')?.name, '');
  });

  test('controller is single-flight, cancellable before save, and session-safe',
      () async {
    var current = true;
    var writes = 0;
    var applies = 0;
    final gate = Completer<void>();
    final c = SavedFileRenameController(
        fileId: 'stable-a', accessIsCurrent: () => current);
    final first = c.save(
        name: 'new',
        write: (_) async {
          writes++;
          await gate.future;
        },
        onCommitted: (_) => applies++);
    expect(c.busy, isTrue);
    expect(c.cancel(), isFalse);
    expect(
        await c.save(
            name: 'other',
            write: (_) async {
              writes++;
            },
            onCommitted: (_) => applies++),
        SavedFileRenameOutcome.inFlight);
    current = false;
    gate.complete();
    expect(await first, SavedFileRenameOutcome.stale);
    expect(writes, 1);
    expect(applies, 0);
    final cancelled = SavedFileRenameController(
        fileId: 'stable-b', accessIsCurrent: () => true);
    expect(cancelled.cancel(), isTrue);
    expect(
        await cancelled.save(
            name: 'new',
            write: (_) async {
              writes++;
            },
            onCommitted: (_) => applies++),
        SavedFileRenameOutcome.cancelled);
    expect(writes, 1);
  });

  test('a committed controller never repeats the write or UI application',
      () async {
    var writes = 0;
    var applies = 0;
    final c = SavedFileRenameController(
        fileId: 'stable-a', accessIsCurrent: () => true);
    Future<SavedFileRenameOutcome> save(String name) => c.save(
        name: name,
        write: (_) async {
          writes++;
        },
        onCommitted: (_) => applies++);
    expect(await save('first'), SavedFileRenameOutcome.saved);
    expect(await save('second'), SavedFileRenameOutcome.saved);
    expect(writes, 1);
    expect(applies, 1);
  });

  test('ciphertext-only API refuses legacy fallback and wrong commit ack',
      () async {
    final f = _Fixture();
    await f.unlock();
    try {
      await f.run(() async {
        final client = VaultAIClient(baseUrl: 'http://localhost:8000');
        ZkActiveMvk.clear();
        await expectLater(
            client.nameVaultFile(
                vaultName: f.app.vaultName!,
                fileId: 'file-a',
                savedName: 'Private title',
                pin: '123456',
                authToken: f.app.sessionToken!,
                requireCiphertext: true),
            throwsStateError);
        expect(f.writes, isEmpty);
        ZkActiveMvk.set(
            mvk: f.mvk,
            vaultId: f.app.vaultId!,
            vaultHandle: f.app.vaultHandle!);
        f.badAck = true;
        await expectLater(
            client.nameVaultFile(
                vaultName: f.app.vaultName!,
                fileId: 'file-a',
                savedName: 'Private title',
                pin: '123456',
                authToken: f.app.sessionToken!,
                requireCiphertext: true),
            throwsStateError);
        expect(jsonEncode(f.writes.single), isNot(contains('Private title')));
        expect(await f.savedName(0), 'Private title');
      });
    } finally {
      f.dispose();
    }
  });

  testWidgets(
      'duplicate original filename lookup stays local and leaves both files intact',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    final originals =
        f.rows.map((row) => Map<String, dynamic>.from(row)).toList();
    try {
      await f.run(() async {
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        await _send(tester, 'Show me my QA duplicate.txt file');
        const reply = 'Multiple saved files match "QA duplicate.txt file". '
            'Open Files and choose the one you want.';
        expect(find.text(reply), findsOneWidget);
        final chat =
            tester.widget<ChatMessageList>(find.byType(ChatMessageList));
        expect(chat.messages.last.text, reply);
        expect(
            f.requests.where((request) => request.url.path == '/chat'),
            isEmpty,
            reason: 'ambiguous private filenames must never fall through to AI');
        expect(f.writes, isEmpty);
        expect(f.rows, originals,
            reason: 'IDs, content bytes, paths and encrypted names stay intact');
        expect(f.rows.map((row) => row['id']), ['file-a', 'file-b']);
        expect(tester.takeException(), isNull);
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  });

  testWidgets(
      'real Files Rename/cancel/validation commits only stable-ID encrypted metadata',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    final originalRows =
        f.rows.map((row) => Map<String, dynamic>.from(row)).toList();
    try {
      await f.run(() async {
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        await _section(tester, 'files');
        await tester
            .tap(find.byKey(const ValueKey('files_file_rename_file-a')));
        await tester.pumpAndSettle();
        await tester.enterText(
            find.byKey(const Key('saved_file_rename_name')), '');
        await tester.tap(find.byKey(const Key('saved_file_rename_save')));
        await tester.pumpAndSettle();
        expect(find.text('Enter a file name.'), findsOneWidget);
        await tester.tap(find.byKey(const Key('saved_file_rename_cancel')));
        await tester.pumpAndSettle();
        expect(f.writes, isEmpty);
        f.pending = Completer<void>();
        await tester
            .tap(find.byKey(const ValueKey('files_file_rename_file-a')));
        await tester.pumpAndSettle();
        await tester.enterText(
            find.byKey(const Key('saved_file_rename_name')), 'Unique title');
        await tester.tap(find.byKey(const Key('saved_file_rename_save')));
        await tester.pump();
        await tester.tap(find.byKey(const Key('saved_file_rename_save')));
        await tester.pump();
        expect(f.writes, hasLength(1));
        expect(find.text('Unique title'), findsOneWidget,
            reason: 'only entered field changes before server commit');
        expect(
            tester
                .widget<TextButton>(
                    find.byKey(const Key('saved_file_rename_cancel')))
                .onPressed,
            isNull);
        f.pending!.complete();
        await tester.pumpAndSettle();
        expect(await f.savedName(0), 'Unique title');
        expect(f.rows[1], originalRows[1]);
        for (final key in [
          'file_name_ciphertext',
          'content_type_ciphertext',
          'file_size',
          'relative_path',
          'encrypted_file_data'
        ]) {
          expect(f.rows[0][key], originalRows[0][key]);
        }
        expect(find.byType(SavedFileRenameDialog), findsNothing);
        expect(find.text('Unique title'), findsOneWidget);
        await _rename(tester, 'file-b', 'Unique title');
        expect(await f.savedName(1), 'Unique title');
        expect(f.rows, hasLength(2),
            reason: 'same title does not merge file IDs');
        expect(f.rows[1]['encrypted_file_data'],
            originalRows[1]['encrypted_file_data']);
        await tester.tap(find.byKey(const Key('files_refresh_button')));
        await tester.pumpAndSettle();
        expect(find.text('Unique title'), findsNWidgets(2));
        await _section(tester, 'chat');
        await _send(tester, 'Rename Unique title to should not happen');
        expect(find.textContaining('Several files match'), findsOneWidget);
        expect(f.writes, hasLength(2));
        expect(tester.takeException(), isNull);
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  });

  for (final delayedPath in ['/list-files', '/folders']) {
    testWidgets(
        'a pre-rename $delayedPath response cannot replace committed labels',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(430, 932));
      final f = _Fixture();
      await tester.runAsync(f.unlock);
      final originalRows =
          f.rows.map((row) => Map<String, dynamic>.from(row)).toList();
      final readGate = Completer<void>();
      try {
        await f.run(() async {
          await tester.pumpWidget(_dashboard(f.app));
          await tester.pumpAndSettle();
          await _section(tester, 'files');
          await _rename(tester, 'file-a', 'Before refresh');
          final readsBeforeRefresh =
              f.requests.where((r) => r.url.path == delayedPath).length;
          if (delayedPath == '/list-files') {
            f.pendingFiles = readGate;
          } else {
            f.pendingFolder = readGate;
          }
          await tester.tap(find.byKey(const Key('files_refresh_button')));
          if (delayedPath == '/list-files') {
            // The Files spinner stays active while this inventory read waits.
            // Chat can rename the already loaded stable ID during that read.
            await tester.pump();
            await tester.tap(find.byIcon(Icons.menu_rounded));
            // Start the drawer animation before advancing its elapsed time.
            await tester.pump();
            await tester.pump(const Duration(milliseconds: 400));
            final chatSection =
                find.byKey(const ValueKey('sidebar_section_chat')).hitTestable();
            expect(chatSection, findsOneWidget);
            await tester.tap(chatSection);
            await tester.pumpAndSettle();
          } else {
            await tester.pumpAndSettle();
          }
          expect(
              f.requests.where((r) => r.url.path == delayedPath).length,
              readsBeforeRefresh + 1,
              reason: 'the delayed response captured the old name before save');
          expect(readGate.isCompleted, isFalse);
          if (delayedPath == '/list-files') {
            await _send(tester, 'Rename Before refresh to Current title');
            expect(find.text('Renamed the file to "Current title".'),
                findsOneWidget);
          } else {
            await _rename(tester, 'file-a', 'Current title');
            expect(find.text('Current title'), findsOneWidget);
          }
          expect(await f.savedName(0), 'Current title');
          expect(f.writes.map((body) => body['file_id']), ['file-a', 'file-a']);
          readGate.complete();
          await tester.pumpAndSettle();
          if (delayedPath == '/folders') {
            await _section(tester, 'chat');
          }
          await _send(tester, 'Show me Current title');
          final chat =
              tester.widget<ChatMessageList>(find.byType(ChatMessageList));
          expect(chat.messages.last.kind, ChatMessage.kVaultFile);
          expect(chat.messages.last.fileId, 'file-a');
          expect(chat.messages.last.payload?['saved_name'], 'Current title',
              reason: 'a delayed inventory response cannot revert local lookup');
          expect(f.requests.where((r) => r.url.path == '/chat'), isEmpty);
          await _section(tester, 'files');
          expect(find.text('Current title'), findsOneWidget,
              reason: 'a delayed folder response cannot revert the Files label');
          expect(find.text('Before refresh'), findsNothing);
          expect(f.rows, hasLength(originalRows.length));
          expect(f.rows[1], originalRows[1]);
          for (var i = 0; i < f.rows.length; i++) {
            for (final key in [
              'id',
              'file_name_ciphertext',
              'content_type_ciphertext',
              'file_size',
              'relative_path',
              'encrypted_file_data',
            ]) {
              expect(f.rows[i][key], originalRows[i][key]);
            }
          }
          expect(tester.takeException(), isNull);
        });
      } finally {
        if (!readGate.isCompleted) readGate.complete();
        await tester.pumpWidget(const SizedBox.shrink());
        f.dispose();
        await tester.binding.setSurfaceSize(null);
      }
    });
  }

  testWidgets(
      'chat rename stays local and session-changed commit cannot update labels',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    final f = _Fixture();
    await tester.runAsync(f.unlock);
    // Keep one filename unique so the chat target is explicit and unambiguous.
    f.rows.removeLast();
    try {
      await f.run(() async {
        await tester.pumpWidget(_dashboard(f.app));
        await tester.pumpAndSettle();
        await _send(tester, 'Show me QA duplicate.txt');
        await _send(tester, 'Rename QA duplicate.txt to Chat Edited');
        expect(await f.savedName(0), 'Chat Edited');
        expect(find.text('Renamed the file to "Chat Edited".'), findsOneWidget);
        final chat =
            tester.widget<ChatMessageList>(find.byType(ChatMessageList));
        final previousCard = chat.messages.singleWhere((msg) =>
            msg.kind == ChatMessage.kVaultFile && msg.fileId == 'file-a');
        expect(previousCard.payload?['saved_name'], 'Chat Edited',
            reason:
                'existing virtualized chat card label updates after commit');
        expect(previousCard.fileName, 'QA duplicate.txt');
        await _section(tester, 'files');
        expect(find.text('Chat Edited'), findsOneWidget);
        f.pending = Completer<void>();
        await tester
            .tap(find.byKey(const ValueKey('files_file_rename_file-a')));
        await tester.pumpAndSettle();
        await tester.enterText(
            find.byKey(const Key('saved_file_rename_name')), 'Stale title');
        await tester.tap(find.byKey(const Key('saved_file_rename_save')));
        await tester.pump();
        f.app.sessionToken = 'different-session';
        f.pending!.complete();
        await tester.pumpAndSettle();
        expect(
            find.text(
                'Could not rename the file. Your entered name is still here; please try again.'),
            findsOneWidget);
        await tester.tap(find.byKey(const Key('saved_file_rename_cancel')));
        await tester.pumpAndSettle();
        expect(find.text('Chat Edited'), findsOneWidget);
        expect(find.text('Stale title'), findsNothing,
            reason: 'old response cannot alter current inventory labels');
      });
    } finally {
      await tester.pumpWidget(const SizedBox.shrink());
      f.dispose();
      await tester.binding.setSurfaceSize(null);
    }
  });

  testWidgets(
      'failed writes preserve the entered name and do not report success',
      (tester) async {
    final c = SavedFileRenameController(
        fileId: 'stable-a', accessIsCurrent: () => true);
    await tester.pumpWidget(MaterialApp(
        home: Builder(
            builder: (context) => TextButton(
                onPressed: () => showDialog<void>(
                    context: context,
                    builder: (_) => SavedFileRenameDialog(
                          initialName: 'Old',
                          controller: c,
                          onSave: (name) => c.save(
                              name: name,
                              write: (_) async =>
                                  throw StateError('safe synthetic failure'),
                              onCommitted: (_) =>
                                  fail('must not apply failed write')),
                        )),
                child: const Text('Rename')))));
    await tester.tap(find.text('Rename'));
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byKey(const Key('saved_file_rename_name')), 'Kept input');
    await tester.tap(find.byKey(const Key('saved_file_rename_save')));
    await tester.pumpAndSettle();
    expect(find.text('Kept input'), findsOneWidget);
    expect(find.textContaining('Could not rename the file.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('saved_file_rename_cancel')));
    await tester.pumpAndSettle();
  });
}
