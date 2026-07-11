
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/delete_vault_flow.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';

import 'package:vault_ai_frontend/services/content_hash.dart';
import 'package:vault_ai_frontend/ui/chat/duplicate_dialog.dart';
import 'package:vault_ai_frontend/ui/chat/storage_limit_dialog.dart';
import 'package:vault_ai_frontend/ui/crypto_receive_panel.dart';

import '_helpers/responsive_harness.dart';




Future<void> _openDialog(
  WidgetTester tester,
  Widget dialogChild, {
  required DeviceProfile device,
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
        builder: (ctx) => Scaffold(
          body: Center(
            child: ElevatedButton(
              onPressed: () {
                showDialog<void>(
                  context: ctx,
                  builder: (_) => dialogChild,
                );
              },
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ),
  );

  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
}


void _forEachPhone(
  String description,
  Future<void> Function(WidgetTester tester, DeviceProfile device) body,
) {
  for (final d in DeviceProfiles.allPhones) {
    testWidgets('$description @ ${d.name}', (tester) async {
      await body(tester, d);
      expectNoOverflow(tester, context: d.name);
      final surface = tester.getSize(find.byType(MaterialApp));
      final dialogs = find.byType(Dialog);
      if (dialogs.evaluate().isNotEmpty) {
        for (final el in dialogs.evaluate()) {
          final box = el.renderObject as RenderBox?;
          if (box != null && box.hasSize) {
            expect(
              box.size.width,
              lessThanOrEqualTo(surface.width),
              reason:
                  'Dialog width ${box.size.width} > screen ${surface.width} on ${d.name}',
            );
          }
        }
      }
      final alertDialogs = find.byType(AlertDialog);
      if (alertDialogs.evaluate().isNotEmpty) {
        for (final el in alertDialogs.evaluate()) {
          final box = el.renderObject as RenderBox?;
          if (box != null && box.hasSize) {
            expect(
              box.size.width,
              lessThanOrEqualTo(surface.width),
              reason:
                  'AlertDialog width ${box.size.width} > screen ${surface.width} on ${d.name}',
            );
          }
        }
      }
    });
  }
}


void main() {


  group('NotEnoughStorageDialog', () {
    _forEachPhone('renders within screen width', (tester, device) async {
      await _openDialog(
        tester,
        const NotEnoughStorageDialog(
          plannedBytes: 5000000000,
          availableBytes: 1000000000,
          folderName: 'A really long folder name that could overflow small screens with wrapping',
        ),
        device: device,
      );
    });
  });


  group('DuplicateUploadDialog', () {
    _forEachPhone('renders within screen width', (tester, device) async {
      await _openDialog(
        tester,
        DuplicateUploadDialog(
          detail: const DuplicateFoundDetail(
            existingFileId: 'abc123',
            incomingFileName: 'incoming_very_long_filename_that_might_overflow_narrow_screens.pdf',
            incomingSize: 12345,
            message: 'This file already exists.',
            existingFileName: 'existing.pdf',
            existingSavedName: 'existing_super_long_saved_name.pdf',
            existingRelativePath: '/some/deeply/nested/folder/path/existing.pdf',
          ),
        ),
        device: device,
      );
    });
  });


  group('NameConflictDialog', () {
    _forEachPhone('renders within screen width', (tester, device) async {
      await _openDialog(
        tester,
        NameConflictDialog(
          detail: const NameConflictDetail(
            existingFileId: 'abc123',
            incomingFileName: 'file.pdf',
            incomingSize: 12345,
            message: 'A file with this name already exists.',
            existingFileName: 'file.pdf',
            existingSavedName: 'file_saved.pdf',
            existingRelativePath: '/very/deep/nesting/that/could/overflow/file.pdf',
            proposedVersionedName: 'file_v2_2026_07_11_a_long_versioned_name.pdf',
          ),
        ),
        device: device,
      );
    });
  });


  group('DeleteVaultFlow', () {
    _forEachPhone('renders within screen width', (tester, device) async {
      await _openDialog(
        tester,
        const DeleteVaultFlow(
          client: VaultAIClient(baseUrl: 'https://example.test'),
          authToken: 'test-token',
        ),
        device: device,
      );
    });
  });


  group('CryptoReceivePanel', () {
    _forEachPhone('renders within screen width', (tester, device) async {
      await pumpAtDevice(
        tester,
        SingleChildScrollView(
          child: ReceivePanel(
            title: 'Receive Bitcoin (BTC) - Mainnet Address',
            address: 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh',
            network: 'Bitcoin Mainnet',
          ),
        ),
        device: device,
      );
    });
  });
}
