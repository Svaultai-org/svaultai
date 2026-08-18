import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

List<Map<String, dynamic>> _records() => <Map<String, dynamic>>[
      {
        'candidate_id': 'aaaaaaaaaaaaaaaaaaaaaaaa',
        'service': 'Synthetic Alpha',
        'username': 'alpha-user',
        'email': null,
        'website': 'https://alpha.example.invalid',
        'password_present': true,
        'pin_present': false,
        'note_present': false,
        'source_context': 'synthetic-three-logins.pdf',
      },
      {
        'candidate_id': 'bbbbbbbbbbbbbbbbbbbbbbbb',
        'service': 'Synthetic Beta',
        'username': null,
        'email': 'beta@example.invalid',
        'website': 'https://beta.example.invalid',
        'password_present': true,
        'pin_present': false,
        'note_present': true,
        'source_context': 'synthetic-three-logins.pdf',
      },
      {
        'candidate_id': 'cccccccccccccccccccccccc',
        'service': 'Synthetic Gamma',
        'username': 'gamma-user',
        'email': null,
        'website': 'https://gamma.example.invalid',
        'password_present': true,
        'pin_present': false,
        'note_present': false,
        'source_context': 'synthetic-three-logins.pdf',
      },
    ];

ChatMessage _message({List<Map<String, dynamic>>? records}) => ChatMessage(
      'assistant',
      'Review all candidates. Nothing is saved until you confirm.',
      kind: ChatMessage.kCredentialExtractionReview,
      payload: <String, dynamic>{
        'records': records ?? _records(),
        'count': (records ?? _records()).length,
        'text_available': true,
        'file': const <String, dynamic>{
          'file_id': 'file-synthetic',
          'file_name': 'synthetic-three-logins.pdf',
        },
      },
    );

Future<void> _pump(
  WidgetTester tester, {
  required FutureOr<void> Function(
    String action,
    Map<String, dynamic>? data,
  ) onAction,
  List<Map<String, dynamic>>? records,
}) async {
  tester.view.physicalSize = const Size(1000, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: CredentialExtractionReviewCard(
          msg: _message(records: records),
          onAction: onAction,
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  test('encrypted review command bypasses local natural-language routers', () {
    final source = File('lib/main.dart').readAsStringSync();
    final sendStart = source.indexOf('Future<void> _send() async');
    final commandConsume = source.indexOf(
      'final privateBackendCommand = _nextEncryptedBackendCommand;',
      sendStart,
    );
    final localRoutes = source.indexOf(
      'if (!hasPrivateBackendCommand) {',
      commandConsume,
    );
    final backendAssignment = source.indexOf(
      'backendText = privateBackendCommand;',
      localRoutes,
    );

    expect(sendStart, greaterThanOrEqualTo(0));
    expect(commandConsume, greaterThan(sendStart));
    expect(localRoutes, greaterThan(commandConsume));
    expect(backendAssignment, greaterThan(localRoutes));
  });

  testWidgets('renders three masked candidates with per-row actions',
      (tester) async {
    await _pump(tester, onAction: (_, __) {});

    expect(find.text('Synthetic Alpha'), findsOneWidget);
    expect(find.text('Synthetic Beta'), findsOneWidget);
    expect(find.text('Synthetic Gamma'), findsOneWidget);
    expect(find.text('Password: ••••••••••'), findsNWidgets(3));
    expect(find.text('Save'), findsNWidgets(3));
    expect(find.text('Edit'), findsNWidgets(3));
    expect(find.text('Ignore'), findsNWidgets(3));
    expect(find.byKey(const Key('credential_extraction_save_selected')),
        findsOneWidget);
    expect(find.textContaining('Alpha-Secret'), findsNothing);
  });

  testWidgets('ignore one excludes it from save selected', (tester) async {
    String? action;
    Map<String, dynamic>? data;
    await _pump(tester, onAction: (nextAction, nextData) {
      action = nextAction;
      data = nextData;
    });

    await tester.tap(find.byKey(const ValueKey(
        'credential_extraction_ignore_aaaaaaaaaaaaaaaaaaaaaaaa')));
    await tester.pumpAndSettle();
    expect(find.text('ignored'), findsOneWidget);
    expect(find.text('Save selected (2)'), findsOneWidget);

    await tester
        .tap(find.byKey(const Key('credential_extraction_save_selected')));
    await tester.pumpAndSettle();
    expect(action, 'credential_extraction_save_selected');
    expect(
      data?['candidate_ids'],
      <String>[
        'bbbbbbbbbbbbbbbbbbbbbbbb',
        'cccccccccccccccccccccccc',
      ],
    );
  });

  testWidgets('save one sends only that candidate id', (tester) async {
    String? action;
    Map<String, dynamic>? data;
    await _pump(tester, onAction: (nextAction, nextData) {
      action = nextAction;
      data = nextData;
    });

    await tester.tap(find.byKey(
        const ValueKey('credential_extraction_save_aaaaaaaaaaaaaaaaaaaaaaaa')));
    await tester.pumpAndSettle();
    expect(action, 'credential_extraction_save');
    expect(data?['candidate_ids'], <String>['aaaaaaaaaaaaaaaaaaaaaaaa']);
    expect(find.text('handled'), findsOneWidget);
  });

  testWidgets(
      'edit saves encrypted override intent without revealing source password',
      (tester) async {
    String? action;
    Map<String, dynamic>? data;
    await _pump(
      tester,
      records: <Map<String, dynamic>>[_records().first],
      onAction: (nextAction, nextData) {
        action = nextAction;
        data = nextData;
      },
    );

    await tester.tap(find.byKey(
        const ValueKey('credential_extraction_edit_aaaaaaaaaaaaaaaaaaaaaaaa')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('credential_extraction_edit_service')),
      'Synthetic Alpha Edited',
    );
    await tester.enterText(
      find.byKey(const Key('credential_extraction_edit_password')),
      'Replacement-Synthetic-Secret',
    );
    await tester.tap(find.byKey(const Key('credential_extraction_edit_save')));
    await tester.pumpAndSettle();

    expect(action, 'credential_extraction_edit_and_save');
    final overrides = data?['overrides'] as Map<String, dynamic>;
    final edited =
        overrides['aaaaaaaaaaaaaaaaaaaaaaaa'] as Map<String, dynamic>;
    expect(edited['service'], 'Synthetic Alpha Edited');
    expect(edited['password'], 'Replacement-Synthetic-Secret');
    expect(find.textContaining('Replacement-Synthetic-Secret'), findsNothing);
  });
}
