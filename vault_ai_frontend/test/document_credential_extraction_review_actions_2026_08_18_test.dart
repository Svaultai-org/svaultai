import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/attachment_credential_review.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

List<Map<String, dynamic>> _records() => <Map<String, dynamic>>[
      {
        'candidate_id': 'aaaaaaaaaaaaaaaaaaaaaaaa',
        'record_type': 'LOGIN',
        'secret_type': 'login',
        'service': 'Synthetic Alpha',
        'username': 'alpha-user',
        'email': null,
        'website': 'https://alpha.example.invalid',
        'password_present': true,
        'pin_present': false,
        'note_present': false,
        'source_context': 'synthetic-three-logins.pdf, page 1',
        'fields': const <String, dynamic>{
          'username': 'alpha-user',
          'password': 'Alpha-Secret !@# with spaces',
          'url': 'https://alpha.example.invalid',
        },
      },
      {
        'candidate_id': 'bbbbbbbbbbbbbbbbbbbbbbbb',
        'record_type': 'ACCOUNT_NUMBER',
        'secret_type': 'account_number',
        'service': 'Synthetic Beta',
        'username': null,
        'email': 'beta@example.invalid',
        'website': 'https://beta.example.invalid',
        'password_present': true,
        'pin_present': false,
        'note_present': true,
        'source_context': 'synthetic-three-logins.pdf, page 2',
        'fields': const <String, dynamic>{
          'email': 'beta@example.invalid',
          'password': 'Beta-Secret',
          'account_number': '0001 0020 0300',
          'note': 'synthetic note',
          'url': 'https://beta.example.invalid',
        },
      },
      {
        'candidate_id': 'cccccccccccccccccccccccc',
        'record_type': 'PIN',
        'secret_type': 'pin',
        'service': 'Synthetic Gamma',
        'username': 'gamma-user',
        'email': null,
        'website': 'https://gamma.example.invalid',
        'password_present': true,
        'pin_present': false,
        'note_present': false,
        'source_context': 'synthetic-three-logins.pdf, page 3',
        'fields': const <String, dynamic>{
          'username': 'gamma-user',
          'password': 'Gamma-Secret',
          'pin': '0042',
          'url': 'https://gamma.example.invalid',
        },
      },
    ];

ChatMessage _message({List<Map<String, dynamic>>? records}) => ChatMessage(
      'assistant',
      'Review all candidates. Nothing is saved until you confirm.',
      kind: ChatMessage.kCredentialExtractionReview,
      payload: <String, dynamic>{
        'records': records ?? _records(),
        'count': (records ?? _records()).length,
        'analysis_counts': const <String, dynamic>{
          'pdf_page_count': 3,
          'text_extraction_page_count': 3,
          'normalized_record_count': 3,
        },
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
  test('only attachment credential review uses the analyzable upload path', () {
    for (final phrase in <String>[
      'analyze this file and save the credentials',
      'read this document and find all logins',
      'extract the passwords from this file',
      'show me all credentials in this document',
      'find all usernames and passwords in this PDF',
      'analyze this attached PDF and save credentials',
      'analyze this and save yhe credentials',
      'anlyze this and save the credentials',
      'analyse this and save credentials',
      'analyze ths and find all passwords',
      'read this file and extract credntials',
      'read this and get all passwords',
      'find the logins in this',
      'what credentials are in this?',
    ]) {
      expect(
        shouldUseServerReadableCredentialReview(phrase),
        isTrue,
        reason: phrase,
      );
    }
    for (final phrase in <String>[
      'generate me an instagram login',
      'create a new password for Facebook',
      'upload this file',
      'summarize this document',
      'show my facebook login',
      'username anlyze password credntials',
    ]) {
      expect(
        shouldUseServerReadableCredentialReview(phrase),
        isFalse,
        reason: phrase,
      );
    }
  });

  test('command normalization is disposable and never rewrites secret data',
      () {
    const supplied = 'username anlyze password credntials';
    expect(
      normalizeAttachmentCommandLanguage(supplied),
      'username analyze password credentials',
    );
    expect(supplied, 'username anlyze password credntials');
    expect(shouldUseServerReadableCredentialReview(supplied), isFalse);
  });

  test('file-v2 is bypassed only for an explicit credential review', () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(
      source,
      contains('if (fileV2Write && !needsServerCredentialReview)'),
    );
    expect(
      source,
      contains('shouldUseServerReadableCredentialReview('
          'ctx.accompanyingText)'),
    );
  });

  test('credential review continues after the analyzable upload auto-names',
      () {
    final source = File('lib/main.dart').readAsStringSync();
    expect(
      source,
      contains('final isCurrentAttachmentCredentialReview = hadAttachments &&'),
    );
    expect(
      source,
      contains('if (uploadOutcome.autoNamedAny &&\n'
          '          !isCurrentAttachmentCredentialReview)'),
    );
    expect(
      source,
      contains('uploadedFileIds.isNotEmpty &&\n'
          '          !isCurrentAttachmentCredentialReview &&'),
    );
  });

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

  testWidgets('renders three masked mixed candidates with per-row actions',
      (tester) async {
    await _pump(tester, onAction: (_, __) {});

    expect(find.text('Synthetic Alpha'), findsOneWidget);
    expect(find.text('Password: ••••••••••'), findsWidgets);
    expect(find.text('Save'), findsWidgets);
    expect(find.text('Edit'), findsWidgets);
    expect(find.text('Ignore'), findsWidgets);
    expect(find.byKey(const Key('credential_extraction_save_selected')),
        findsOneWidget);
    expect(find.textContaining('Alpha-Secret'), findsNothing);
    expect(find.text('login'), findsOneWidget);
    expect(find.text('Pages: 3/3  •  Candidates: 3'), findsOneWidget);
    await tester.drag(find.byType(ListView), const Offset(0, -500));
    await tester.pumpAndSettle();
    expect(find.text('Synthetic Gamma'), findsOneWidget);
    expect(find.text('pin'), findsOneWidget);
  });

  testWidgets('owner reveal shows exact punctuation and whitespace value',
      (tester) async {
    await _pump(tester, onAction: (_, __) {});

    const exact = 'Alpha-Secret !@# with spaces';
    expect(find.textContaining(exact), findsNothing);
    await tester.tap(find.byKey(const ValueKey(
      'credential_extraction_reveal_aaaaaaaaaaaaaaaaaaaaaaaa',
    )));
    await tester.pumpAndSettle();
    expect(find.text('Password: $exact'), findsOneWidget);
    expect(find.text('Hide extracted values'), findsOneWidget);
  });

  testWidgets('all sixty candidates remain selected and actionable',
      (tester) async {
    final many = List<Map<String, dynamic>>.generate(60, (index) {
      final id = index.toString().padLeft(24, '0');
      return <String, dynamic>{
        'candidate_id': id,
        'record_type': 'LOGIN',
        'secret_type': 'login',
        'service': 'Synthetic $index',
        'password_present': true,
        'pin_present': false,
        'note_present': false,
        'source_context': 'synthetic-twelve-pages.pdf, page ${index ~/ 5 + 1}',
        'fields': <String, dynamic>{
          'username': 'user-$index',
          'password': 'Secret-$index',
        },
      };
    });
    String? action;
    Map<String, dynamic>? data;
    await _pump(
      tester,
      records: many,
      onAction: (nextAction, nextData) {
        action = nextAction;
        data = nextData;
      },
    );

    expect(CredentialExtractionReviewCard.maxRows, greaterThanOrEqualTo(60));
    expect(find.text('Save selected (60)'), findsOneWidget);
    await tester.tap(find.byKey(
      const Key('credential_extraction_save_selected'),
    ));
    await tester.pumpAndSettle();
    expect(action, 'credential_extraction_save_selected');
    expect((data?['candidate_ids'] as List).length, 60);
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
