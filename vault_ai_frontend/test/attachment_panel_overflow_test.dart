

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/main.dart' show ChatAttachmentPanel;


Future<void> _pumpWithViewport(
  WidgetTester tester, {
  required Size viewport,
  required int rowCount,
  required bool isMobile,
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
        
        
        body: SafeArea(
          child: SizedBox(
            height: viewport.height,
            width: viewport.width,
            child: Column(
              children: [
                Expanded(
                  child: Container(color: const Color(0xFF1F1F1F)),
                ),
                ChatAttachmentPanel(
                  isMobile: isMobile,
                  count: rowCount,
                  itemBuilder: (context, index) => Container(
                    margin: const EdgeInsets.symmetric(vertical: 4),
                    padding: const EdgeInsets.all(10),
                    height: 60,
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.05),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text('file_$index.pdf'),
                  ),
                  onClear: () {},
                ),
                
                Container(
                  key: const ValueKey('mock-composer'),
                  height: 64,
                  color: const Color(0xFF2F2F2F),
                  child: const Center(child: Text('composer')),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('ChatAttachmentPanel — no overflow at scale', () {
    for (final scenario in [
      ('desktop wide', const Size(1440, 900), false, 50),
      ('laptop narrow', const Size(1024, 700), false, 30),
      ('mobile', const Size(390, 780), true, 25),
    ]) {
      final (label, viewport, isMobile, rowCount) = scenario;

      testWidgets('$label / $rowCount rows', (tester) async {
        await _pumpWithViewport(
          tester,
          viewport: viewport,
          rowCount: rowCount,
          isMobile: isMobile,
        );

        
        expect(tester.takeException(), isNull,
            reason: '$label: layout should not throw an overflow error');

        
        expect(find.byType(Scrollable), findsWidgets,
            reason: '$label: panel must contain a Scrollable');
        expect(find.byType(ListView), findsOneWidget,
            reason: '$label: panel must use ListView.builder, not an '
                    'unbounded Column');

        
        expect(
          find.text('$rowCount attachment(s) ready'),
          findsOneWidget,
          reason: '$label: counter footer must remain mounted',
        );
        expect(
          find.byTooltip('Clear attachments'),
          findsOneWidget,
          reason: '$label: Clear button must remain mounted',
        );

        
        expect(
          find.byKey(const ValueKey('mock-composer')),
          findsOneWidget,
          reason: '$label: composer must remain in the tree',
        );
      });
    }
  });

  group('ChatAttachmentPanel — height cap constants', () {
    test('desktop cap is taller than mobile cap', () {
      
      
      expect(
        ChatAttachmentPanel.maxHeightDesktop,
        greaterThan(ChatAttachmentPanel.maxHeightMobile),
      );
    });

    test('both caps are positive and finite', () {
      
      
      expect(ChatAttachmentPanel.maxHeightMobile, greaterThan(0));
      expect(ChatAttachmentPanel.maxHeightMobile.isFinite, isTrue);
      expect(ChatAttachmentPanel.maxHeightDesktop, greaterThan(0));
      expect(ChatAttachmentPanel.maxHeightDesktop.isFinite, isTrue);
    });
  });

  testWidgets('Single attachment still renders cleanly (regression for '
      'the small-N case)', (tester) async {
    
    
    await _pumpWithViewport(
      tester,
      viewport: const Size(390, 780),
      rowCount: 1,
      isMobile: true,
    );
    expect(tester.takeException(), isNull);
    expect(find.text('1 attachment(s) ready'), findsOneWidget);
    expect(find.text('file_0.pdf'), findsOneWidget);
  });
}
