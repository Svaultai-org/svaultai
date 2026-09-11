

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';


ChatMessage _travelMsg({
  String confidence = 'partial',
  List<String> found = const ['passport', 'visa'],
  List<String> missing = const ['boarding_pass', 'hotel_itinerary'],
  List<Map<String, dynamic>> expired = const [],
  List<Map<String, dynamic>> expiringSoon = const [],
  String message = "You're partly travel-ready.",
}) {
  return ChatMessage(
    'assistant',
    message,
    kind: ChatMessage.kTravelReadiness,
    payload: <String, dynamic>{
      'confidence': confidence,
      'found': found,
      'missing': missing,
      'expired': expired,
      'expiring_soon': expiringSoon,
    },
  );
}


Future<void> _pump(
  WidgetTester tester, {
  required ChatMessage msg,
  Size viewport = const Size(900, 800),
}) async {
  tester.view.physicalSize = viewport;
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
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: TravelReadinessCard(msg: msg),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}


void main() {
  group('TravelReadinessCard — status chip', () {
    testWidgets('ready confidence shows READY label', (tester) async {
      await _pump(
        tester,
        msg: _travelMsg(
          confidence: 'ready',
          found: const ['passport', 'visa', 'boarding_pass', 'ticket', 'hotel_itinerary'],
          missing: const [],
        ),
      );
      expect(find.text('READY'), findsOneWidget);
    });

    testWidgets('partial confidence shows PARTIAL label', (tester) async {
      await _pump(tester, msg: _travelMsg(confidence: 'partial'));
      expect(find.text('PARTIAL'), findsOneWidget);
    });

    testWidgets('blocked confidence shows BLOCKED label', (tester) async {
      await _pump(
        tester,
        msg: _travelMsg(
          confidence: 'blocked',
          found: const ['passport'],
          missing: const ['visa', 'boarding_pass'],
          expired: const [
            {
              'doc_type': 'passport',
              'file_id': 'p1',
              'expiry_date': '2025-09-15',
              'label': 'Maureen passport',
              'days_overdue': 257,
            },
          ],
        ),
      );
      expect(find.text('BLOCKED'), findsOneWidget);
    });
  });

  group('TravelReadinessCard — sections', () {
    testWidgets('found section lists pretty doc types', (tester) async {
      await _pump(
        tester,
        msg: _travelMsg(
          found: const ['passport', 'visa'],
          missing: const ['hotel_itinerary'],
        ),
      );
      expect(find.text('Found'), findsOneWidget);
      expect(find.text('Passport'), findsOneWidget);
      expect(find.text('Visa'), findsOneWidget);
    });

    testWidgets('missing section names docs', (tester) async {
      await _pump(
        tester,
        msg: _travelMsg(
          found: const ['passport'],
          missing: const ['hotel_itinerary', 'boarding_pass'],
        ),
      );
      expect(find.text('Missing'), findsOneWidget);
      expect(find.text('Hotel itinerary'), findsOneWidget);
      expect(find.text('Boarding pass'), findsOneWidget);
    });

    testWidgets('expired section shows "expired Nd ago"', (tester) async {
      await _pump(
        tester,
        msg: _travelMsg(
          confidence: 'blocked',
          found: const ['passport'],
          expired: const [
            {
              'doc_type': 'passport',
              'file_id': 'p1',
              'expiry_date': '2025-09-15',
              'label': 'Maureen passport',
              'days_overdue': 257,
            },
          ],
        ),
      );
      expect(find.text('Expired'), findsOneWidget);
      expect(
        find.textContaining('expired 257d ago'),
        findsOneWidget,
      );
    });

    testWidgets('expiring soon section shows days countdown',
        (tester) async {
      await _pump(
        tester,
        msg: _travelMsg(
          confidence: 'partial',
          found: const ['visa'],
          expiringSoon: const [
            {
              'doc_type': 'visa',
              'file_id': 'v1',
              'expiry_date': '2026-06-25',
              'label': 'Qatar visa',
              'days_until': 18,
            },
          ],
        ),
      );
      expect(find.text('Expiring soon'), findsOneWidget);
      expect(find.textContaining('18d'), findsOneWidget);
      expect(find.textContaining('Qatar visa'), findsOneWidget);
    });
  });

  group('TravelReadinessCard — empty state', () {
    testWidgets('empty vault renders friendly upload prompt',
        (tester) async {
      await _pump(
        tester,
        msg: ChatMessage(
          'assistant',
          "I don't see any travel documents in your vault yet. Upload a "
          "passport, visa, or boarding pass to start a travel readiness "
          "check.",
          kind: ChatMessage.kTravelReadiness,
          payload: const <String, dynamic>{
            'confidence': 'blocked',
            'found': <String>[],
            'missing': <String>[],
            'expired': <Map<String, dynamic>>[],
            'expiring_soon': <Map<String, dynamic>>[],
          },
        ),
      );
      expect(find.textContaining('Upload a passport'), findsOneWidget);
    });
  });

  group('TravelReadinessCard — overflow guards', () {
    testWidgets('many docs across sections do not overflow',
        (tester) async {
      await _pump(
        tester,
        msg: _travelMsg(
          confidence: 'blocked',
          found: const ['passport', 'visa', 'ticket'],
          missing: const ['boarding_pass', 'hotel_itinerary'],
          expired: List.generate(
            10,
            (i) => <String, dynamic>{
              'doc_type': 'visa',
              'file_id': 'v$i',
              'expiry_date': '2024-01-01',
              'label': 'Country $i visa',
              'days_overdue': i + 1,
            },
          ),
          expiringSoon: List.generate(
            10,
            (i) => <String, dynamic>{
              'doc_type': 'visa',
              'file_id': 'vs$i',
              'expiry_date': '2026-07-01',
              'label': 'Soon $i visa',
              'days_until': i + 1,
            },
          ),
        ),
        viewport: const Size(900, 800),
      );
      expect(tester.takeException(), isNull);
    });
  });

  group('TravelReadinessCard — source guards', () {
    test('chat_models.dart exposes kTravelReadiness', () {
      expect(ChatMessage.kTravelReadiness, equals('travel_readiness'));
    });

    test('main.dart parser handles travel_readiness type', () async {
      final src = await File('lib/main.dart').readAsString();
      expect(src, contains("type == 'travel_readiness'"));
    });

    test('chat_bubble.dart routes kTravelReadiness to TravelReadinessCard',
        () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      expect(src, contains('ChatMessage.kTravelReadiness'));
      expect(src, contains('TravelReadinessCard'));
    });
  });
}
