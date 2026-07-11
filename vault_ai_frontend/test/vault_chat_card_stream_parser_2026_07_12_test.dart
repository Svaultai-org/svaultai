


import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart' as vcr;
import 'package:vault_ai_frontend/services/vault_chat_stream_parser.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';


const List<LocalizationsDelegate<Object?>> _testL10nDelegates = [
  AppLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];




const Map<String, dynamic> _PROD_ENVELOPE_LOGIN_SEARCH = {
  'type':    'vault_chat_card',
  'schema':  'vault_chat_response_v1',
  'intent':  'vault_login_search',
  'message': '',
  'card': {
    'schema':          'vault_chat_router_v1',
    'cardType':        'vault_login_card',
    'maskedByDefault': true,
    'liveFetchRequired': true,
    'view':            'search',
    'query':           'American First Credit Union',
    'data': {
      'schema':    'vault_login_data_v1',
      'available': true,
      'view':      'search',
      'query':     'American First Credit Union',
      'logins': [
        {
          'id':              'l-1',
          'title':           'American First Credit Union',
          'service':         'American First Credit Union',
          'username_masked': 'a•••@example.com',
          'has_username':    true,
          'domain':          'americanfirst.com',
          'updated_at':      '2026-07-11T09:00:00Z',
          'generated':       false,
        }
      ],
      'count':         1,
      'limit_applied': 50,
    },
  },
  'locale': 'pt',
};

const Map<String, dynamic> _PROD_ENVELOPE_LOGIN_MULTI = {
  'type':    'vault_chat_card',
  'schema':  'vault_chat_response_v1',
  'intent':  'vault_login_search',
  'message': '',
  'card': {
    'schema':          'vault_chat_router_v1',
    'cardType':        'vault_login_card',
    'maskedByDefault': true,
    'liveFetchRequired': true,
    'view':            'search',
    'query':           'Chase',
    'data': {
      'schema':    'vault_login_data_v1',
      'available': true,
      'view':      'search',
      'query':     'Chase',
      'logins': [
        {
          'id':              'l-1',
          'title':           'Chase',
          'service':         'Chase',
          'username_masked': 'a•••@example.com',
          'has_username':    true,
          'domain':          'chase.com',
          'updated_at':      '2026-07-11T09:00:00Z',
          'generated':       false,
        },
        {
          'id':              'l-2',
          'title':           'Chase Business',
          'service':         'Chase Business',
          'username_masked': 'b•••@example.com',
          'has_username':    true,
          'domain':          'chase.com',
          'updated_at':      '2026-07-11T09:00:00Z',
          'generated':       false,
        }
      ],
      'count':         2,
      'limit_applied': 50,
    },
  },
  'locale': 'en',
};

const Map<String, dynamic> _PROD_ENVELOPE_GENERATED_LOGIN = {
  'type':    'vault_chat_card',
  'schema':  'vault_chat_response_v1',
  'intent':  'vault_generated_login_create_draft',
  'message': '',
  'card': {
    'schema':                       'vault_chat_router_v1',
    'cardType':                     'vault_generated_login_card',
    'maskedByDefault':              true,
    'liveFetchRequired':            false,
    'view':                         'create_draft',
    'canSaveWithoutConfirmation':   false,
  },
  'locale': 'en',
};

const Map<String, dynamic> _PROD_ENVELOPE_STORAGE = {
  'type':    'vault_chat_card',
  'schema':  'vault_chat_response_v1',
  'intent':  'vault_storage_usage',
  'message': '',
  'card': {
    'schema':          'vault_chat_router_v1',
    'cardType':        'vault_storage_usage_card',
    'maskedByDefault': false,
    'liveFetchRequired': true,
  },
  'locale': 'en',
};

const Map<String, dynamic> _PROD_ENVELOPE_FILE_RESULT = {
  'type':    'vault_chat_card',
  'schema':  'vault_chat_response_v1',
  'intent':  'vault_file_search',
  'message': '',
  'card': {
    'schema':          'vault_chat_router_v1',
    'cardType':        'vault_file_result_card',
    'liveFetchRequired': true,
    'view':            'search',
    'query':           'passport',
  },
  'locale': 'en',
};

const Map<String, dynamic> _UNKNOWN_CARD = {
  'type':    'vault_chat_card',
  'schema':  'vault_chat_response_v1',
  'intent':  'vault_unrecognized',
  'message': '',
  'card': {
    'schema':   'vault_chat_router_v1',
    'cardType': 'vault_something_the_frontend_has_never_heard_of',
  },
  'locale': 'en',
};




void main() {
  group('parseVaultChatCardMessage — exact production envelope', () {
    test('production login-search envelope becomes a vault_chat_card '
        'ChatMessage (this is the failing case from prod)', () {
      final buffer = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull, reason:
          'The exact production envelope MUST parse. If this fails, '
          'the raw JSON is what the user is seeing in the bubble.');
      expect(msg!.kind, ChatMessage.kVaultChatCard);
      expect(msg.isCard, isTrue);
      expect(msg.role, 'assistant');

      final payload = msg.payload!;
      expect(payload['intent'], 'vault_login_search');
      expect(payload['schema'], 'vault_chat_response_v1');

      final card = payload['card'] as Map<String, dynamic>;
      expect(card['cardType'], 'vault_login_card');
      expect(card['maskedByDefault'], isTrue);
      expect(card['view'], 'search');
      expect(card['query'], 'American First Credit Union');
    });

    test('empty message field does NOT discard the card', () {

      final buffer = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
      expect(msg!.text, '');
      expect(msg.kind, ChatMessage.kVaultChatCard);
      expect(msg.isCard, isTrue);
    });

    test('locale field ("pt") does not break parsing', () {
      final buffer = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      expect(buffer, contains('"locale":"pt"'));
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
    });

    test('camelCase cardType is preserved verbatim (matches renderer)', () {
      final buffer = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
      final card = msg!.payload!['card'] as Map<String, dynamic>;

      expect(card.containsKey('cardType'), isTrue);
      expect(card['cardType'], 'vault_login_card');
      expect(card.containsKey('card_type'), isFalse);
    });

    test('generated-login envelope parses to a vault_chat_card too', () {
      final buffer = jsonEncode(_PROD_ENVELOPE_GENERATED_LOGIN);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
      expect(msg!.kind, ChatMessage.kVaultChatCard);
      final card = msg.payload!['card'] as Map<String, dynamic>;
      expect(card['cardType'], 'vault_generated_login_card');
    });

    test('storage envelope parses to a vault_chat_card', () {
      final buffer = jsonEncode(_PROD_ENVELOPE_STORAGE);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
      final card = msg!.payload!['card'] as Map<String, dynamic>;
      expect(card['cardType'], 'vault_storage_usage_card');
    });

    test('file-result envelope parses to a vault_chat_card', () {
      final buffer = jsonEncode(_PROD_ENVELOPE_FILE_RESULT);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
      final card = msg!.payload!['card'] as Map<String, dynamic>;
      expect(card['cardType'], 'vault_file_result_card');
    });

    test('unknown cardType still parses so the router-level fallback '
        'renders — never leaks raw JSON', () {

      final buffer = jsonEncode(_UNKNOWN_CARD);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull, reason:
          'unknown cardType must NOT return null — that would leak '
          'raw JSON in the bubble. The parser succeeds and the card '
          'renderer falls back to the unrecognized-card widget.');
    });
  });

  group('parseVaultChatCardMessage — negative + adversarial inputs', () {
    test('null buffer -> null', () {
      expect(parseVaultChatCardMessage(''), isNull);
    });

    test('non-JSON text -> null', () {
      expect(
        parseVaultChatCardMessage('hello there'),
        isNull,
      );
    });

    test('valid JSON but not a card envelope -> null', () {
      final buffer = jsonEncode({
        'type': 'vault_file',
        'file_id': 'x',
        'file_name': 'y',
      });
      expect(parseVaultChatCardMessage(buffer), isNull);
    });

    test('envelope without cardType -> null (renderer would render '
        'nothing anyway)', () {
      final buffer = jsonEncode({
        'type':   'vault_chat_card',
        'schema': 'vault_chat_response_v1',
        'intent': 'vault_login_search',
        'card':   {
          'schema': 'vault_chat_router_v1',
        },
      });
      expect(parseVaultChatCardMessage(buffer), isNull);
    });

    test('trailing NUL byte after the JSON does not break parsing '
        '(defensive against buggy transports)', () {
      final buffer =
          '${jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH)}\x00';
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
    });

    test('trailing newline / whitespace does not break parsing', () {
      final buffer = '${jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH)}\n  \t';
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
    });

    test('malformed JSON -> null', () {
      expect(
        parseVaultChatCardMessage(
          '{"type":"vault_chat_card","card":',
        ),
        isNull,
      );
    });
  });

  group('parseVaultChatCardMessage — streaming split', () {


    test('two-chunk arrival: first chunk half + second chunk half '
        '(concatenated buffer)', () {
      final full = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final half = full.length ~/ 2;
      final chunk1 = full.substring(0, half);
      final chunk2 = full.substring(half);


      final buffer1 = chunk1;
      expect(parseVaultChatCardMessage(buffer1), isNull);


      final buffer2 = chunk1 + chunk2;
      final msg = parseVaultChatCardMessage(buffer2);
      expect(msg, isNotNull);
      expect(msg!.kind, ChatMessage.kVaultChatCard);
    });

    test('three-chunk arrival with tiny final chunk', () {
      final full = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final c1 = full.substring(0, full.length ~/ 3);
      final c2 = full.substring(full.length ~/ 3, 2 * full.length ~/ 3);
      final c3 = full.substring(2 * full.length ~/ 3);
      final assembled = c1 + c2 + c3;
      final msg = parseVaultChatCardMessage(assembled);
      expect(msg, isNotNull);
    });

    test('non-streaming (single-chunk) case', () {

      final buffer = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull);
      expect(msg!.kind, ChatMessage.kVaultChatCard);
    });
  });

  group('ChatMessage.isCard reads kVaultChatCard as a card', () {
    test('a parsed message reports isCard=true and NOT isUser', () {
      final buffer = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msg = parseVaultChatCardMessage(buffer)!;
      expect(msg.isCard, isTrue);
      expect(msg.isAssistant, isTrue);
      expect(msg.isUser, isFalse);
    });
  });

  group('VaultChatCardView renders the masked login card', () {
    Widget wrap(Widget child) => MaterialApp(
          localizationsDelegates: _testL10nDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: SingleChildScrollView(child: child)),
        );

    Future<void> _pumpVaultChatCardEnvelope(
      WidgetTester tester,
      Map<String, dynamic> envelope,
    ) async {
      final buffer = jsonEncode(envelope);
      final msg = parseVaultChatCardMessage(buffer);
      expect(msg, isNotNull, reason:
          'parser must return a card message for known envelopes');
      final card = msg!.payload!['card'] as Map<String, dynamic>;
      final response = vcr.VaultChatResponse.fromJson({
        'intent': msg.payload!['intent'] ?? '',
        'card':   card,
      });
      await tester.pumpWidget(wrap(VaultChatCardView(response: response)));
      await tester.pump();
    }

    testWidgets('single login match renders as a login card '
        '(not raw JSON)', (tester) async {
      await _pumpVaultChatCardEnvelope(
        tester, _PROD_ENVELOPE_LOGIN_SEARCH,
      );

      expect(find.byKey(const Key(kVcrCardKeyLogin)), findsOneWidget);


      final rawJsonFragment = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      expect(find.text(rawJsonFragment), findsNothing);
      expect(find.textContaining('"cardType"'), findsNothing);
      expect(find.textContaining('"schema"'), findsNothing);
    });

    testWidgets('multi-match login list renders as a tappable '
        'selector — rows carry a chevron affordance, not a password '
        'dot cluster (2026-07-12 product decision)',
        (tester) async {
      await _pumpVaultChatCardEnvelope(
        tester, _PROD_ENVELOPE_LOGIN_MULTI,
      );
      expect(find.byKey(const Key(kVcrCardKeyLogin)), findsOneWidget);
      // Each row is a real selector (has chevron_right), NOT a static
      // masked-dot row that hints at a password without letting the
      // user drill in. Selecting a row re-issues a targeted search
      // that resolves to the full editable login detail card.
      expect(find.byIcon(Icons.chevron_right), findsWidgets);
    });

    testWidgets('generated-login card renders', (tester) async {
      await _pumpVaultChatCardEnvelope(
        tester, _PROD_ENVELOPE_GENERATED_LOGIN,
      );
      expect(
        find.byKey(const Key(kVcrCardKeyGeneratedLogin)),
        findsOneWidget,
      );
    });

    testWidgets('storage card renders', (tester) async {
      await _pumpVaultChatCardEnvelope(
        tester, _PROD_ENVELOPE_STORAGE,
      );
      expect(
        find.byKey(const Key(kVcrCardKeyStorageUsage)),
        findsOneWidget,
      );
    });

    testWidgets('file result card renders', (tester) async {
      await _pumpVaultChatCardEnvelope(
        tester, _PROD_ENVELOPE_FILE_RESULT,
      );
      expect(
        find.byKey(const Key(kVcrCardKeyFileResult)),
        findsOneWidget,
      );
    });

    testWidgets('unknown card renders the unrecognized-card widget '
        '(NEVER raw JSON)', (tester) async {
      await _pumpVaultChatCardEnvelope(
        tester, _UNKNOWN_CARD,
      );
      expect(
        find.byKey(const Key(kVcrCardKeyUnrecognized)),
        findsOneWidget,
      );

      expect(find.textContaining('vault_chat_card'), findsNothing);
      expect(find.textContaining('"cardType"'), findsNothing);
    });
  });

  group('Password / secret invariants at the widget layer', () {
    Widget wrap(Widget child) => MaterialApp(
          localizationsDelegates: _testL10nDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: SingleChildScrollView(child: child)),
        );

    testWidgets('login card never renders a plaintext password '
        'string (backend does not send one; widget must not '
        'synthesise one either)', (tester) async {
      final buffer = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msg = parseVaultChatCardMessage(buffer)!;
      final card = msg.payload!['card'] as Map<String, dynamic>;
      final response = vcr.VaultChatResponse.fromJson({
        'intent': msg.payload!['intent'] ?? '',
        'card':   card,
      });
      await tester.pumpWidget(wrap(VaultChatCardView(response: response)));
      await tester.pump();

      for (final banned in [
        'password',
        'passphrase',
        'seed',
        'mnemonic',
        'private key',
        'api key',
      ]) {

        expect(
          find.textContaining(RegExp(banned, caseSensitive: false)),
          findsNothing,
          reason: 'login card must not surface $banned',
        );
      }
    });
  });

  group('Source-guard: main.dart uses the extracted parser', () {


    test('lib/main.dart imports vault_chat_stream_parser', () {
      final src =
          _readMainDart();
      expect(
        src,
        contains(
          "import 'services/vault_chat_stream_parser.dart' as vcs_parser;",
        ),
        reason: 'main.dart must import the extracted parser',
      );
    });

    test('_tryParseAssistantStructuredMessage calls '
        'parseVaultChatCardMessage first', () {
      final src = _readMainDart();
      expect(
        src,
        contains('vcs_parser.parseVaultChatCardMessage(text)'),
        reason:
            'main.dart must delegate to the tested parser BEFORE the '
            'existing type dispatch — the parser is the source of '
            'truth for vault_chat_card',
      );
    });

    test('the fallback Map<dynamic,dynamic> cast keeps parsing '
        'alive on Dart web edge cases', () {
      final src = _readMainDart();
      expect(
        src,
        contains(
          'decodedRaw.map<String, dynamic>(',
        ),
        reason: 'main.dart must handle Map<dynamic,dynamic> too',
      );
    });
  });









  group('Race guard: chunk callback must parse before finalizing the '
        'assistant message', () {
    String _mainSrc() => _readMainDart();

    test('main.dart uses await for over the chat stream (no .listen '
        'race between async decrypt and stream done)', () {
      final src = _mainSrc();


      expect(
        src.contains('await for (final encryptedChunk in stream)'),
        isTrue,
        reason: 'production chat handler must consume the chat '
                'stream with `await for`, not `.listen((chunk) async '
                '{...})`. The .listen form races: the callback\'s '
                'decrypt Future runs concurrently with the stream\'s '
                'done event, so buffer updates from the last chunk '
                'can arrive AFTER _tryParseAssistantStructuredMessage '
                'has already run against an empty buffer.',
      );


      expect(
        src.contains('await sub.asFuture<void>()'),
        isFalse,
        reason: 'the racy asFuture pattern must be removed from every '
                'chat handler that expects a structured card',
      );
    });

    test('main.dart parses+replaces INSIDE the chunk loop (belt), '
        'and again after the loop (suspenders)', () {
      final src = _mainSrc();




      expect(
        RegExp(r'final\s+structuredNow\s*=\s*\n\s*_tryParseAssistantStructuredMessage\(buffer\);')
            .hasMatch(src),
        isTrue,
        reason: 'the chunk-level parse must run so a completed JSON '
                'envelope becomes a card in the SAME setState that '
                'wrote the buffer — never leaving a raw-JSON text '
                'message visible to the user',
      );
      expect(
        RegExp(r"final\s+_Msg\s+replacement\s*=\s*structuredNow\s*\?\?\s*\n\s*_Msg\('assistant',\s*buffer\);")
            .hasMatch(src),
        isTrue,
        reason: 'the placeholder committed to msgs[i] must ALREADY '
                'be the structured card when the JSON is complete',
      );

      expect(
        src.contains('if (assistantIndex != null && buffer.isNotEmpty) {'),
        isTrue,
        reason: 'the post-loop parse must ALSO run, so any '
                'edge-case chunking that missed the intra-chunk '
                'parse is caught before returning',
      );


      final structuredNowMatches =
          RegExp(r'\bstructuredNow\b').allMatches(src).length;
      expect(
        structuredNowMatches, greaterThanOrEqualTo(4),
        reason:
            'both chatStream callsites (delete-confirm + main _send) '
            'must contain the belt: define structuredNow and use it '
            'in the replacement (≥ 2 * 2 = 4 references)',
      );
    });

    test('both chatStream callsites in main.dart are await-for '
        '(delete-confirm flow + main _send flow)', () {
      final src = _mainSrc();
      final awaitForCount = 'await for (final encryptedChunk in stream)'
          .allMatches(src)
          .length;
      expect(
        awaitForCount, greaterThanOrEqualTo(2),
        reason: 'BOTH chatStream flows (delete-confirm + _send) must '
                'use await for; otherwise one of them keeps the race',
      );

      expect(src.contains('.listen(\n      (encryptedChunk) async {'), isFalse);
      expect(src.contains('.listen(\n        (encryptedChunk) async {'), isFalse);
    });
  });




  group('Streamed vault_login_card assembles into a card BEFORE '
        'the widget builds — the exact production replay', () {




    Future<List<ChatMessage>> _simulateSendReceive({
      required List<String> chunks,
    }) async {
      final msgs = <ChatMessage>[];
      int? assistantIndex;
      var buffer = '';

      for (final chunk in chunks) {

        await Future<void>.delayed(Duration.zero);
        buffer += chunk;


        final structuredNow = parseVaultChatCardMessage(buffer);
        final ChatMessage replacement = structuredNow ??
            ChatMessage('assistant', buffer);

        if (assistantIndex == null) {
          msgs.add(replacement);
          assistantIndex = msgs.length - 1;
        } else {
          msgs[assistantIndex] = replacement;
        }
      }


      if (assistantIndex != null && buffer.isNotEmpty) {
        final structured = parseVaultChatCardMessage(buffer);
        if (structured != null) {
          msgs[assistantIndex] = structured;
        }
      }
      return msgs;
    }

    test('single-chunk arrival: state committed for the widget is '
        'a vault_chat_card, NEVER a text ChatMessage', () async {
      final full = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msgs = await _simulateSendReceive(chunks: [full]);

      expect(msgs, hasLength(1));
      expect(msgs.first.kind, ChatMessage.kVaultChatCard);
      expect(msgs.first.isCard, isTrue);
      expect(msgs.first.payload, isNotNull);


      expect(msgs.first.text, '');
    });

    test('two-chunk arrival: FINAL state is a card (fix eliminates '
        'the raw-text bubble the user was seeing in production)',
        () async {
      final full = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final half = full.length ~/ 2;
      final msgs = await _simulateSendReceive(chunks: [
        full.substring(0, half),
        full.substring(half),
      ]);

      expect(msgs, hasLength(1));
      expect(msgs.first.kind, ChatMessage.kVaultChatCard,
        reason: 'FINAL msg (after all chunks) must be a card — this '
                'is exactly the invariant that was broken by the '
                'race in the old .listen((chunk) async {...}) flow.',
      );
      expect(msgs.first.isCard, isTrue);
    });

    test('three-chunk arrival with tiny final chunk', () async {
      final full = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final chunks = [
        full.substring(0, full.length ~/ 3),
        full.substring(full.length ~/ 3, 2 * full.length ~/ 3),
        full.substring(2 * full.length ~/ 3),
      ];
      final msgs = await _simulateSendReceive(chunks: chunks);
      expect(msgs.first.kind, ChatMessage.kVaultChatCard);
    });

    test('empty message field on the envelope does NOT downgrade '
        'the card back to text', () async {
      expect(_PROD_ENVELOPE_LOGIN_SEARCH['message'], '');
      final full = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msgs = await _simulateSendReceive(chunks: [full]);
      expect(msgs.first.text, '');
      expect(msgs.first.kind, ChatMessage.kVaultChatCard);
    });

    test('locale "pt" does not break intra-chunk parse', () async {
      final env = Map<String, dynamic>.from(_PROD_ENVELOPE_LOGIN_SEARCH);
      env['locale'] = 'pt';
      final msgs = await _simulateSendReceive(chunks: [jsonEncode(env)]);
      expect(msgs.first.kind, ChatMessage.kVaultChatCard);
    });




    test('adversarial race: if _tryParseAssistant were called BEFORE '
        'the chunk callback fired, we would leave a raw-text bubble. '
        'The intra-chunk parse guarantees the assistantIndex slot is '
        'ALREADY a card when the widget builds.', () async {
      final full = jsonEncode(_PROD_ENVELOPE_LOGIN_SEARCH);
      final msgs = await _simulateSendReceive(chunks: [full]);


      expect(msgs.first.kind, isNot('text'));

      expect(msgs.first.kind, ChatMessage.kVaultChatCard);
    });
  });
}


String _readMainDart() {

  try {
    final f = File('lib/main.dart');
    return f.readAsStringSync();
  } catch (_) {
    return '';
  }
}


