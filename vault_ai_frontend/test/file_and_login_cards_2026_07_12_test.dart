import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

import '_helpers/responsive_harness.dart';


Widget _wrap(Widget child) => MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Scaffold(body: child),
    );


ChatMessage _fileMsg({
  String id = 'file-123',
  String name = 'holiday-video.mp4',
  String mime = 'video/mp4',
  int? sizeBytes,
}) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kVaultFile,
    fileId: id,
    fileName: name,
    mimeType: mime,
    payload: {
      if (sizeBytes != null) 'size_bytes': sizeBytes,
    },
  );
}


void main() {
  group('Bug: View action loading + double-tap protection', () {
    testWidgets('first tap shows spinner and disables View button',
        (t) async {
      var viewTaps = 0;
      await t.pumpWidget(_wrap(VaultFileCard(
        msg: _fileMsg(),
        onOpen: () => viewTaps++,
        onDownload: () {},
        isViewInFlight: false,
        isDownloadInFlight: false,
      )));
      final btn = find.byKey(const Key('vault_file_card_view_btn'));
      expect(btn, findsOneWidget);

      await t.tap(btn);
      expect(viewTaps, 1);

      // Simulate parent flipping isViewInFlight -> true
      await t.pumpWidget(_wrap(VaultFileCard(
        msg: _fileMsg(),
        onOpen: () => viewTaps++,
        onDownload: () {},
        isViewInFlight: true,
        isDownloadInFlight: false,
      )));
      await t.pump();

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Opening…'), findsOneWidget);

      // Additional taps while in-flight are ignored (button is disabled).
      final btn2 = find.byKey(const Key('vault_file_card_view_btn'));
      final button2 = t.widget<FilledButton>(btn2);
      expect(button2.onPressed, isNull);
    });

    testWidgets('rapid ten taps register only one tap because parent '
        'is expected to flip in-flight immediately',
        (t) async {
      var viewTaps = 0;
      bool inFlight = false;
      Future<void> pumpCard() async {
        await t.pumpWidget(_wrap(VaultFileCard(
          msg: _fileMsg(),
          onOpen: () {
            if (inFlight) return;
            inFlight = true;
            viewTaps++;
          },
          onDownload: () {},
          isViewInFlight: inFlight,
          isDownloadInFlight: false,
        )));
      }

      await pumpCard();
      for (var i = 0; i < 10; i++) {
        await t.tap(
          find.byKey(const Key('vault_file_card_view_btn')),
          warnIfMissed: false,
        );
        await pumpCard();
      }
      expect(viewTaps, 1,
          reason: 'in-flight guard must collapse repeated taps to '
              'exactly one fetch');
    });

    testWidgets('one file loading does not disable unrelated cards',
        (t) async {
      var t1Taps = 0;
      var t2Taps = 0;
      await t.pumpWidget(_wrap(Column(children: [
        VaultFileCard(
          key: const Key('card-a'),
          msg: _fileMsg(id: 'file-a', name: 'a.pdf'),
          onOpen: () => t1Taps++,
          onDownload: () {},
          isViewInFlight: true,
          isDownloadInFlight: false,
        ),
        VaultFileCard(
          key: const Key('card-b'),
          msg: _fileMsg(id: 'file-b', name: 'b.pdf'),
          onOpen: () => t2Taps++,
          onDownload: () {},
          isViewInFlight: false,
          isDownloadInFlight: false,
        ),
      ])));

      // The View button on card A is disabled; on card B still enabled.
      final btnA = find.descendant(
        of: find.byKey(const Key('card-a')),
        matching: find.byKey(const Key('vault_file_card_view_btn')),
      );
      final btnB = find.descendant(
        of: find.byKey(const Key('card-b')),
        matching: find.byKey(const Key('vault_file_card_view_btn')),
      );
      expect(t.widget<FilledButton>(btnA).onPressed, isNull);
      expect(t.widget<FilledButton>(btnB).onPressed, isNotNull);

      await t.tap(btnB);
      expect(t1Taps, 0);
      expect(t2Taps, 1);
    });
  });


  group('Bug: Download does NOT call View', () {
    testWidgets('Download button uses distinct callback',
        (t) async {
      var viewTaps = 0;
      var downloadTaps = 0;
      await t.pumpWidget(_wrap(VaultFileCard(
        msg: _fileMsg(),
        onOpen: () => viewTaps++,
        onDownload: () => downloadTaps++,
      )));

      await t.tap(find.byKey(const Key('vault_file_card_download_btn')));
      expect(downloadTaps, 1,
          reason: 'Download tap must invoke onDownload, not onOpen');
      expect(viewTaps, 0,
          reason: 'Download must NOT open the media viewer');
    });

    testWidgets('Download button shows Downloading… + spinner while '
        'isDownloadInFlight', (t) async {
      await t.pumpWidget(_wrap(VaultFileCard(
        msg: _fileMsg(),
        onOpen: () {},
        onDownload: () {},
        isDownloadInFlight: true,
      )));
      expect(find.text('Downloading…'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      final btn = find.byKey(const Key('vault_file_card_download_btn'));
      expect(t.widget<OutlinedButton>(btn).onPressed, isNull);
    });

    testWidgets('Rapid Download taps register only once',
        (t) async {
      var downloadTaps = 0;
      bool inFlight = false;
      Future<void> pumpCard() async {
        await t.pumpWidget(_wrap(VaultFileCard(
          msg: _fileMsg(),
          onOpen: () {},
          onDownload: () {
            if (inFlight) return;
            inFlight = true;
            downloadTaps++;
          },
          isDownloadInFlight: inFlight,
        )));
      }

      await pumpCard();
      for (var i = 0; i < 10; i++) {
        await t.tap(
          find.byKey(const Key('vault_file_card_download_btn')),
          warnIfMissed: false,
        );
        await pumpCard();
      }
      expect(downloadTaps, 1);
    });
  });


  group('Bug: file-list rows have distinct View and Download', () {
    testWidgets('_VaultFileListRow renders View + Download icons + '
        'human-readable size', (t) async {
      var viewedId = '';
      var downloadedId = '';

      final msg = ChatMessage(
        'assistant',
        '',
        kind: ChatMessage.kVaultFileList,
        payload: {
          'title': 'All 2 files in your vault',
          'files': [
            {
              'file_id': 'f1',
              'file_name': 'invoice-january.pdf',
              'mime_type': 'application/pdf',
              'size_bytes': 250000,
              'size_display': '244.1 KB',
              'downloadable': true,
            },
            {
              'file_id': 'f2',
              'file_name': 'holiday.mp4',
              'mime_type': 'video/mp4',
              'size_bytes': 47600000,
              'size_display': '45.4 MB',
              'downloadable': true,
            },
          ],
        },
      );

      await t.pumpWidget(_wrap(VaultFileListCard(
        msg: msg,
        onOpen: (fm) => viewedId = fm.fileId ?? '',
        onDownload: (fm) => downloadedId = fm.fileId ?? '',
      )));
      await t.pumpAndSettle();

      // Human-readable size present.
      expect(find.textContaining('244.1 KB'), findsOneWidget);
      expect(find.textContaining('45.4 MB'), findsOneWidget);

      // Distinct handlers.
      await t.tap(find.byKey(const Key('vault_file_list_row_view_f1')));
      expect(viewedId, 'f1');
      await t.tap(
        find.byKey(const Key('vault_file_list_row_download_f2')),
      );
      expect(downloadedId, 'f2');
    });
  });


  group('Bug: mobile rendering at 320/390/430', () {
    for (final device in const [
      DeviceProfiles.iphoneSE,
      DeviceProfiles.iphone12,
      DeviceProfiles.iphone14ProMax,
    ]) {
      testWidgets(
          'VaultFileCard fits ${device.name} without overflow',
          (t) async {
        await pumpAtDevice(
          t,
          _wrap(VaultFileCard(
            msg: _fileMsg(
              name: 'very-long-filename-that-should-ellipsize-'
                  'or-wrap-cleanly.pdf',
              sizeBytes: 4263030,
            ),
            onOpen: () {},
            onDownload: () {},
          )),
          device: device,
        );
        expectNoOverflow(t, context: device.name);
      });

      testWidgets(
          'VaultFileListCard fits ${device.name} without overflow',
          (t) async {
        final msg = ChatMessage(
          'assistant',
          '',
          kind: ChatMessage.kVaultFileList,
          payload: {
            'title': 'All 3 files in your vault',
            'files': [
              {
                'file_id': 'x1',
                'file_name': 'a-really-really-long-name-'
                    'to-test-mobile-wrapping.pdf',
                'mime_type': 'application/pdf',
                'size_bytes': 4263030,
                'size_display': '4.1 MB',
              },
              {
                'file_id': 'x2',
                'file_name': 'clip.webm',
                'mime_type': 'video/webm',
                'size_bytes': 49869645,
                'size_display': '47.6 MB',
              },
            ],
          },
        );
        await pumpAtDevice(
          t,
          _wrap(VaultFileListCard(
            msg: msg,
            onOpen: (_) {},
            onDownload: (_) {},
          )),
          device: device,
        );
        expectNoOverflow(t, context: device.name);
      });
    }
  });
}
