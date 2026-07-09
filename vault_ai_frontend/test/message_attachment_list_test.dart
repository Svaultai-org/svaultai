

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/chat/chat_bubble.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


Future<void> _pumpMessageAttachmentList(
  WidgetTester tester, {
  required List<ChatAttachmentSummary> attachments,
  required Size viewport,
  bool isMobile = false,
  bool onAccent = true,
}) async {
  tester.view.physicalSize = viewport;
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });

  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        backgroundColor: const Color(0xFF10A37F),
        body: SafeArea(
          child: SizedBox(
            width: viewport.width,
            height: viewport.height,
            
            
            child: Center(
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: viewport.width * (isMobile ? 0.86 : 0.62),
                ),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  color: const Color(0xFF10A37F),
                  child: MessageAttachmentList(
                    attachments: attachments,
                    isMobile: isMobile,
                    onAccent: onAccent,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


String _readLib(String relative) {
  final file = File('lib/$relative');
  expect(file.existsSync(), isTrue,
      reason: 'expected file does not exist: ${file.path}');
  return file.readAsStringSync();
}


void main() {
  group('Header copy', () {
    testWidgets('single attachment shows the file but NO "Uploaded N '
        'files" header', (tester) async {
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(900, 600),
        attachments: const [
          ChatAttachmentSummary(name: 'invoice.pdf', kind: 'file'),
        ],
      );
      expect(find.text('invoice.pdf'), findsOneWidget);
      
      expect(find.textContaining('Uploaded'), findsNothing);
    });

    testWidgets('two attachments show "Uploaded 2 files" header',
        (tester) async {
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(900, 600),
        attachments: const [
          ChatAttachmentSummary(name: 'a.pdf', kind: 'file'),
          ChatAttachmentSummary(name: 'b.pdf', kind: 'file'),
        ],
      );
      expect(find.text('Uploaded 2 files'), findsOneWidget);
      expect(find.text('a.pdf'), findsOneWidget);
      expect(find.text('b.pdf'), findsOneWidget);
    });

    testWidgets('three attachments — the user-reported scenario — '
        'render cleanly with no raw "[file]" tokens', (tester) async {
      const files = [
        'Payment scratch card.pdf',
        'Sample Pitch Deck for Startups.pdf',
        'RECENT ACCOUNT OPENING FORM BANKEDIT.pdf',
      ];
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(1440, 900),
        attachments: files
            .map((n) => ChatAttachmentSummary(name: n, kind: 'file'))
            .toList(),
      );
      expect(find.text('Uploaded 3 files'), findsOneWidget);
      for (final n in files) {
        expect(find.text(n), findsOneWidget,
            reason: 'each filename must render as its own row');
      }
      
      expect(find.textContaining('[file]'), findsNothing);
      expect(find.textContaining('[Attachments'), findsNothing);
    });
  });

  group('Icon mapping', () {
    testWidgets('PDF mime / .pdf name -> picture_as_pdf', (tester) async {
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(900, 600),
        attachments: const [
          ChatAttachmentSummary(
            name: 'doc.pdf',
            kind: 'file',
            mimeType: 'application/pdf',
          ),
        ],
      );
      expect(find.byIcon(Icons.picture_as_pdf), findsOneWidget);
    });

    testWidgets('image/* -> image icon', (tester) async {
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(900, 600),
        attachments: const [
          ChatAttachmentSummary(
            name: 'shot.jpg',
            kind: 'image',
            mimeType: 'image/jpeg',
          ),
        ],
      );
      expect(find.byIcon(Icons.image), findsOneWidget);
    });

    testWidgets('video/* -> videocam_outlined icon', (tester) async {
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(900, 600),
        attachments: const [
          ChatAttachmentSummary(
            name: 'clip.mp4',
            kind: 'video',
            mimeType: 'video/mp4',
          ),
        ],
      );
      expect(find.byIcon(Icons.videocam_outlined), findsOneWidget);
    });

    testWidgets('audio/* -> audiotrack icon', (tester) async {
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(900, 600),
        attachments: const [
          ChatAttachmentSummary(
            name: 'memo.m4a',
            kind: 'audio',
            mimeType: 'audio/mp4',
          ),
        ],
      );
      expect(find.byIcon(Icons.audiotrack), findsOneWidget);
    });

    testWidgets('unknown mime / kind -> generic insert_drive_file',
        (tester) async {
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(900, 600),
        attachments: const [
          ChatAttachmentSummary(name: 'thing.bin', kind: 'file'),
        ],
      );
      expect(find.byIcon(Icons.insert_drive_file), findsOneWidget);
    });
  });

  group('Overflow safety + Phase 5 folder summary card', () {
    testWidgets('20 attachments collapse to a folder-summary card '
        '(N >= folderSummaryThreshold)', (tester) async {
      final many = List.generate(
        20,
        (i) => ChatAttachmentSummary(
          name: 'file_${i.toString().padLeft(2, '0')}.pdf',
          kind: 'file',
          mimeType: 'application/pdf',
          size: 1024 * 500,
        ),
      );
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(1024, 700),
        attachments: many,
      );
      
      expect(tester.takeException(), isNull,
          reason: 'attachment list must not overflow with 20 files');
      
      
      expect(
        find.byType(ListView),
        findsNothing,
        reason:
            'folder summary must NOT use a per-file ListView at N>=threshold',
      );
      
      expect(find.byIcon(Icons.folder_copy_outlined), findsOneWidget);
      
      expect(find.textContaining('20 files'), findsWidgets);
    });

    testWidgets(
        '23,000 attachments still renders cleanly — folder summary, '
        'no per-file rows, no overflow',
        (tester) async {
      
      
      final many = List.generate(
        23000,
        (i) => ChatAttachmentSummary(
          name: 'big_folder/file_$i.pdf',
          kind: 'file',
          mimeType: 'application/pdf',
          size: 4 * 1024,
        ),
      );
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(360, 740),
        isMobile: true,
        attachments: many,
      );
      expect(tester.takeException(), isNull,
          reason: '23k-file folder must not overflow on mobile');
      expect(
        find.byType(ListView),
        findsNothing,
        reason: '23k attachments must not render 23k rows',
      );
      expect(find.byIcon(Icons.folder_copy_outlined), findsOneWidget);
      
      expect(find.text('big_folder'), findsOneWidget);
      
      expect(find.textContaining('more'), findsOneWidget);
    });

    testWidgets('threshold-1 attachments still render per-file rows',
        (tester) async {
      
      
      final five = List.generate(
        MessageAttachmentList.folderSummaryThreshold - 1,
        (i) => ChatAttachmentSummary(
          name: 'small_$i.pdf',
          kind: 'file',
          mimeType: 'application/pdf',
        ),
      );
      await _pumpMessageAttachmentList(
        tester,
        viewport: const Size(900, 600),
        attachments: five,
      );
      expect(tester.takeException(), isNull);
      
      expect(find.byType(ListView), findsOneWidget);
      
      expect(find.byIcon(Icons.folder_copy_outlined), findsNothing);
    });
  });

  group('Cap constants', () {
    test('desktop cap > mobile cap, both finite and positive', () {
      expect(
        MessageAttachmentList.maxHeightDesktop,
        greaterThan(MessageAttachmentList.maxHeightMobile),
      );
      expect(MessageAttachmentList.maxHeightDesktop, greaterThan(0));
      expect(MessageAttachmentList.maxHeightMobile, greaterThan(0));
      expect(MessageAttachmentList.maxHeightDesktop.isFinite, isTrue);
      expect(MessageAttachmentList.maxHeightMobile.isFinite, isTrue);
    });
  });

  group('main.dart no longer stringifies attachments into the bubble',
      () {
    test('source no longer builds the "[Attachments: …]" suffix', () {
      
      
      final src = _readLib('main.dart');
      expect(
        src.contains("'[Attachments: \$attachmentLabel]'"),
        isFalse,
        reason: 'the raw bracketed suffix must not be reintroduced',
      );
      expect(
        src.contains(r"'\$text\n\n[Attachments: \$attachmentLabel]'"),
        isFalse,
        reason: 'the raw bracketed suffix must not be reintroduced',
      );
      expect(
        src.contains(r"'[\${a.kind}] \${a.name}'"),
        isFalse,
        reason: 'the per-attachment "[kind] name" prefix must not be '
                'reintroduced',
      );
    });

    test('source constructs ChatAttachmentSummary list instead', () {
      
      final src = _readLib('main.dart');
      expect(
        src,
        contains('ChatAttachmentSummary('),
        reason: 'main.dart must build the structured summary list the '
                'bubble renderer consumes',
      );
    });
  });
}
