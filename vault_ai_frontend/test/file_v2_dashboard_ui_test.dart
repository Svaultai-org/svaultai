import 'dart:convert';

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
import 'package:vault_ai_frontend/services/legacy_ciphertext_migration_codec.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart';
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';

class _App extends AppState {
  @override
  Future<void> refreshVaultStats() async {}
}

void main() {
  testWidgets(
    'Files shows retired V2 copy from encrypted inventory without legacy PIN list',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(430, 932));
      final app = _App()
        ..sessionToken = 'synthetic-v2-session'
        ..vaultId = 'synthetic-v2-vault'
        ..vaultName = 'Synthetic vault'
        ..vaultHandle = 'synthetic-v2-handle'
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
          source: 'synthetic-v2-ui-fixture',
        );
      } finally {
        debugDefaultTargetPlatformOverride = oldPlatform;
      }
      final mvk = SecretKey(List<int>.filled(32, 81));
      ZkActiveMvk.set(
        mvk: mvk,
        vaultId: app.vaultId!,
        vaultHandle: app.vaultHandle!,
      );
      st.SessionTermination.instance.bindSession(app.sessionToken!);
      app.unlocked = true;
      setApiClientDeviceId('synthetic-v2-device');
      final metadataKey = await VaultKeyHierarchy(mvk).metadataKey();
      final nameCt = b64urlEncode(
        await aesGcmWrap(metadataKey, utf8.encode('synthetic-v2-note.txt')),
      );
      final legacyKey = SecretKey(List<int>.filled(32, 83));
      final fileBytes = utf8.encode('synthetic private note');
      final oldBox = await AesGcm.with256bits().encrypt(
        fileBytes,
        secretKey: legacyKey,
        nonce: List<int>.generate(12, (i) => i + 1),
      );
      final oldCt = base64.encode(<int>[
        ...oldBox.nonce,
        ...oldBox.cipherText,
        ...oldBox.mac.bytes,
      ]);
      final v2 = await LegacyCiphertextMigrationCodec(
        legacyKey: legacyKey,
        mvk: mvk,
      ).stageFile(
        fileId: 'synthetic-v2-file',
        legacyCiphertext: oldCt,
        declaredFileSize: fileBytes.length,
        contentType: 'text/plain',
        encryptedMetadata: <String, String?>{
          'file_name_ciphertext': nameCt,
        },
      );
      final paths = <String>[];
      final mock = MockClient((request) async {
        expect(request.url.host, '127.0.0.1');
        expect(request.url.port, 1);
        paths.add('${request.method} ${request.url.path}');
        if (request.url.path == '/vault/files/metadata') {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'records': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'file_id': v2.fileId,
                    'file_size': fileBytes.length,
                    'file_name_ciphertext': nameCt,
                    'lifecycle_state': 'legacy_migration_retired',
                    'verification_state': 'client_verified',
                  },
                ],
                'has_more': false,
                'next_after_file_id': v2.fileId,
              }),
              200);
        }
        if (request.url.path == '/vault/file-v2') {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'files': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'file_id': v2.fileId,
                    'lifecycle_state': 'legacy_migration_retired',
                    'verification_state': 'client_verified',
                  },
                ],
              }),
              200);
        }
        if (request.url.path.endsWith('/manifest')) {
          return http.Response(
              jsonEncode(<String, dynamic>{
                ...v2.toManifestBody(),
                'lifecycle_state': 'legacy_migration_retired',
                'verification_state': 'client_verified',
              }),
              200);
        }
        if (request.url.path.contains('/chunk/')) {
          final index = int.parse(request.url.path.split('/').last);
          return http.Response(
              jsonEncode(<String, dynamic>{
                'file_id': v2.fileId,
                'chunk_index': index,
                'ciphertext': v2.chunkCiphertexts[index],
              }),
              200);
        }
        if (request.url.path == '/folders') {
          return http.Response(
              jsonEncode(<String, dynamic>{
                'path': '',
                'folders': <Object>[],
                'files': <Map<String, dynamic>>[
                  <String, dynamic>{
                    'id': v2.fileId,
                    'file_size': fileBytes.length,
                    'file_name_ciphertext': nameCt,
                  },
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
        fail('Unexpected request: ${request.method} ${request.url.path}');
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
          expect(find.text('synthetic-v2-note.txt'), findsWidgets);
          final rename = tester.widget<IconButton>(
            find.byKey(const ValueKey('files_file_rename_synthetic-v2-file')),
          );
          expect(rename.onPressed, isNull);
          await tester.tap(find.byKey(
            const ValueKey('files_file_ask_synthetic-v2-file'),
          ));
          await tester.pumpAndSettle();
          await tester.tap(find.byKey(const Key('vault_file_card_view_btn')));
          await tester.pump(const Duration(milliseconds: 250));
          expect(find.text('synthetic private note'), findsWidgets);
          await tester.tap(find.byKey(const Key('text_viewer_dialog_close')));
          await tester.pumpAndSettle();
          await tester
              .tap(find.byKey(const Key('vault_file_card_download_btn')));
          await tester.pumpAndSettle();
          expect(
              paths
                  .where((path) =>
                      path == 'GET /vault/file-v2/synthetic-v2-file/chunk/0')
                  .length,
              2);
          expect(paths, contains('GET /vault/files/metadata'));
          expect(paths, isNot(contains('POST /list-files')));
          expect(paths, isNot(contains('POST /download-file')));
        }, () => mock);
      } finally {
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pump();
        app.unlocked = false;
        app.dispose();
        ZkActiveMvk.clear();
        VaultCryptoRegistry.clear(reason: 'synthetic-v2-ui-cleanup');
        setApiClientDeviceId('');
        await tester.binding.setSurfaceSize(null);
      }
    },
    skip: !kEnableFileV2UiRead,
  );
}
