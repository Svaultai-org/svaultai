import 'dart:convert';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/file_v2_writer.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

class _App extends AppState {
  @override
  Future<void> refreshVaultStats() async {}
}

void main() {
  for (final withOlderFolder in <bool>[false, true]) {
    testWidgets(
        withOlderFolder
            ? 'older folder stays navigable while private child path stays local'
            : 'private folder navigation never sends its path to the server',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(430, 932));
      final app = _App()
        ..sessionToken = 'synthetic-folder-session'
        ..vaultId = 'synthetic-folder-vault'
        ..vaultName = 'Synthetic vault'
        ..vaultHandle = 'synthetic-folder-handle'
        ..displayName = 'QA'
        ..authed = true
        ..billingLoadState = BillingLoadState.loaded
        ..billingIncludedBytes = kVaultStorageLimitBytes
        ..billingEffectiveLimitBytes = kVaultStorageLimitBytes;
      final oldPlatform = debugDefaultTargetPlatformOverride;
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      try {
        await deriveAndInstallCryptoContext(
          vaultId: app.vaultId!,
          vaultName: app.vaultName!,
          pin: '123456',
          pinSaltBase64: base64Encode(List<int>.filled(16, 5)),
          iterations: 1,
          source: 'synthetic-v2-folder-fixture',
        );
      } finally {
        debugDefaultTargetPlatformOverride = oldPlatform;
      }
      final mvk = SecretKey(List<int>.filled(32, 81));
      ZkActiveMvk.set(
          mvk: mvk, vaultId: app.vaultId!, vaultHandle: app.vaultHandle!);
      st.SessionTermination.instance.bindSession(app.sessionToken!);
      app.unlocked = true;
      setApiClientDeviceId('synthetic-folder-device');
      final prepared = await FileV2Writer(mvk).prepare(
        fileId: FileV2Writer.newFileId(),
        fileName: 'beach.jpg',
        relativePath: withOlderFolder
            ? 'holiday/Beach/beach.jpg'
            : 'Holiday/Beach/beach.jpg',
        bytes: Uint8List.fromList(<int>[1, 2, 3]),
      );
      final folderQueries = <String>[];
      final mock = MockClient((request) async {
        if (request.url.path == '/vault/files/metadata') {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'records': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'file_id': prepared.fileId,
                    'file_size': 3,
                    'lifecycle_state': 'client_v2_ready',
                    'verification_state': 'client_verified',
                  }
                ],
                'has_more': false,
                'next_after_file_id': prepared.fileId,
              }),
              200);
        }
        if (request.url.path == '/vault/file-v2') {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'files': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'file_id': prepared.fileId,
                    'lifecycle_state': 'client_v2_ready',
                    'verification_state': 'client_verified',
                  }
                ],
              }),
              200);
        }
        if (request.url.path.endsWith('/manifest')) {
          return http.Response(
              jsonEncode(<String, dynamic>{
                ...prepared.toManifestBody(),
                'lifecycle_state': 'client_v2_ready',
                'verification_state': 'client_verified',
              }),
              200);
        }
        if (request.url.path == '/folders') {
          folderQueries.add(request.url.query);
          if (request.url.queryParameters['path'] == 'Holiday') {
            expect(withOlderFolder, isTrue);
            return http.Response(
                jsonEncode(<String, dynamic>{
                  'path': 'Holiday',
                  'breadcrumbs': <String>['Holiday'],
                  'folders': <Object>[],
                  'files': <Object>[],
                }),
                200);
          }
          expect(request.url.query, isEmpty,
              reason: 'decrypted V2 folder paths must stay on the device');
          return http.Response(
              jsonEncode(<String, dynamic>{
                'path': '', 'breadcrumbs': <String>[],
                'folders': withOlderFolder
                    ? <Map<String, dynamic>>[
                        <String, dynamic>{
                          'name': 'Holiday',
                          'file_count': 0,
                        }
                      ]
                    : <Object>[],
                // The server sees only this root marker, without its folder path.
                'files': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'id': prepared.fileId,
                    'file_size': 3,
                  }
                ],
              }),
              200);
        }
        if (request.url.path == '/vault/ciphertext/vault-items') {
          return http.Response('[]', 200);
        }
        if (request.url.path == '/list-secure-items') {
          return http.Response('{"items":[]}', 200);
        }
        fail('Unexpected request: ${request.method} ${request.url}');
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
          await tester.tap(find.byIcon(Icons.menu_rounded));
          await tester.pumpAndSettle();
          final tile = find.byKey(const ValueKey('sidebar_section_files'));
          await tester.ensureVisible(tile);
          await tester.tap(tile);
          await tester.pumpAndSettle();
          expect(find.text('Holiday'), findsOneWidget);
          expect(find.byKey(ValueKey('files_file_card_${prepared.fileId}')),
              findsNothing);
          await tester.tap(find.text('Holiday'));
          await tester.pumpAndSettle();
          expect(find.text('Beach'), findsOneWidget);
          await tester.tap(find.text('Beach'));
          await tester.pumpAndSettle();
          expect(find.byKey(ValueKey('files_file_card_${prepared.fileId}')),
              findsOneWidget);
          expect(folderQueries,
              withOlderFolder ? <String>['', 'path=Holiday'] : <String>['']);
        }, () => mock);
      } finally {
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pump();
        app.unlocked = false;
        app.dispose();
        ZkActiveMvk.clear();
        VaultCryptoRegistry.clear(reason: 'synthetic-folder-cleanup');
        setApiClientDeviceId('');
        await tester.binding.setSurfaceSize(null);
      }
    }, skip: !kEnableFileV2UiRead);
  }
}
