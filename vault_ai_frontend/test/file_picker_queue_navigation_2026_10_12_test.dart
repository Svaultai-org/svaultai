import 'dart:async';
import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:file_picker/file_picker.dart';
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
import 'package:vault_ai_frontend/services/zk_active_sk_vault.dart';
import 'package:vault_ai_frontend/services/zk_auth_service.dart'
    show kSignedFileCreateClientEnabled;
import 'package:vault_ai_frontend/services/folder_picker.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/ui/chat/storage_limit_dialog.dart';

// All identities and file bytes are synthetic. HTTP is allowlisted in-process;
// selecting a file must not upload it or dispatch chat before Send is pressed.
class _FixtureApp extends AppState {
  int statsRefreshCalls = 0;

  @override
  Future<void> refreshVaultStats() async {
    statsRefreshCalls++;
  }
}

class _Picker extends FilePicker {
  int calls = 0;
  Future<FilePickerResult?> Function() action = () async => null;

  @override
  Future<FilePickerResult?> pickFiles({
    String? dialogTitle,
    String? initialDirectory,
    FileType type = FileType.any,
    List<String>? allowedExtensions,
    Function(FilePickerStatus)? onFileLoading,
    bool allowCompression = false,
    int compressionQuality = 0,
    bool allowMultiple = false,
    bool withData = false,
    bool withReadStream = false,
    bool lockParentWindow = false,
    bool readSequential = false,
  }) {
    calls++;
    expect(type, FileType.any);
    expect(allowMultiple, isTrue);
    expect(withData, isFalse);
    expect(withReadStream, isTrue);
    return action();
  }
}

class _SyntheticFolderPicker implements FolderPickerService {
  @override
  bool get isSupported => true;

  @override
  String get unsupportedReason => '';

  @override
  Future<FolderPickResult?> pickFolder() async => FolderPickResult(
        rootFolderName: 'SyntheticFolder',
        files: <PickedFolderFile>[
          PickedFolderFile(
            name: 'holiday.jpg',
            relativePath: 'SyntheticFolder/nested/holiday.jpg',
            size: 4,
            readBytes: () async => Uint8List.fromList(<int>[1, 2, 3, 4]),
          ),
        ],
      );
}

FilePickerResult _selected({bool readable = true}) => FilePickerResult([
      PlatformFile(
        name: 'synthetic-file.txt',
        size: 4,
        bytes: readable ? Uint8List.fromList([1, 2, 3, 4]) : null,
      ),
    ]);

FilePickerResult _selectedTwo() => FilePickerResult([
      PlatformFile(name: 'synthetic-a.txt', size: 4,
          bytes: Uint8List.fromList([1, 2, 3, 4])),
      PlatformFile(name: 'synthetic-b.txt', size: 4,
          bytes: Uint8List.fromList([5, 6, 7, 8])),
    ]);

String _signedToken(int offerBits) => base64Url.encode(
      <int>[3, offerBits, ...List<int>.filled(48, 7)],
    ).replaceAll('=', '');

Future<AppState> _fixture({
  bool signedCreate = false,
  bool signedReadsWithoutCreate = false,
}) async {
  assert(!(signedCreate && signedReadsWithoutCreate));
  final app = _FixtureApp()
    ..sessionToken = signedCreate
        ? _signedToken(8)
        : signedReadsWithoutCreate
            ? _signedToken(7)
            : 'synthetic-picker-token'
    ..vaultId = 'synthetic-picker-vault'
    ..vaultName = 'Synthetic picker vault'
    ..vaultHandle = 'synthetic-picker-handle'
    ..displayName = 'QA'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
  st.SessionTermination.instance.bindSession(app.sessionToken!);
  if (kPrivateOnlyUnlockEnabled) {
    installZkPrivateOnlyUnlockKeys(
      app: app,
      origin: ZkPrivateUnlockOrigin.login,
      sessionToken: app.sessionToken!,
      vaultId: app.vaultId!,
      vaultName: app.vaultName!,
      vaultHandle: app.vaultHandle!,
      mvk: SecretKey(List.filled(32, 4)),
      skVault: SecretKey(List.filled(32, 5)),
    );
    expect(PrivateZkPinTransportSession.active, isTrue);
    expect(zkPrivateUnlockCredentialStateForTesting(), {
      'pin_cache_entries': 0,
      'legacy_key_entries': 0,
      'has_pbkdf2_context': false,
    });
  } else {
    // Ordinary-build fixture uses a synthetic PIN only for legacy regressions.
    final fixturePlatform = debugDefaultTargetPlatformOverride;
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await deriveAndInstallCryptoContext(
        vaultId: app.vaultId!,
        vaultName: app.vaultName!,
        pin: '123456',
        pinSaltBase64: base64Encode(List.filled(16, 4)),
        iterations: 1,
        source: 'file-picker-regression-fixture',
      );
    } finally {
      debugDefaultTargetPlatformOverride = fixturePlatform;
    }
    ZkActiveMvk.set(
      mvk: SecretKey(List.filled(32, 4)),
      vaultId: app.vaultId!,
      vaultHandle: app.vaultHandle!,
    );
  }
  app.unlocked = true;
  expect(app.unlocked, isTrue);
  return app;
}

Widget _dashboard(AppState app, {FolderPickerService? folderPicker}) =>
    ChangeNotifierProvider<AppState>.value(
      value: app,
      child: MaterialApp(
        theme: ThemeData.dark(useMaterial3: true),
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        routes: {'/pin': (_) => const Text('Synthetic PIN route')},
        home: ChatDashboardPage(folderPickerOverride: folderPicker),
      ),
    );

Future<void> _openFiles(WidgetTester tester) async {
  await tester.tap(find.byIcon(Icons.menu_rounded));
  await tester.pumpAndSettle();
  final tile = find.byKey(const ValueKey('sidebar_section_files'));
  await tester.ensureVisible(tile);
  await tester.tap(tile);
  await tester.pumpAndSettle();
  expect(find.byKey(const Key('attachment_menu_button')), findsNothing);
}

Future<void> _createFile(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('top_nav_create_button')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('create_choice_file')));
  await tester.pumpAndSettle();
}

Future<void> _chatFile(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('attachment_menu_button')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('attachment_menu_upload_file')));
  await tester.pumpAndSettle();
}

Future<void> _withDashboard(WidgetTester tester,
    Future<void> Function(AppState, _Picker, List<String>) action,
    {Size size = const Size(430, 932),
    bool signedCreate = false,
    bool signedReadsWithoutCreate = false,
    FolderPickerService? folderPicker,
    Future<http.Response> Function(http.Request)? respond}) async {
  await tester.binding.setSurfaceSize(size);
  final app = (await tester.runAsync(
    () => _fixture(
      signedCreate: signedCreate,
      signedReadsWithoutCreate: signedReadsWithoutCreate,
    ),
  ))!;
  final picker = _Picker();
  FilePicker? previous;
  try {
    previous = FilePicker.platform;
  } catch (_) {
    // The platform plugin need not be initialized in this offline harness.
  }
  FilePicker.platform = picker;
  final requests = <String>[];
  setApiClientDeviceId('synthetic-picker-device');
  try {
    await http.runWithClient(() async {
      await tester.pumpWidget(_dashboard(app, folderPicker: folderPicker));
      await tester.pumpAndSettle();
      expect(find.text('Synthetic PIN route'), findsNothing);
      await action(app, picker, requests);
      expect(tester.takeException(), isNull);
    },
        () => MockClient((request) async {
              requests.add('${request.method} ${request.url.path}');
              if (respond != null) return respond(request);
              final Object body;
              switch ('${request.method} ${request.url.path}') {
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
                case 'GET /vault/files/metadata':
                  body = {
                    'records': [],
                    'has_more': false,
                    'next_after_file_id': '',
                  };
                  break;
                case 'GET /vault/file-v2':
                  body = {'files': []};
                  break;
                default:
                  throw StateError('Unexpected fixture request');
              }
              return http.Response(jsonEncode(body), 200,
                  headers: {'content-type': 'application/json'});
            }));
  } finally {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
    if (previous != null) FilePicker.platform = previous;
    app.unlocked = false;
    app.dispose();
    ZkActiveMvk.clear();
    ZkActiveSkVault.clear();
    PrivateZkPinTransportSession.clear();
    st.SessionTermination.instance.reset();
    VaultCryptoRegistry.clear(reason: 'picker-regression-cleanup');
    setApiClientDeviceId('');
    await tester.binding.setSurfaceSize(null);
  }
}

class _PrivateV2Server {
  Map<String, dynamic>? manifest;
  final chunks = <int, String>{};
  bool published = false;
  bool denyFirstPublishForStorage = false;
  int manifestPosts = 0;
  int chunkPuts = 0;
  int publishCalls = 0;
  final publishedIds = <String>[];

  Future<http.Response> respond(http.Request request) async {
    final path = request.url.path;
    final body = request.body;
    expectSync(request.headers['x-svaultai-file-v2-reader'], '1');
    expectSync(body, isNot(contains('123456')));
    expectSync(body, isNot(contains('synthetic-file.txt')));
    expectSync(body, isNot(contains('Please analyze my attachment')));
    expectSync(body, isNot(contains('"pin"')));
    if (request.method == 'GET' && path.endsWith('/manifest')) {
      if (manifest == null) {
        return http.Response('{"detail":"file_v2_not_found"}', 404);
      }
      return http.Response(jsonEncode(<String, dynamic>{
        ...manifest!,
        'lifecycle_state': published ? 'client_v2_ready' : 'file_v2_written',
        'verification_state': published ? 'client_verified' : 'unverified',
      }), 200);
    }
    if (request.method == 'POST' && path == '/vault/file-v2/manifest') {
      manifestPosts++;
      manifest = Map<String, dynamic>.from(jsonDecode(body) as Map);
      return http.Response('{"created":true}', 200);
    }
    if (path.contains('/chunk/') && request.method == 'GET') {
      final index = int.parse(path.split('/').last);
      return chunks.containsKey(index)
          ? http.Response(jsonEncode(<String, dynamic>{
              'file_id': manifest!['file_id'],
              'chunk_index': index,
              'ciphertext': chunks[index],
            }), 200)
          : http.Response('{"detail":"file_v2_chunk_not_found"}', 404);
    }
    if (request.method == 'PUT' && path == '/vault/file-v2/chunk') {
      chunkPuts++;
      final decoded = Map<String, dynamic>.from(jsonDecode(body) as Map);
      chunks[decoded['chunk_index'] as int] = decoded['ciphertext'] as String;
      return http.Response('{"stored":true}', 200);
    }
    if (request.method == 'POST' && path.endsWith('/publish-new')) {
      publishCalls++;
      publishedIds.add(manifest!['file_id'] as String);
      if (denyFirstPublishForStorage && publishCalls == 1) {
        return http.Response(
            '{"detail":{"message":"Synthetic storage cap reached"}}',
            413);
      }
      published = true;
      return http.Response(jsonEncode(<String, dynamic>{
        'file_id': manifest!['file_id'],
        'status': 'published',
      }), 200);
    }
    if (request.method == 'GET' && path == '/vault/files/metadata') {
      return http.Response(jsonEncode(<String, dynamic>{
        'records': <Map<String, dynamic>>[
          {
            'file_id': manifest!['file_id'],
            'file_size': 4,
            'lifecycle_state': 'client_v2_ready',
            'verification_state': 'client_verified',
          },
        ],
        'has_more': false,
        'next_after_file_id': manifest!['file_id'],
      }), 200);
    }
    if (request.method == 'GET' && path == '/vault/file-v2') {
      return http.Response(jsonEncode(<String, dynamic>{
        'files': <Map<String, dynamic>>[
          {
            'file_id': manifest!['file_id'],
            'lifecycle_state': 'client_v2_ready',
            'verification_state': 'client_verified',
          },
        ],
      }), 200);
    }
    if (request.method == 'GET' && path == '/folders') {
      return http.Response('{"path":"","folders":[],"files":[]}', 200);
    }
    fail('Unexpected private request ${request.method} $path');
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
            const MethodChannel('com.llfbandit.record/messages'), null);
  });

  testWidgets('actual Create header opens one menu and File never opens Login',
      (tester) async {
    for (final size in [const Size(430, 932), const Size(1280, 900)]) {
      await _withDashboard(tester, (app, picker, requests) async {
        await tester.tap(find.byKey(const Key('top_nav_create_button')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('vault_create_menu')), findsOneWidget);
        expect(find.byKey(const Key('create_choice_login')), findsOneWidget);
        expect(find.byKey(const Key('create_choice_file')), findsOneWidget);
        expect(find.byKey(const Key('create_choice_memory')), findsOneWidget);
        await tester.tap(find.byKey(const Key('create_choice_file')));
        await tester.pumpAndSettle();
        expect(picker.calls, 1);
        expect(find.byKey(const Key('vault_create_menu')), findsNothing);
        expect(find.text('New Login'), findsNothing);
        expect(find.text('Save login'), findsNothing);
      }, size: size);
    }
  },
      variant:
          TargetPlatformVariant({TargetPlatform.iOS, TargetPlatform.android}));

  testWidgets('Create File from Files reveals the queue in Chat without upload',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      await _openFiles(tester);
      final before = List<String>.of(requests);
      picker.action = () async => _selected();
      await _createFile(tester);
      expect(picker.calls, 1);
      expect(find.byType(ChatAttachmentPanel), findsOneWidget);
      expect(find.text('synthetic-file.txt'), findsOneWidget);
      expect(find.text('1 attachment(s) ready'), findsOneWidget);
      expect(find.byKey(const Key('attachment_menu_button')), findsOneWidget);
      expect(find.text('Save login'), findsNothing);
      expect(requests, before, reason: 'selection never uploads or sends chat');
    });
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('Chat plus File opens the same picker and shows its selection',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      final before = List<String>.of(requests);
      picker.action = () async => _selected();
      await _chatFile(tester);
      expect(picker.calls, 1);
      expect(find.byType(ChatAttachmentPanel), findsOneWidget);
      expect(find.text('synthetic-file.txt'), findsOneWidget);
      expect(requests, before);
    });
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('private V2 Send never follows upload with PIN routes or chat',
      (tester) async {
    Map<String, dynamic>? manifest;
    final chunks = <int, String>{};
    var published = false;
    var publishCalls = 0;
    await _withDashboard(tester, (app, picker, requests) async {
      picker.action = () async => _selected();
      await _createFile(tester);
      // The live MVK is sufficient to choose V2 even if a transient UI state
      // no longer has the handle string. It must never choose PIN follow-ups.
      app.vaultHandle = null;
      final statsBeforeSend = (app as _FixtureApp).statsRefreshCalls;
      await tester.enterText(
        find.byKey(const Key('chat_composer_field')),
        'Please explain this attached file',
      );
      // The fixture's transient attachment banner covers the composer hit
      // target. Invoke the actual enabled InkWell callback after rendering.
      final send = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      expect(send.onTap, isNotNull);
      send.onTap!();
      await tester.pumpAndSettle();
      expect(find.textContaining('File saved privately.'), findsWidgets);
      expect(publishCalls, 1);
      expect(app.statsRefreshCalls, statsBeforeSend);
      expect(requests, contains('POST /vault/file-v2/manifest'));
      expect(requests, contains('PUT /vault/file-v2/chunk'));
      expect(requests, contains('GET /vault/files/metadata'));
      expect(requests, contains('GET /vault/file-v2'));
      expect(requests, isNot(contains('POST /vault/stats')));
      expect(requests, isNot(contains('POST /list-secure-items')));
      expect(requests, isNot(contains('POST /chat')));
      expect(requests, isNot(contains('POST /list-files')));
      expect(requests, isNot(contains('POST /upload-file')));
      expect(requests, isNot(contains('POST /start-import')));
    }, signedCreate: kSignedFileCreateClientEnabled,
        respond: (request) async {
      final path = request.url.path;
      final body = request.body;
      expectSync(request.headers['x-svaultai-file-v2-reader'], '1');
      expectSync(body, isNot(contains('123456')));
      expectSync(body, isNot(contains('synthetic-file.txt')));
      expectSync(body, isNot(contains('Please explain this attached file')));
      expectSync(body, isNot(contains('"pin"')));
      if (request.method == 'GET' && path.endsWith('/manifest')) {
        if (manifest == null) {
          return http.Response('{"detail":"file_v2_not_found"}', 404);
        }
        return http.Response(
            jsonEncode(<String, dynamic>{
              ...manifest!,
              'lifecycle_state':
                  published ? 'client_v2_ready' : 'file_v2_written',
              'verification_state':
                  published ? 'client_verified' : 'unverified',
            }),
            200);
      }
      if (request.method == 'POST' && path == '/vault/file-v2/manifest') {
        manifest = Map<String, dynamic>.from(jsonDecode(body) as Map);
        return http.Response('{"created":true}', 200);
      }
      if (path.contains('/chunk/') && request.method == 'GET') {
        final index = int.parse(path.split('/').last);
        return chunks.containsKey(index)
            ? http.Response(
                jsonEncode(<String, dynamic>{
                  'file_id': manifest!['file_id'],
                  'chunk_index': index,
                  'ciphertext': chunks[index],
                }),
                200)
            : http.Response('{"detail":"file_v2_chunk_not_found"}', 404);
      }
      if (request.method == 'PUT' && path == '/vault/file-v2/chunk') {
        final decoded = Map<String, dynamic>.from(jsonDecode(body) as Map);
        chunks[decoded['chunk_index'] as int] = decoded['ciphertext'] as String;
        return http.Response('{"stored":true}', 200);
      }
      if (request.method == 'POST' && path.endsWith('/publish-new')) {
        expectSync(jsonDecode(body), <String, dynamic>{'confirm': true});
        published = true;
        publishCalls++;
        return http.Response(
            jsonEncode(<String, dynamic>{
              'file_id': manifest!['file_id'],
              'status': 'published',
            }),
            200);
      }
      if (request.method == 'GET' && path == '/vault/files/metadata') {
        return http.Response(
            jsonEncode(<String, dynamic>{
              'records': <Map<String, dynamic>>[
                {
                  'file_id': manifest!['file_id'],
                  'file_size': 4,
                  'lifecycle_state': 'client_v2_ready',
                  'verification_state': 'client_verified',
                }
              ],
              'has_more': false,
              'next_after_file_id': manifest!['file_id'],
            }),
            200);
      }
      if (request.method == 'GET' && path == '/vault/file-v2') {
        return http.Response(
            jsonEncode(<String, dynamic>{
              'files': <Map<String, dynamic>>[
                {
                  'file_id': manifest!['file_id'],
                  'lifecycle_state': 'client_v2_ready',
                  'verification_state': 'client_verified',
                }
              ],
            }),
            200);
      }
      if (request.method == 'GET' && path == '/folders') {
        return http.Response('{"path":"","folders":[],"files":[]}', 200);
      }
      fail('Unexpected request ${request.method} $path');
    });
  },
      skip: !(kEnableFileV2UiRead && kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('signed create keeps folder pick queued before unsupported batch',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      await tester.tap(find.byKey(const Key('attachment_menu_button')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('attachment_menu_upload_folder')));
      await tester.pumpAndSettle();
      expect(find.text('holiday.jpg'), findsOneWidget);
      final beforeSend = List<String>.of(requests);
      final send = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      send.onTap!();
      await tester.pumpAndSettle();
      expect(find.text('holiday.jpg'), findsOneWidget);
      expect(find.textContaining('Private folder and multiple-file uploads'),
          findsWidgets);
      expect(requests, beforeSend,
          reason: 'the signed offer must not silently skip import semantics');
    }, signedCreate: true, folderPicker: _SyntheticFolderPicker());
  },
      skip: !(kSignedFileCreateClientEnabled &&
          kEnableFileV2UiRead &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('signed create keeps a two-file import queued without writes',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      picker.action = () async => _selectedTwo();
      await _createFile(tester);
      expect(find.text('2 attachment(s) ready'), findsOneWidget);
      final beforeSend = List<String>.of(requests);
      final send = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      send.onTap!();
      await tester.pumpAndSettle();
      expect(find.text('2 attachment(s) ready'), findsOneWidget);
      expect(find.textContaining('Private folder and multiple-file uploads'),
          findsWidgets);
      expect(requests, beforeSend);
    }, signedCreate: true);
  },
      skip: !(kSignedFileCreateClientEnabled &&
          kEnableFileV2UiRead &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('signed client without create offer or private chat uses legacy upload',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      expect(kSignedFileCreateClientEnabled, isTrue);
      expect(kEnableZkPrivateChat, isFalse);
      expect(signedFileCreateOfferedForToken(app.sessionToken!), isFalse);
      expect(signedPrivateChatOfferedForToken(app.sessionToken!), isFalse);
      picker.action = () async => _selected();
      await _createFile(tester);
      expect(
        tester.widget<TextField>(
          find.byKey(const Key('chat_composer_field')),
        ).controller?.text,
        isEmpty,
      );
      final send = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      send.onTap!();
      await tester.pumpAndSettle();
      expect(requests, contains('POST /upload-file'));
      expect(requests, isNot(contains('POST /vault/file-v2/manifest')));
      expect(requests, isNot(contains('POST /chat')));
      expect(find.textContaining('Private file upload is unavailable'),
          findsNothing);
    }, signedReadsWithoutCreate: true, respond: (request) async {
      final path = request.url.path;
      if (path == '/upload-file') {
        expectSync(request.body, contains('123456'));
        return http.Response('{"file_id":"synthetic-legacy-upload"}', 200);
      }
      if (path == '/vault/files/metadata') {
        return http.Response(
          '{"records":[],"has_more":false,"next_after_file_id":""}', 200);
      }
      if (path == '/vault/file-v2') {
        return http.Response('{"files":[]}', 200);
      }
      if (path == '/list-secure-items') {
        return http.Response('{"items":[]}', 200);
      }
      if (path == '/vault/ciphertext/vault-items') {
        return http.Response('[]', 200);
      }
      if (path == '/folders') {
        return http.Response('{"path":"","folders":[],"files":[]}', 200);
      }
      fail('Unexpected unoffered request ${request.method} $path');
    });
  },
      skip: !(kSignedFileCreateClientEnabled &&
          !kEnableZkPrivateChat &&
          kEnableFileV2UiRead &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('unoffered create remains local when private chat is enabled',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      expect(signedFileCreateOfferedForToken(app.sessionToken!), isFalse);
      picker.action = () async => _selected();
      await _createFile(tester);
      final beforeSend = List<String>.of(requests);
      final send = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      send.onTap!();
      await tester.pumpAndSettle();
      expect(find.text('synthetic-file.txt'), findsOneWidget);
      expect(find.textContaining('Private file upload is unavailable'),
          findsWidgets);
      expect(requests, beforeSend,
          reason: 'private chat must not fall through to a PIN or AI route');
    });
  },
      skip: !(kSignedFileCreateClientEnabled &&
          kEnableZkPrivateChat &&
          kEnableFileV2UiRead &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('signed create stops after its session changes mid-upload',
      (tester) async {
    final server = _PrivateV2Server();
    var replaced = false;
    await _withDashboard(tester, (app, picker, requests) async {
      picker.action = () async => _selected();
      await _createFile(tester);
      final send = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      send.onTap!();
      await tester.pumpAndSettle();
      expect(replaced, isTrue);
      expect(server.manifestPosts, 1);
      expect(server.publishCalls, 0);
      expect(requests, isNot(contains('POST /upload-file')));
      expect(requests, isNot(contains('POST /upload-file/init')));
    }, signedCreate: true, respond: (request) async {
      final response = await server.respond(request);
      if (!replaced && request.method == 'POST' &&
          request.url.path == '/vault/file-v2/manifest') {
        replaced = true;
        st.SessionTermination.instance.bindSession('replacement-bearer');
      }
      return response;
    });
  },
      skip: !(kSignedFileCreateClientEnabled &&
          kEnableFileV2UiRead &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('private chat saves V2 attachment and never sends prompt to AI',
      (tester) async {
    final server = _PrivateV2Server();
    await _withDashboard(tester, (app, picker, requests) async {
      picker.action = () async => _selected();
      await _createFile(tester);
      await tester.enterText(find.byKey(const Key('chat_composer_field')),
          'Please analyze my attachment');
      final send = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      send.onTap!();
      await tester.pumpAndSettle();
      expect(find.textContaining('1 file saved privately'), findsWidgets);
      expect(find.textContaining('AI analysis of attached files is not available'),
          findsWidgets);
      expect(find.text('1 attachment(s) ready'), findsNothing);
      expect(server.manifestPosts, 1);
      expect(server.chunkPuts, 1);
      expect(server.publishCalls, 1);
      expect(requests, contains('POST /vault/file-v2/manifest'));
      expect(requests, isNot(contains('POST /chat')));
      expect(requests, isNot(contains('POST /chat/general')));
      expect(requests, isNot(contains('POST /upload-file')));
      expect(requests, isNot(contains('POST /list-files')));
      expect(requests, isNot(contains('POST /imports/start')));
      expect(requests, isNot(contains('POST /vault/stats')));
    }, respond: server.respond);
  },
      skip: !(kEnableZkPrivateChat &&
          kEnableFileV2UiRead &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('private chat storage failure retries same encrypted V2 file',
      (tester) async {
    final server = _PrivateV2Server()..denyFirstPublishForStorage = true;
    await _withDashboard(tester, (app, picker, requests) async {
      picker.action = () async => _selected();
      await _createFile(tester);
      await tester.enterText(find.byKey(const Key('chat_composer_field')),
          'Please analyze my attachment');
      Future<void> send() async {
        final button = tester.widget<InkWell>(find.descendant(
          of: find.byKey(const Key('composer_send_button')),
          matching: find.byType(InkWell),
        ));
        button.onTap!();
        await tester.pumpAndSettle();
      }

      await send();
      expect(find.textContaining('too little storage'), findsWidgets);
      expect(find.text('1 attachment(s) ready'), findsOneWidget);
      expect(server.manifestPosts, 1);
      expect(server.publishCalls, 1);
      app.sessionToken = 'synthetic-replacement-session';
      await send();
      expect(server.publishCalls, 1,
          reason: 'a changed session cannot resume the previous V2 job');
      app.sessionToken = 'synthetic-picker-token';
      await send();
      expect(find.textContaining('1 file saved privately'), findsWidgets);
      expect(find.text('1 attachment(s) ready'), findsNothing);
      expect(server.manifestPosts, 1,
          reason: 'retry must reuse staged manifest and prepared ID');
      expect(server.chunkPuts, 1,
          reason: 'retry must reuse the same encrypted chunk');
      expect(server.publishCalls, 2);
      expect(server.publishedIds.toSet(), hasLength(1));
      expect(requests, isNot(contains('POST /chat')));
      expect(requests, isNot(contains('POST /upload-file')));
    }, respond: server.respond);
  },
      skip: !(kEnableZkPrivateChat &&
          kEnableFileV2UiRead &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('private chat blocks over-limit attachment before network',
      (tester) async {
    final server = _PrivateV2Server();
    await _withDashboard(tester, (app, picker, requests) async {
      app.billingEffectiveLimitBytes = 6;
      picker.action = () async => _selectedTwo();
      await _createFile(tester);
      final send = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      send.onTap!();
      await tester.pumpAndSettle();
      expect(find.byType(NotEnoughStorageDialog), findsOneWidget);
      expect(server.manifestPosts, 0);
      expect(requests, isNot(contains('POST /chat')));
      expect(find.text('2 attachment(s) ready'), findsOneWidget);
    }, respond: server.respond);
  },
      skip: !(kEnableZkPrivateChat &&
          kEnableFileV2UiRead &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('private chat memory command saves ciphertext once',
      (tester) async {
    const prompt = 'Save a new memory with title Synthetic reminder and '
        'content: Bring the blue folder';
    Map<String, dynamic>? stored;
    var writes = 0;
    final requestsWithBodies = <http.Request>[];
    await _withDashboard(tester, (app, picker, requests) async {
      Future<void> sendPrompt() async {
        await tester.enterText(
            find.byKey(const Key('chat_composer_field')), prompt);
        await tester.pump();
        final send = tester.widget<InkWell>(find.descendant(
          of: find.byKey(const Key('composer_send_button')),
          matching: find.byType(InkWell),
        ));
        send.onTap!();
        await tester.pump(const Duration(seconds: 1));
        await tester.pumpAndSettle();
        await tester.runAsync(
            () => Future<void>.delayed(const Duration(milliseconds: 500)));
        await tester.pumpAndSettle();
      }

      await sendPrompt();
      expect(find.textContaining('Memory saved securely'), findsWidgets);
      expect(writes, 1);
      expect(stored, isNotNull);
      await sendPrompt();
      expect(find.textContaining('already'), findsWidgets);
      expect(writes, 1, reason: 'same-title retry cannot duplicate a memory');
      expect(requests, isNot(contains('POST /chat')));
      expect(requests, isNot(contains('POST /chat/general')));
      expect(requestsWithBodies.every((request) =>
          !request.body.contains('Bring the blue folder') &&
          !request.body.contains('"pin"')), isTrue);
    }, respond: (request) async {
      requestsWithBodies.add(request);
      final path = request.url.path;
      if (request.method == 'GET' && path == '/vault/files/metadata') {
        return http.Response('{"records":[],"has_more":false}', 200);
      }
      if (request.method == 'GET' && path == '/vault/file-v2') {
        return http.Response('{"files":[]}', 200);
      }
      if (request.method == 'GET' && path == '/folders') {
        return http.Response('{"path":"","folders":[],"files":[]}', 200);
      }
      if (request.method == 'GET' &&
          path == '/vault/ciphertext/vault-items') {
        return http.Response('[]', 200);
      }
      if (request.method == 'GET' && path == '/vault/items/metadata') {
        return http.Response('{"records":[],"has_more":false}', 200);
      }
      if (path == '/vault/ciphertext/vault-ai-memory') {
        if (request.method == 'POST') {
          writes++;
          stored = Map<String, dynamic>.from(jsonDecode(request.body) as Map);
          expectSync(stored!['replace_existing'], isFalse);
          return http.Response('{"memory_id":"synthetic-id"}', 200);
        }
        return http.Response(jsonEncode(<Map<String, dynamic>>[
          if (stored != null) stored!,
        ]), 200);
      }
      fail('Unexpected private memory request ${request.method} $path');
    });
  },
      skip: !(kPrivateOnlyUnlockEnabled && kEnableZkPrivateChat),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('private chat file rename opens proof gate and cancels cleanly',
      (tester) async {
    final server = _PrivateV2Server();
    await _withDashboard(tester, (app, picker, requests) async {
      picker.action = () async => _selected();
      await _createFile(tester);
      Future<void> send(String text) async {
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

      await send('Save this file');
      expect(find.textContaining('1 file saved privately'), findsWidgets);
      await send('Rename file synthetic-file.txt to Updated.txt');
      expect(find.byKey(const Key('zk_action_pin_field')), findsOneWidget);
      expect(requests, isNot(contains('POST /chat')));
      expect(requests, isNot(contains('POST /chat/general')));
      expect(requests.any((r) => r.endsWith('/rename')), isFalse);
      await tester.tap(find.descendant(
        of: find.byType(AlertDialog), matching: find.text('Cancel'),
      ));
      await tester.pumpAndSettle();
      expect(find.textContaining('File rename cancelled'), findsWidgets);
      expect(requests.any((r) => r.endsWith('/rename')), isFalse);
      await send('Rename file synthetic-file.txt to Save this file');
      expect(find.textContaining('already has that name'), findsWidgets);
      expect(find.byKey(const Key('zk_action_pin_field')), findsNothing);
      expect(requests.any((r) => r.endsWith('/rename')), isFalse);
    }, respond: server.respond);
  },
      skip: !(kPrivateOnlyUnlockEnabled &&
          kEnableZkPrivateChat &&
          kEnableZkFileV2Rename &&
          kEnableNewFileV2Upload),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('private chat refuses to rename an unretired legacy file',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      await tester.enterText(find.byKey(const Key('chat_composer_field')),
          'Rename file Unnamed file to Updated.txt');
      await tester.pump();
      final button = tester.widget<InkWell>(find.descendant(
        of: find.byKey(const Key('composer_send_button')),
        matching: find.byType(InkWell),
      ));
      button.onTap!();
      await tester.pumpAndSettle();
      expect(find.textContaining('private file upgrade'), findsWidgets);
      expect(find.byKey(const Key('zk_action_pin_field')), findsNothing);
      expect(requests.any((r) => r.contains('/rename') ||
          r.contains('/name-file') || r.contains('/chat')), isFalse);
    }, respond: (request) async {
      final path = request.url.path;
      expectSync(request.body, isNot(contains('Updated.txt')));
      expectSync(request.body, isNot(contains('"pin"')));
      if (request.method == 'GET' && path == '/vault/files/metadata') {
        return http.Response(jsonEncode({
          'records': [
            {'file_id': 'synthetic-legacy-file', 'file_size': 4,
             'has_inline_ciphertext': true}
          ],
          'has_more': false,
        }), 200);
      }
      if (request.method == 'GET' && path == '/vault/file-v2') {
        return http.Response('{"files":[]}', 200);
      }
      if (request.method == 'GET' && path == '/folders') {
        return http.Response('{"path":"","folders":[],"files":[]}', 200);
      }
      fail('Unexpected private legacy request ${request.method} $path');
    });
  },
      skip: !(kPrivateOnlyUnlockEnabled &&
          kEnableZkPrivateChat && kEnableZkFileV2Rename &&
          kEnableFileV2UiRead),
      variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('cancel and unreadable selection leave the Files section intact',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      await _openFiles(tester);
      await _createFile(tester);
      expect(
          find.byKey(const Key('files_empty_refresh_button')), findsOneWidget);
      expect(find.byType(ChatAttachmentPanel), findsNothing);
      picker.action = () async => _selected(readable: false);
      await _createFile(tester);
      expect(
          find.byKey(const Key('files_empty_refresh_button')), findsOneWidget);
      expect(find.byType(ChatAttachmentPanel), findsNothing);
      expect(find.textContaining('unreadable'), findsOneWidget);
      expect(picker.calls, 2);
    });
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('picker failure is controlled and permits a later retry',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      await _openFiles(tester);
      picker.action = () async => throw StateError('synthetic-private-error');
      await _createFile(tester);
      expect(find.text('Could not open the file picker. Please try again.'),
          findsOneWidget);
      expect(find.textContaining('synthetic-private-error'), findsNothing);
      expect(
          find.byKey(const Key('files_empty_refresh_button')), findsOneWidget);
      picker.action = () async => _selected();
      await _createFile(tester);
      expect(picker.calls, 2);
      expect(find.byType(ChatAttachmentPanel), findsOneWidget);
    });
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('two File actions while one picker is pending invoke it once',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      await _openFiles(tester);
      final pending = Completer<FilePickerResult?>();
      picker.action = () => pending.future;
      await _createFile(tester);
      await _createFile(tester);
      expect(picker.calls, 1);
      pending.complete(_selected());
      await tester.pumpAndSettle();
      expect(find.text('1 attachment(s) ready'), findsOneWidget);
    });
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('late picker result cannot queue into a changed session',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      await _openFiles(tester);
      final pending = Completer<FilePickerResult?>();
      picker.action = () => pending.future;
      await _createFile(tester);
      app.sessionToken = 'synthetic-replacement-session';
      pending.complete(_selected());
      await tester.pumpAndSettle();
      expect(find.byType(ChatAttachmentPanel), findsNothing);
      expect(
          find.byKey(const Key('files_empty_refresh_button')), findsOneWidget);
    });
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  testWidgets('late picker result after disposal is ignored safely',
      (tester) async {
    await _withDashboard(tester, (app, picker, requests) async {
      final pending = Completer<FilePickerResult?>();
      picker.action = () => pending.future;
      await _chatFile(tester);
      await tester.pumpWidget(const SizedBox.shrink());
      pending.complete(_selected());
      await tester.pumpAndSettle();
      expect(find.byType(ChatAttachmentPanel), findsNothing);
      expect(tester.takeException(), isNull);
    });
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));
}
