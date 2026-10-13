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

// All identities and file bytes are synthetic. HTTP is allowlisted in-process;
// selecting a file must not upload it or dispatch chat before Send is pressed.
class _FixtureApp extends AppState {
  @override
  Future<void> refreshVaultStats() async {}
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

FilePickerResult _selected({bool readable = true}) => FilePickerResult([
      PlatformFile(
        name: 'synthetic-file.txt',
        size: 4,
        bytes: readable ? Uint8List.fromList([1, 2, 3, 4]) : null,
      ),
    ]);

Future<AppState> _fixture() async {
  final app = _FixtureApp()
    ..sessionToken = 'synthetic-picker-token'
    ..vaultId = 'synthetic-picker-vault'
    ..vaultName = 'Synthetic picker vault'
    ..vaultHandle = 'synthetic-picker-handle'
    ..displayName = 'QA'
    ..authed = true
    ..billingLoadState = BillingLoadState.loaded
    ..billingIncludedBytes = kVaultStorageLimitBytes
    ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
  // This VM fixture runs on macOS, not on an Android device with the native
  // library. Seed the same synthetic context with the software KDF, then
  // restore the requested platform BEFORE rendering the actual UI.
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
  app.unlocked = true;
  expect(app.unlocked, isTrue);
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
    {Size size = const Size(430, 932)}) async {
  await tester.binding.setSurfaceSize(size);
  final app = (await tester.runAsync(_fixture))!;
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
      await tester.pumpWidget(_dashboard(app));
      await tester.pumpAndSettle();
      expect(find.text('Synthetic PIN route'), findsNothing);
      await action(app, picker, requests);
      expect(tester.takeException(), isNull);
    },
        () => MockClient((request) async {
              requests.add('${request.method} ${request.url.path}');
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
    VaultCryptoRegistry.clear(reason: 'picker-regression-cleanup');
    setApiClientDeviceId('');
    await tester.binding.setSurfaceSize(null);
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
