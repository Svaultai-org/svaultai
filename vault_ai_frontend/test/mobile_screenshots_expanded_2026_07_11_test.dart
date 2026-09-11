import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/delete_vault_flow.dart';
import 'package:vault_ai_frontend/device_pending_page.dart';
import 'package:vault_ai_frontend/help_center_page.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/logins_page.dart';
import 'package:vault_ai_frontend/services/content_hash.dart';
import 'package:vault_ai_frontend/ui/chat/duplicate_dialog.dart';
import 'package:vault_ai_frontend/ui/chat/storage_limit_dialog.dart';
import 'package:vault_ai_frontend/ui/crypto_receive_panel.dart';
import 'package:vault_ai_frontend/ui/secure_item_detail.dart';

import '_helpers/responsive_harness.dart';

final List<DeviceProfile> _extraDevices = const [
  DeviceProfiles.ipad,
  DeviceProfiles.desktop,
  DeviceProfiles.iphoneSELandscape,
  DeviceProfiles.iphone12Landscape,
];

Future<void> _captureGolden(
  WidgetTester tester,
  Widget widget,
  String name,
  DeviceProfile device, {
  double keyboardHeight = 0,
}) async {
  // Some production pages own periodic polling timers. Explicitly unmount the
  // page after capture so those timers are deterministically disposed even
  // when a golden comparison fails.
  addTearDown(() async {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump();
  });
  await pumpAtDevice(tester, widget,
      device: device, keyboardHeight: keyboardHeight);
  await expectLater(
    find.byType(MaterialApp),
    matchesGoldenFile(goldenPath(name, device)),
  );
}

Future<void> _openDialogAndCapture(
  WidgetTester tester,
  Widget dialog,
  String name,
  DeviceProfile device, {
  double keyboardHeight = 0,
}) async {
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
        builder: (ctx) => MediaQuery(
          data: MediaQueryData(
            size: device.logicalSize,
            devicePixelRatio: device.devicePixelRatio,
            padding: device.safeAreaInsets,
            viewInsets: keyboardHeight > 0
                ? EdgeInsets.only(bottom: keyboardHeight)
                : EdgeInsets.zero,
          ),
          child: Scaffold(
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
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
  await expectLater(
    find.byType(MaterialApp),
    matchesGoldenFile(goldenPath(name, device)),
  );
}

Future<void> _openBottomSheetAndCapture(
  WidgetTester tester,
  Widget sheet,
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
        builder: (ctx) => MediaQuery(
          data: MediaQueryData(
            size: device.logicalSize,
            devicePixelRatio: device.devicePixelRatio,
            padding: device.safeAreaInsets,
          ),
          child: Scaffold(
            backgroundColor: const Color(0xFF1B1B1B),
            body: Center(
              child: ElevatedButton(
                onPressed: () => showModalBottomSheet<void>(
                  context: ctx,
                  builder: (_) => sheet,
                  backgroundColor: Colors.transparent,
                ),
                child: const Text('open'),
              ),
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
  for (final device in _extraDevices) {
    group(
        'Extra viewport goldens @ ${device.name} '
        '(${device.width.toInt()}x${device.height.toInt()})', () {
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
            ],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          ),
          'logins_mixed',
          device,
        );
      });

      testWidgets('logins_loading', (t) async {
        await pumpAtDevice(
          t,
          LoginsPage(
            isLoading: true,
            hasLoaded: false,
            logins: const <VaultLoginItem>[],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          ),
          device: device,
          settle: false,
        );
        await expectLater(
          find.byType(MaterialApp),
          matchesGoldenFile(goldenPath('logins_loading', device)),
        );
      });

      testWidgets('logins_error', (t) async {
        await _captureGolden(
          t,
          LoginsPage(
            isLoading: false,
            hasLoaded: true,
            error: 'Could not load your logins. Check your connection.',
            logins: const <VaultLoginItem>[],
            vaultLabel: 'MyVault',
            onRefresh: () async {},
          ),
          'logins_error',
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

      testWidgets('duplicate_upload_dialog', (t) async {
        await _openDialogAndCapture(
          t,
          DuplicateUploadDialog(
            detail: const DuplicateFoundDetail(
              existingFileId: 'x',
              incomingFileName: 'photo.png',
              incomingSize: 123,
              message: 'exists',
              existingFileName: 'photo.png',
              existingSavedName: 'photo.png',
              existingRelativePath: '/Photos/2024',
            ),
          ),
          'duplicate_upload_dialog',
          device,
        );
      });

      testWidgets('storage_limit_dialog', (t) async {
        await _openDialogAndCapture(
          t,
          const NotEnoughStorageDialog(
            plannedBytes: 5000000000,
            availableBytes: 1000000000,
            folderName: 'A quite long folder name',
          ),
          'storage_limit_dialog',
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

  // Bottom-sheet golden: SecureItemDetailSheet on all phones.
  for (final device in DeviceProfiles.allPhones) {
    testWidgets('BottomSheet: secure_item_detail_sheet_login @ ${device.name}',
        (t) async {
      await _openBottomSheetAndCapture(
        t,
        const SecureItemDetailSheet(
          title: 'American First Credit Union',
          itemType: 'login',
          username: 'user@example.com',
        ),
        'secure_item_detail_sheet_login',
        device,
      );
    });
  }

  // Keyboard-open golden: DeleteVaultFlow with a keyboard on iPhone SE + 12
  for (final device in const [
    DeviceProfiles.iphoneSE,
    DeviceProfiles.iphone12,
  ]) {
    testWidgets('KeyboardOpen: delete_vault_dialog @ ${device.name}',
        (t) async {
      await _openDialogAndCapture(
        t,
        const DeleteVaultFlow(
          client: VaultAIClient(baseUrl: 'https://example.test'),
          authToken: 'test-token',
        ),
        'delete_vault_dialog_keyboard',
        device,
        keyboardHeight: 336,
      );
    });
  }

  // Device-pending page across viewports — proves the countdown metric scales.
  for (final device in const [
    DeviceProfiles.iphoneSE,
    DeviceProfiles.iphone12,
    DeviceProfiles.iphone14ProMax,
  ]) {
    testWidgets('DevicePendingPage @ ${device.name}', (t) async {
      await _captureGolden(
        t,
        const DevicePendingPage(status: 'pending'),
        'device_pending_page',
        device,
      );
    });
  }
}
