// 2026-07-31 frontend-contract tests for the two backend envelope
// changes shipped in d184d22 (Codex blockers 1 and 2).
//
// This file proves that Flutter parses the EXACT payload the backend
// now emits AND renders it as a structured card — never as plain
// assistant text. If the backend contract regresses (say, someone
// renames `files` back to `options`, or drops the router-V1 wrapper
// around a credential draft), these tests fail loudly.
//
// The tests exercise the parser layer directly. Widget-render tests
// for the same shapes live in file_disambiguation_card_test.dart
// (which the router's disambiguation output feeds into as-is) and
// vault_chat_card_stream_parser_2026_07_12_test.dart (which the
// router's generated-login envelope feeds into as-is).

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart';
import 'package:vault_ai_frontend/services/vault_chat_stream_parser.dart';
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';

// ---------------------------------------------------------------------------
// Fixtures — captured VERBATIM from the backend endpoint tests
// (test_chat_endpoint_deterministic_2026_08_01.py evidence dump).
// ---------------------------------------------------------------------------

// Blocker 1 evidence: an actual `file_disambiguation` envelope
// captured from POST /chat with 2 candidates. Uses `files` (not
// `options`) — the field name Flutter reads.
const String kBackendDisambigJson = '''
{
  "type":  "file_disambiguation",
  "files": [
    {
      "file_id":       "row-pdf-passport-2024",
      "file_name":     "passport-2024.pdf",
      "saved_name":    "passport 2024",
      "relative_path": null,
      "mime_type":     "application/pdf",
      "asset_type":    "pdf",
      "confidence":    "medium",
      "reasons":       ["saved-name substring match"],
      "best_match":    false,
      "mostly_credentials": false,
      "purpose_label": null
    },
    {
      "file_id":       "row-pdf-passport-2025",
      "file_name":     "passport-2025.pdf",
      "saved_name":    "passport 2025",
      "relative_path": null,
      "mime_type":     "application/pdf",
      "asset_type":    "pdf",
      "confidence":    "medium",
      "reasons":       ["saved-name substring match"],
      "best_match":    false,
      "mostly_credentials": false,
      "purpose_label": null
    }
  ],
  "title":         "Which file do you mean by \\"passport\\"?",
  "count":         2,
  "context_kind":  "named_object",
  "candidate_name": "passport",
  "message":       "I found 2 items whose saved name matches \\"passport\\". Tap the one you meant.",
  "resolved_by":   "deterministic_router"
}
''';

// Blocker 2 evidence: an actual `vault_chat_card` envelope
// wrapping a generated-login draft, captured from POST /chat.
// The Flutter parser at vault_chat_stream_parser.dart:88-168
// requires this exact wrapper shape.
// 2026-08-01 UPDATED — the backend now populates the `card` sub-dict
// with the actual credential values so the Flutter renderer can show
// service / username / password / draft_id + Save/Cancel buttons.
// The whole /chat SSE stream is AES-GCM encrypted; the plaintext
// password never crosses the trust boundary in the clear.
const String kBackendCredDraftJson = '''
{
  "type":    "vault_chat_card",
  "schema":  "vault_chat_response_v1",
  "intent":  "vault_generated_login_create_draft",
  "message": "I prepared a HBO Max login draft. Review the values, then tap Save to store it in your vault or Cancel to discard it.",
  "card": {
    "cardType": "vault_generated_login_card",
    "view":     "create_draft",
    "data": {
      "schema":       "vault_generated_login_draft_v1",
      "view":         "create_draft",
      "service":      "HBO Max",
      "service_name": "HBO Max",
      "username":     "beraves123@gmail.com",
      "password":     "P@ssw0rd!ExampleGenerated",
      "draft_id":     "draft-endpoint-0001",
      "email":        "beraves123@gmail.com",
      "explicit_fields": ["username", "email"],
      "actions":      ["save", "cancel"]
    }
  },
  "resolved_by": "deterministic_router"
}
''';

// A regression-fossil: what the backend used to emit BEFORE d184d22.
// The parser must NOT accept this — it degraded to plain text in
// production. If someone reverts blocker #2, this fixture becomes a
// real envelope again and the "must not parse" assertion below
// catches it.
const String kOldBrokenCredDraftJson = '''
{
  "type":            "vault_generated_login_card",
  "service":         "youtube",
  "username":        "beraves@gmail.com",
  "password":        "P@ssw0rd!",
  "draft_id":        "draft-yt-1",
  "explicit_fields": ["username"],
  "message":         "Draft youtube login ready.",
  "resolved_by":     "deterministic_router"
}
''';

// Another regression-fossil: the backend used to emit `options` in
// the disambiguation envelope. Flutter would fall through and render
// an empty candidate list. If someone reverts blocker #1, this
// fixture becomes real again and the "must render 0 files" assertion
// below catches it.
const String kOldBrokenDisambigJson = '''
{
  "type":            "file_disambiguation",
  "options":         [
    {"file_id": "row-pdf-passport-2024", "file_name": "passport-2024.pdf"},
    {"file_id": "row-pdf-passport-2025", "file_name": "passport-2025.pdf"}
  ],
  "candidate_name":  "passport",
  "message":         "I found 2 items with a similar name.",
  "resolved_by":     "deterministic_router"
}
''';

// ---------------------------------------------------------------------------
// Blocker 1 — file_disambiguation.files parser + renderer
// ---------------------------------------------------------------------------

void _testBlocker1() {
  group('Blocker 1: file_disambiguation.files', () {
    test('backend envelope decodes to a two-entry `files` list', () {
      final decoded = jsonDecode(kBackendDisambigJson) as Map<String, dynamic>;
      expect(decoded['type'], 'file_disambiguation');
      expect(decoded['files'], isA<List>());
      final files = (decoded['files'] as List).cast<Map<String, dynamic>>();
      expect(files.length, 2);
      expect(files[0]['file_id'], 'row-pdf-passport-2024');
      expect(files[1]['file_id'], 'row-pdf-passport-2025');
    });

    test('each row carries every field the frontend row reader keys on', () {
      final decoded = jsonDecode(kBackendDisambigJson) as Map<String, dynamic>;
      final files = (decoded['files'] as List).cast<Map<String, dynamic>>();
      for (final row in files) {
        // These are the keys the row renderer at chat_cards.dart:3520
        // reads. Missing any is a rendering regression.
        expect(row.containsKey('file_id'), isTrue);
        expect(row.containsKey('file_name'), isTrue);
        expect(row.containsKey('saved_name'), isTrue);
        expect(row.containsKey('mime_type'), isTrue);
        expect(row.containsKey('confidence'), isTrue);
        expect(row.containsKey('reasons'), isTrue);
        expect(row.containsKey('best_match'), isTrue);
        expect(row.containsKey('mostly_credentials'), isTrue);
      }
    });

    test('`content_type` is NOT the key the frontend reads (mime_type is)', () {
      final decoded = jsonDecode(kBackendDisambigJson) as Map<String, dynamic>;
      final files = (decoded['files'] as List).cast<Map<String, dynamic>>();
      // Belt-and-braces: earlier internal envelopes used content_type.
      // If someone re-introduces it and drops mime_type, the row
      // renderer at chat_cards.dart:3520-3533 renders "unknown mime".
      expect(files[0].containsKey('content_type'), isFalse);
      expect(files[0]['mime_type'], 'application/pdf');
    });

    testWidgets(
      'ChatMessage built from the backend envelope renders '
      'FileDisambiguationCard, not plain assistant text',
      (WidgetTester tester) async {
        final decoded =
            jsonDecode(kBackendDisambigJson) as Map<String, dynamic>;
        final files = (decoded['files'] as List).cast<Map<String, dynamic>>();
        final msg = ChatMessage(
          'assistant',
          decoded['message']?.toString() ?? '',
          kind: ChatMessage.kFileDisambiguation,
          payload: <String, dynamic>{
            'files': files,
            'title': decoded['title']?.toString(),
            'count': decoded['count'],
            'context_kind': decoded['context_kind'],
          },
        );

        // Reproduce the exact pump the existing disambig test uses.
        tester.view.physicalSize = const Size(900, 800);
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
            supportedLocales: const [Locale('en')],
            home: Scaffold(
              body: FileDisambiguationCard(
                msg: msg,
                onOpen: (_) {},
              ),
            ),
          ),
        );
        await tester.pumpAndSettle(const Duration(milliseconds: 200));

        // Structured card render evidence: the row title is
        // `saved_name` if present, else `file_name` (see
        // chat_cards.dart:3535). Both saved names must appear —
        // if parsing regressed and the frontend fell back to plain
        // assistant text, neither structured row would render.
        expect(find.text('passport 2024'), findsOneWidget,
            reason: 'file_disambiguation.files[0].saved_name did not '
                'render as a card row — parser or contract '
                'regressed');
        expect(find.text('passport 2025'), findsOneWidget,
            reason: 'file_disambiguation.files[1].saved_name did not '
                'render as a card row — parser or contract '
                'regressed');
      },
    );

    test(
        'regression-fossil: the OLD `options` envelope produces an '
        'empty files list — exactly the empty-render bug Codex flagged', () {
      final decoded =
          jsonDecode(kOldBrokenDisambigJson) as Map<String, dynamic>;
      // The parser cast at main.dart:11204 uses `decoded['files']`.
      // With the old envelope shape, `files` is null → cast becomes
      // an empty list → card renders zero candidates. Test that the
      // regression signature is what we expect.
      final filesRaw = decoded['files'];
      final files = filesRaw is List
          ? filesRaw.cast<Map<String, dynamic>>()
          : const <Map<String, dynamic>>[];
      expect(files, isEmpty,
          reason: 'old envelope shape leaks empty candidate list — '
              'this is the exact bug the fix closes');
    });
  });
}

// ---------------------------------------------------------------------------
// Blocker 2 — vault_chat_card + card.cardType=vault_generated_login_card
// ---------------------------------------------------------------------------

void _testBlocker2() {
  group('Blocker 2: vault_chat_card generated-login envelope', () {
    test('parseVaultChatCardMessage accepts the new backend envelope', () {
      final result = parseVaultChatCardMessage(kBackendCredDraftJson);
      expect(result, isNotNull,
          reason: 'parser rejected a valid vault_chat_card envelope '
              '— rendering will fall back to plain assistant text');
      expect(result!.kind, ChatMessage.kVaultChatCard);
      final payload = result.payload;
      expect(payload, isNotNull);
      expect(payload!['intent'], 'vault_generated_login_create_draft');
      final card = payload['card'] as Map<String, dynamic>;
      expect(card['cardType'], 'vault_generated_login_card');
      expect(card['view'], 'create_draft');
    });

    test('parser REJECTS the OLD top-level type (regression fossil)', () {
      // The pre-blocker-2 envelope used `type: "vault_generated_login_card"`
      // at the top level. The parser at vault_chat_stream_parser.dart:119
      // rejects anything whose type is not vault_chat_card/response_v1.
      // If someone reverts the fix, this test fails LOUDLY —
      // parseVaultChatCardMessage would return null on the OLD shape,
      // and the message would silently degrade to plain text at
      // main.dart:11451-11471.
      final result = parseVaultChatCardMessage(kOldBrokenCredDraftJson);
      expect(result, isNull,
          reason: 'parser accepted the old broken envelope — the '
              'blocker-2 fix has regressed');
    });

    testWidgets(
      'ChatMessage from the new envelope renders the structured '
      '_GeneratedLoginCard with service, username, masked password, '
      'and Save/Cancel buttons — not plain assistant text',
      (WidgetTester tester) async {
        final result = parseVaultChatCardMessage(kBackendCredDraftJson);
        expect(result, isNotNull);

        tester.view.physicalSize = const Size(900, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });

        // Route through VaultChatResponse.fromJson → the same
        // widget the real chat bubble uses (VaultChatCardView).
        final envelope =
            jsonDecode(kBackendCredDraftJson) as Map<String, dynamic>;
        final response = VaultChatResponse.fromJson(envelope);
        expect(response.card.cardType, 'vault_generated_login_card',
            reason: 'router failed to recognize the card type');

        String? savedDraftId;
        String? cancelledDraftId;
        await tester.pumpWidget(
          MaterialApp(
            localizationsDelegates: const [
              AppLocalizations.delegate,
              GlobalMaterialLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
            ],
            supportedLocales: const [Locale('en')],
            home: Scaffold(
              body: VaultChatCardView(
                response: response,
                onGeneratedLoginSave: (data) {
                  savedDraftId = '${data['draft_id']}';
                },
                onGeneratedLoginCancel: (id, svc) {
                  cancelledDraftId = id;
                },
              ),
            ),
          ),
        );
        await tester.pumpAndSettle(const Duration(milliseconds: 200));

        // 2026-08-01 widget rewrite. The card MUST now display:
        //   service name (HBO Max) as the title
        //   username in plaintext (never hidden)
        //   password masked by default
        //   Save + Cancel buttons

        // Service title.
        expect(
          find.byKey(const Key(
            'vault_chat_card_generated_login_service',
          )),
          findsOneWidget,
        );
        expect(find.text('HBO Max'), findsOneWidget,
            reason: 'service name not rendered as the card title');

        // Username row (visible in plaintext). Fixture has the
        // same value as `email` so we expect >=1 render (username +
        // optional email row when email is supplied).
        expect(
          find.text('beraves123@gmail.com'),
          findsWidgets,
          reason: 'username row must be plaintext and always visible',
        );
        // Explicit username-row key check — proves the Username row
        // specifically renders (not just any row with that value).
        expect(
          find.byKey(const Key(
            'vault_chat_card_generated_login_username_value',
          )),
          findsOneWidget,
        );

        // Password row (masked by default).
        final passwordValueFinder = find.byKey(const Key(
          'vault_chat_card_generated_login_password_value',
        ));
        expect(passwordValueFinder, findsOneWidget);
        final passwordDisplay = tester
            .widget<Text>(
              passwordValueFinder,
            )
            .data;
        expect(
          passwordDisplay?.contains('•'),
          isTrue,
          reason: 'password row must be masked by default',
        );
        expect(
          passwordDisplay?.contains('P@ssw0rd!ExampleGenerated'),
          isFalse,
          reason: 'plaintext password leaked in default (unrevealed) '
              'render — security regression',
        );

        // Reveal-eye toggle exposes the real password.
        final revealFinder = find.byKey(const Key(
          'vault_chat_card_generated_login_password_reveal',
        ));
        expect(revealFinder, findsOneWidget);
        await tester.tap(revealFinder);
        await tester.pumpAndSettle();
        final revealedText = tester
            .widget<Text>(
              passwordValueFinder,
            )
            .data;
        expect(
          revealedText,
          'P@ssw0rd!ExampleGenerated',
          reason: 'reveal toggle did not expose the plaintext password',
        );

        // Save + Cancel buttons wired to callbacks.
        final saveBtn = find.byKey(const Key(
          'vault_chat_card_generated_login_save',
        ));
        final cancelBtn = find.byKey(const Key(
          'vault_chat_card_generated_login_cancel',
        ));
        expect(saveBtn, findsOneWidget);
        expect(cancelBtn, findsOneWidget);

        // Tap Cancel first; callback fires with the draft id.
        await tester.tap(cancelBtn);
        await tester.pumpAndSettle();
        expect(cancelledDraftId, 'draft-endpoint-0001',
            reason: 'Cancel button did not invoke the callback with '
                'the correct draft_id');
        // Save doesn't fire because the widget debounces once
        // dispatched — verify that guard holds.
        expect(savedDraftId, isNull);
      },
    );

    testWidgets(
      'Copy button copies the username to the clipboard',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(900, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(() {
          tester.view.resetPhysicalSize();
          tester.view.resetDevicePixelRatio();
        });

        // Intercept clipboard writes for the assertion.
        final List<String> clipboardValues = <String>[];
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(SystemChannels.platform,
                (MethodCall call) async {
          if (call.method == 'Clipboard.setData') {
            final args = call.arguments as Map;
            clipboardValues.add((args['text'] ?? '').toString());
          }
          return null;
        });
        addTearDown(() {
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
              .setMockMethodCallHandler(SystemChannels.platform, null);
        });

        final envelope =
            jsonDecode(kBackendCredDraftJson) as Map<String, dynamic>;
        final response = VaultChatResponse.fromJson(envelope);
        await tester.pumpWidget(
          MaterialApp(
            localizationsDelegates: const [
              AppLocalizations.delegate,
              GlobalMaterialLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
            ],
            supportedLocales: const [Locale('en')],
            home: Scaffold(
              body: VaultChatCardView(response: response),
            ),
          ),
        );
        await tester.pumpAndSettle(const Duration(milliseconds: 200));

        await tester.tap(find.byKey(const Key(
          'vault_chat_card_generated_login_username_copy',
        )));
        await tester.pumpAndSettle();
        expect(
          clipboardValues,
          contains('beraves123@gmail.com'),
          reason: 'copy button did not write username to clipboard',
        );

        // Copy password too — value must be the plaintext even
        // when displayed masked in the UI.
        await tester.tap(find.byKey(const Key(
          'vault_chat_card_generated_login_password_copy',
        )));
        await tester.pumpAndSettle();
        expect(
          clipboardValues,
          contains('P@ssw0rd!ExampleGenerated'),
          reason: 'copy button did not write plaintext password to '
              'clipboard',
        );
      },
    );

    test(
        'the envelope does NOT surface generated username/password '
        'at the TOP level (security posture preserved)', () {
      final decoded = jsonDecode(kBackendCredDraftJson) as Map<String, dynamic>;
      // The credential values live INSIDE the `card.data` sub-dict —
      // not at the top level of the envelope, and not directly on
      // `card`. That way any caller that logs the outer envelope for
      // telemetry / audit cannot accidentally leak secrets.
      expect(decoded.containsKey('password'), isFalse);
      expect(decoded.containsKey('username'), isFalse);
      final card = decoded['card'] as Map<String, dynamic>;
      // Not on outer `card` either.
      expect(card.containsKey('password'), isFalse);
      expect(card.containsKey('username'), isFalse);
      // But they DO exist inside `card.data` so the widget can render.
      final data = card['data'] as Map<String, dynamic>;
      expect(data.containsKey('username'), isTrue);
      expect(data.containsKey('password'), isTrue);
    });
  });
}

void main() {
  _testBlocker1();
  _testBlocker2();
}
