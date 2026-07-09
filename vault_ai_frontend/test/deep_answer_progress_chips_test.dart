

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _progressMsg({
  required Map<String, dynamic> coverage,
  String status = 'scanning',
  String? stageLabel,
  String? blockerReason,
  String text = "Let me check your vault properly. "
      "I'll read the files before giving the result.",
}) {
  return ChatMessage(
    'assistant', text,
    kind: ChatMessage.kDeepAnswerProgress,
    payload: <String, dynamic>{
      'job_id': 'job-1',
      'status': status,
      'progress': <String, dynamic>{
        'coverage':      coverage,
        'stage_label':   stageLabel,
        if (blockerReason != null) 'blocker_reason': blockerReason,
      },
    },
  );
}


Future<void> _pump(WidgetTester tester, ChatMessage msg) async {
  tester.view.physicalSize = const Size(900, 1200);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ],
      supportedLocales: AppLocalizations.supportedLocales,
      home: Scaffold(
        backgroundColor: const Color(0xFF0F1115),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: DeepAnswerProgressCard(
              msg: msg,
              pollInterval: const Duration(seconds: 60),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
}


void main() {
  group('DeepAnswerProgressCard — simple-UI normal-mode bubble', () {
    testWidgets('renders the natural assistant bubble while scanning',
        (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 0, 'pending': 425},
        ),
      );
      expect(
        find.textContaining('Let me check your vault properly'),
        findsOneWidget,
      );
      expect(
        find.textContaining("I'll read the files before giving the result"),
        findsOneWidget,
      );
    });

    testWidgets('does NOT render the big "Scanning your vault" card',
        (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 4, 'pending': 421},
        ),
      );
      expect(find.text('Scanning your vault'), findsNothing);
    });

    testWidgets('does NOT render the "0 of N checked" / "N to go" pills',
        (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 4, 'pending': 421},
        ),
      );
      expect(find.textContaining('of 425 checked'), findsNothing);
      expect(find.textContaining('to go'), findsNothing);
      expect(find.textContaining('files read'), findsNothing);
    });

    testWidgets('does NOT render any "Deep Answer Mode" / "live" copy',
        (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 4, 'pending': 421},
        ),
      );
      expect(find.textContaining('Deep Answer Mode'), findsNothing);
      expect(find.textContaining('live'), findsNothing);
      expect(find.textContaining('Reading files'), findsNothing);
      expect(find.textContaining('Preparing scan'), findsNothing);
    });

    testWidgets('does NOT render the chatty footer ("A slow accurate '
        'answer…")', (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 4, 'pending': 421},
        ),
      );
      expect(
        find.textContaining('A slow accurate answer'),
        findsNothing,
      );
      expect(
        find.textContaining("I won't return final results"),
        findsNothing,
      );
    });

    testWidgets('does NOT render any progress bar in normal mode',
        (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 4, 'pending': 421},
        ),
      );
      expect(find.byType(LinearProgressIndicator), findsNothing);
    });
  });

  group('DeepAnswerProgressCard — honest failure copy', () {
    testWidgets('blocker_reason from backend flips to the honest failure '
        'line', (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 0, 'pending': 425},
          blockerReason: 'queue_empty_but_coverage_pending',
        ),
      );
      expect(
        find.textContaining(
            "I couldn't finish checking the vault because file "
            'analysis is not moving'),
        findsOneWidget,
      );
      expect(
        find.textContaining(
            'Try running vault analysis or check the backend workers'),
        findsOneWidget,
      );
    });

    testWidgets('status=failed flips to the same honest failure line',
        (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {'total': 425, 'scanned': 0, 'pending': 425},
          status: 'failed',
        ),
      );
      expect(
        find.textContaining(
            "I couldn't finish checking the vault because file "
            'analysis is not moving'),
        findsOneWidget,
      );
    });

    testWidgets('status=ready with scanned=0 (backend lie) still surfaces '
        'the honest failure', (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {
            'total': 425, 'scanned': 0, 'pending': 425,
            'scan_complete': true,                 
          },
          status: 'ready',
        ),
      );
      expect(find.text('Scan complete'), findsNothing);
      expect(
        find.textContaining(
            "I couldn't finish checking the vault because file "
            'analysis is not moving'),
        findsOneWidget,
      );
    });
  });

  group('DeepAnswerProgressCard — terminal-ready collapse', () {
    testWidgets('status=ready with honest coverage renders nothing '
        '(SizedBox.shrink — the result card takes over)',
        (tester) async {
      await _pump(
        tester,
        _progressMsg(
          coverage: const {
            'total': 10, 'scanned': 10, 'pending': 0,
            'scan_complete': true,
          },
          status: 'ready',
        ),
      );
      expect(find.textContaining('Let me check your vault'), findsNothing);
      expect(find.textContaining('Scan complete'), findsNothing);
      expect(find.byType(Card), findsNothing);
    });
  });
}
