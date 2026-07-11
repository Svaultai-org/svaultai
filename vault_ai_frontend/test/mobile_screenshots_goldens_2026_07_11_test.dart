
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/delete_vault_flow.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';

import 'package:vault_ai_frontend/services/content_hash.dart';
import 'package:vault_ai_frontend/ui/chat/duplicate_dialog.dart';
import 'package:vault_ai_frontend/ui/chat/storage_limit_dialog.dart';
import 'package:vault_ai_frontend/ui/crypto_receive_panel.dart';

import '_helpers/responsive_harness.dart';




final List<DeviceProfile> _screenshotDevices = const [
  DeviceProfiles.iphoneSE,
  DeviceProfiles.iphone12,
  DeviceProfiles.iphone14ProMax,
];


Future<void> _captureGolden(
  WidgetTester tester,
  Widget widget,
  String name,
  DeviceProfile device,
) async {
  await pumpAtDevice(tester, widget, device: device);
  await expectLater(
    find.byType(MaterialApp),
    matchesGoldenFile(goldenPath(name, device)),
  );
}


Future<void> _openDialogAndCapture(
  WidgetTester tester,
  Widget dialog,
  String name,
  DeviceProfile device,
) async {
  await tester.binding.setSurfaceSize(device.logicalSize);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Builder(
        builder: (ctx) => Scaffold(
          backgroundColor: const Color(0xFF1B1B1B),
          body: Center(
            child: ElevatedButton(
              onPressed: () => showDialog<void>(
                context: ctx,
                builder: (_) => dialog,
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  await expectLater(
    find.byType(MaterialApp),
    matchesGoldenFile(goldenPath(name, device)),
  );
}

void main() {
  for (final device in _screenshotDevices) {
    group('Screenshots @ ${device.name} (${device.width.toInt()}dp)', () {
      testWidgets('logins_empty', (t) async {
        await _captureGolden(
          t,
          LoginsPage(
            isLoading: false,
            hasLoaded: true,
            logins: const <VaultLoginItem>[],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          ),
          'logins_empty',
          device,
        );
      });

      testWidgets('logins_mixed', (t) async {
        await _captureGolden(
          t,
          LoginsPage(
            isLoading: false,
            hasLoaded: true,
            logins: const [
              VaultLoginItem(service: 'Netflix', itemType: 'login'),
              VaultLoginItem(
                service: 'American First Credit Union Portal',
                itemType: 'login',
              ),
              VaultLoginItem(
                service: 'Passport (2028)',
                itemType: 'id_document',
              ),
              VaultLoginItem(
                service: 'Bank of America Card',
                itemType: 'card',
              ),
              VaultLoginItem(
                service: 'Ledger seed phrase',
                itemType: 'crypto',
              ),
            ],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          ),
          'logins_mixed',
          device,
        );
      });

      testWidgets('help_center_public', (t) async {
        await _captureGolden(
          t,
          const HelpCenterPage(mode: HelpCenterMode.public),
          'help_center_public',
          device,
        );
      });

      testWidgets('storage_limit_dialog', (t) async {
        await _openDialogAndCapture(
          t,
          const NotEnoughStorageDialog(
            plannedBytes: 5000000000,
            availableBytes: 1000000000,
            folderName: 'My Photos From The Trip To Iceland',
          ),
          'storage_limit_dialog',
          device,
        );
      });

      testWidgets('duplicate_upload_dialog', (t) async {
        await _openDialogAndCapture(
          t,
          DuplicateUploadDialog(
            detail: const DuplicateFoundDetail(
              existingFileId: 'abc',
              incomingFileName: 'family-photo.png',
              incomingSize: 2400000,
              message: 'File already exists',
              existingFileName: 'family-photo.png',
              existingSavedName: 'family-photo.png',
              existingRelativePath: '/Photos/2024/Winter',
            ),
          ),
          'duplicate_upload_dialog',
          device,
        );
      });

      testWidgets('name_conflict_dialog', (t) async {
        await _openDialogAndCapture(
          t,
          NameConflictDialog(
            detail: const NameConflictDetail(
              existingFileId: 'abc',
              incomingFileName: 'passport.pdf',
              incomingSize: 400000,
              message: 'Name conflict',
              existingFileName: 'passport.pdf',
              existingSavedName: 'passport.pdf',
              existingRelativePath: '/Documents',
              proposedVersionedName: 'passport_v2.pdf',
            ),
          ),
          'name_conflict_dialog',
          device,
        );
      });

      testWidgets('delete_vault_dialog', (t) async {
        await _openDialogAndCapture(
          t,
          const DeleteVaultFlow(
            client: VaultAIClient(baseUrl: 'https://example.test'),
            authToken: 'test-token',
          ),
          'delete_vault_dialog',
          device,
        );
      });

      testWidgets('crypto_receive_panel', (t) async {
        await _captureGolden(
          t,
          SingleChildScrollView(
            child: Container(
              color: const Color(0xFF1B1B1B),
              padding: const EdgeInsets.all(16),
              child: const ReceivePanel(
                title: 'Receive Bitcoin (BTC)',
                address: 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh',
                network: 'Bitcoin Mainnet',
              ),
            ),
          ),
          'crypto_receive_panel',
          device,
        );
      });
    });
  }
}
