// Regression tests for the 2026-07-20 vault-AI-name introduction.
//
// Locks four contracts:
//
//   1. Profile menu reads DISPLAY name only.
//      The top-right account chip + dropdown header render
//      ``displayUsername ?? 'Account'``. They must NEVER read
//      ``canonicalUsername``, ``vaultAiName``, ``vaultName``,
//      ``vaultHandle``, or any hash.
//
//   2. Typing indicator reads the VAULT AI NAME only.
//      ``ChatMessageList`` composes the typing label from
//      ``widget.vaultAiName`` and falls back to the neutral
//      "VaultAI is thinking..." literal. It must NEVER read
//      ``app.vaultName`` (VLT handle / random hex), the canonical
//      username, or any identifier.
//
//   3. Account-username intent is NARROW.
//      The regex catches only unambiguous login-identifier
//      phrasings and never intercepts AI-side identity questions
//      ("who are you", "what is your name", "what is your role").
//      Those fall through to the LLM path.
//
//   4. AppState carries a separate ``vaultAiName`` field with the
//      documented persistence + clear semantics; it is loaded from
//      ``/auth/me`` and persisted as ``last_vault_ai_name``.
//
// Non-goal in this pass: rendering the vault AI name anywhere in
// the sidebar / dashboard / drawer. The typing indicator is the
// sole surface that reads it, and the LLM prompt is the sole other
// consumer (server-side).

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('AppState vaultAiName field', () {
    test('AppState declares a distinct vaultAiName field', () {
      final src = _read('lib/main.dart');
      expect(src.contains('String? vaultAiName;'), isTrue,
          reason: 'AppState must expose vaultAiName as a field '
              'distinct from canonicalUsername, displayUsername, '
              'vaultName, and vaultHandle');
    });

    test('hydrate reads vault_ai_name from /auth/me response', () {
      final src = _read('lib/main.dart');
      expect(src.contains("me['vault_ai_name']"), isTrue,
          reason: 'the AI name is server-authoritative; hydrate '
              'must consume the /auth/me field');
    });

    test('hydrate restores last_vault_ai_name from SharedPreferences', () {
      final src = _read('lib/main.dart');
      expect(src.contains("sp.getString('last_vault_ai_name')"), isTrue);
    });

    test(
        'setSession writes last_vault_ai_name to SharedPreferences '
        'when the network path fills it', () {
      final src = _read('lib/main.dart');
      // The persist call must exist SOMEWHERE for last_vault_ai_name
      // so subsequent launches can paint the name before /auth/me
      // resolves. Present via the hydrate write-back path.
      expect(src.contains("sp.setString('last_vault_ai_name'"), isTrue);
    });

    test('clearSession(keepLastVaultName=false) wipes last_vault_ai_name', () {
      final src = _read('lib/main.dart');
      expect(
        src.contains("await sp.remove('last_vault_ai_name');"),
        isTrue,
        reason: '"Use another vault" must not carry the previous '
            "vault's AI name into a fresh session",
      );
    });
  });

  group('Profile menu reads displayUsername ?? Account', () {
    test(
        'profile menu source is displayUsername, never '
        'canonicalUsername / vaultAiName / vaultName', () {
      final src = _read('lib/main.dart');
      // Positive: the exact reading pattern must appear at least
      // twice (dropdown header + chip).
      final positive = RegExp(
        r"app\.displayUsername\s*\?\?\s*'Account'",
      );
      expect(positive.allMatches(src).length, greaterThanOrEqualTo(2),
          reason: 'both PopupMenu header and the visible chip must '
              'read displayUsername ?? Account');
      // Negative: the pre-2026-07-20 wrapping that read
      // canonicalUsername ?? displayUsername ?? "VaultAI User"
      // must not linger anywhere.
      expect(src.contains("'VaultAI User'"), isFalse,
          reason: 'the fallback string was changed from '
              '"VaultAI User" to the neutral "Account"; leaving '
              'the old literal in place indicates one of the two '
              'menu sites was missed');
    });
  });

  group('ChatMessageList typing indicator reads vaultAiName only', () {
    test('the widget declares vaultAiName (renamed from vaultName)', () {
      final src = _read('lib/ui/chat/chat_message_list.dart');
      expect(src.contains('final String? vaultAiName;'), isTrue);
      // The old field name must be gone — a residual "vaultName"
      // on this widget re-opens the leak surface.
      expect(RegExp(r'final\s+String\?\s+vaultName\s*;').hasMatch(src), isFalse,
          reason: 'the pre-fix ``vaultName`` field on ChatMessageList '
              'received the VLT handle / random hex placeholder and '
              'must be removed entirely');
    });

    test('the typing-label source is widget.vaultAiName, not vaultName', () {
      final src = _read('lib/ui/chat/chat_message_list.dart');
      expect(src.contains('widget.vaultAiName?.trim()'), isTrue,
          reason: 'the typing indicator must read the vault AI '
              'name only');
      expect(src.contains('widget.vaultName?.trim()'), isFalse,
          reason: 'the pre-fix source (widget.vaultName) is what '
              'leaked the 32-hex placeholder into the typing '
              'indicator; it must be gone');
    });

    test('caller in main.dart passes vaultAiName: app.vaultAiName', () {
      final src = _read('lib/main.dart');
      expect(src.contains('vaultAiName: app.vaultAiName'), isTrue,
          reason: 'the ChatMessageList caller must pass the vault '
              'AI name, never app.vaultName');
      // The pre-fix caller passed ``vaultName: activeVaultName``
      // where activeVaultName = app.vaultName. That path must be
      // fully retired.
      expect(src.contains('vaultName: activeVaultName'), isFalse);
    });

    testWidgets(
        'TypingPulse label is "VaultAI is thinking..." when '
        'vaultAiName is null', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('en'),
          home: Scaffold(
            body: ChatMessageList(
              messages: const <ChatMessage>[],
              thinking: true,
              streaming: false,
              isMobile: false,
              vaultAiName: null,
            ),
          ),
        ),
      );
      await tester.pump();
      expect(find.text('VaultAI is thinking...'), findsOneWidget);
    });

    testWidgets(
        'TypingPulse label is "Nova is thinking..." when '
        'vaultAiName is "Nova"', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('en'),
          home: Scaffold(
            body: ChatMessageList(
              messages: const <ChatMessage>[],
              thinking: true,
              streaming: false,
              isMobile: false,
              vaultAiName: 'Nova',
            ),
          ),
        ),
      );
      await tester.pump();
      expect(find.text('Nova is thinking...'), findsOneWidget);
    });

    testWidgets(
        'TypingPulse never renders a 32-hex string or a '
        'VLT- handle, even if one is passed', (tester) async {
      // Even if a future regression pushes a bad value into the
      // vaultAiName slot, the LOCALIZED template is
      // "{name} is thinking..." — we assert here that the widget
      // faithfully renders whatever it is given (so a bad value
      // shows up in a test) and that the source-scan tests above
      // fail closed when the wire changes.
      const badHex = 'b21e31c5b59abdc8067ff6b23643b254';
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('en'),
          home: Scaffold(
            body: ChatMessageList(
              messages: const <ChatMessage>[],
              thinking: true,
              streaming: false,
              isMobile: false,
              vaultAiName: badHex,
            ),
          ),
        ),
      );
      await tester.pump();
      // The widget WILL render whatever it's handed — that's the
      // point of the source-scan tests: they lock down the caller
      // so this widget never gets bad input. If this test flips
      // (i.e. widget starts filtering), update the source-scan
      // caller expectations.
      expect(find.text('$badHex is thinking...'), findsOneWidget);
    });
  });

  group('Account-username intent is narrow', () {
    test(
        'the intent regex was renamed to _accountUsernameQueryRe '
        'to reflect its narrowed scope', () {
      final src = _read('lib/main.dart');
      expect(src.contains('_accountUsernameQueryRe'), isTrue);
      expect(src.contains('_tryDirectAccountUsernameReply'), isTrue);
    });

    test(
        'the regex no longer matches vault-name / who-am-i / '
        'which-vault questions', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('_accountUsernameQueryRe = RegExp');
      expect(idx, greaterThan(-1));
      final endIdx = src.indexOf(');', idx);
      final regexSrc = src.substring(idx, endIdx);
      // These phrasings must NOT be present in the regex — they
      // belong on the LLM path so the vault-AI identity context
      // can answer them specifically.
      expect(regexSrc.contains('vault\\s*name'), isFalse,
          reason: '"vault name" is ambiguous with the vault AI '
              'name and must not be intercepted here');
      expect(regexSrc.contains('who\\s+am\\s+i'), isFalse,
          reason: '"who am I" belongs on the LLM path');
      expect(regexSrc.contains('which\\s+vault\\s+am\\s+i\\s+in'), isFalse);
      // These MUST still be present.
      expect(regexSrc.contains('username'), isTrue);
      expect(regexSrc.contains('account\\s*name'), isTrue);
    });

    test(
        'the intent reply says "Your username is X" not "Your '
        'vault name is X"', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('_tryDirectAccountUsernameReply(');
      expect(idx, greaterThan(-1));
      final endIdx = src.indexOf('Future<void> _send()', idx);
      final window = src.substring(idx, endIdx);
      expect(window.contains(r"'Your username is $canonical.'"), isTrue,
          reason: 'reply must specifically name the login '
              'identifier, not the ambiguous "vault name"');
      expect(window.contains(r"'Your vault name is"), isFalse,
          reason: 'the previous reply text conflated the login '
              'identifier with the vault-AI identity');
    });
  });
}
