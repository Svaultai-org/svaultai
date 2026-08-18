import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart' as vcr;
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';


Future<void> _pumpReview(WidgetTester tester) async {
  tester.view.physicalSize = const Size(1000, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  final message = ChatMessage(
    'assistant',
    'Review',
    kind: ChatMessage.kCredentialExtractionReview,
    payload: <String, dynamic>{
      'count': 1,
      'text_available': true,
      'file': const <String, dynamic>{
        'file_id': 'synthetic-fidelity-file',
        'file_name': 'synthetic-field-fidelity.pdf',
      },
      'records': const <Map<String, dynamic>>[
        {
          'candidate_id': 'dddddddddddddddddddddddd',
          'record_type': 'LOGIN',
          'secret_type': 'login',
          'service': 'Mixed',
          'password_present': true,
          'pin_present': true,
          'note_present': false,
          'source_context': 'synthetic-field-fidelity.pdf, page 1',
          'fields': <String, dynamic>{
            'user_id': 'test-user-001',
            'login_id': 'member55',
            'account_id': 'account-77',
            'password': 'ExactPass!XYZ',
            'pin': '9988',
            'secure_value': 'alpha-beta',
            'custom_token': 'case-Sensitive.Value',
          },
        },
      ],
    },
  );
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: CredentialExtractionReviewCard(
        msg: message,
        onAction: (String _, Map<String, dynamic>? __) async {},
      ),
    ),
  ));
  await tester.pumpAndSettle();
}


Finder _visibleText(String value) => find.byWidgetPredicate((widget) {
  if (widget is Text) return (widget.data ?? '') == value;
  if (widget is SelectableText) return (widget.data ?? '') == value;
  return false;
});


Map<String, dynamic> _retrievalEnvelope() => <String, dynamic>{
  'intent': 'vault_login_search',
  'card': <String, dynamic>{
    'schema': 'vault_chat_router_v1',
    'cardType': 'vault_login_card',
    'view': 'detail',
    'query': 'mixed',
    'data': <String, dynamic>{
      'schema': 'vault_login_data_v1',
      'available': true,
      'view': 'detail',
      'query': 'mixed',
      'login': <String, dynamic>{
        'id': 'login-1',
        'record_id': 'synthetic-mixed-1',
        'title': 'Mixed',
        'service': 'Mixed',
        'username': 'member55',
        'identifier_type': 'login_id',
        'identifier_label': 'Login ID',
        'password': 'ExactPass!XYZ',
        'domain': '',
        'website': '',
        'notes': '',
        'fields': const <Map<String, String>>[
          {'label': 'Login ID', 'value': 'member55'},
          {'label': 'Secure value', 'value': 'alpha-beta'},
          {'label': 'PIN', 'value': '9988'},
          {'label': 'Password', 'value': 'ExactPass!XYZ'},
        ],
      },
    },
  },
};


void main() {
  testWidgets('review renders typed identifiers and hides all secure fields',
      (tester) async {
    await _pumpReview(tester);

    expect(find.text('User ID: test-user-001'), findsOneWidget);
    expect(find.text('Login ID: member55'), findsOneWidget);
    expect(find.text('Account ID: account-77'), findsOneWidget);
    expect(find.textContaining('ExactPass!XYZ'), findsNothing);
    expect(find.text('Secure value: ••••••••••'), findsOneWidget);
    expect(find.text('Custom Token: ••••••••••'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey(
      'credential_extraction_reveal_dddddddddddddddddddddddd',
    )));
    await tester.pumpAndSettle();
    expect(find.text('Password: ExactPass!XYZ'), findsOneWidget);
    expect(find.text('PIN: 9988'), findsOneWidget);
    expect(find.text('Secure value: alpha-beta'), findsOneWidget);
    expect(find.text('Custom Token: case-Sensitive.Value'), findsOneWidget);
  });

  testWidgets('chat retrieval renders every source-typed field',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Scaffold(
        body: SingleChildScrollView(
          child: VaultChatCardView(
            response: vcr.VaultChatResponse.fromJson(_retrievalEnvelope()),
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();

    for (final value in const <String>[
      'Login ID',
      'member55',
      'Secure value',
      'alpha-beta',
      'PIN',
      '9988',
      'Password',
      'ExactPass!XYZ',
    ]) {
      expect(_visibleText(value), findsOneWidget, reason: value);
    }
  });
}
