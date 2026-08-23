// Regression tests for the 2026-07-20 vault_name unification.
//
// Product model (confirmed):
//   vault_name    User-chosen identity used for signing in AND as
//                 the vault AI's name. ONE string, ONE meaning.
//   display_name  Optional human owner's visible name.
//   vault_id      Internal opaque identifier.
//
// The typing indicator, LLM prompt, and any "what is your name"
// answer all use vault_name. The profile menu uses displayName.
// Internal handles/hashes/IDs are never shown or reused.

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/ui/chat/chat_message_list.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

String _read(String path) => File(path).readAsStringSync();

void main() {
  group('AppState identity fields — one vault_name, one display_name', () {
    test(
        'AppState declares vaultName + displayName + vaultHandle + '
        'vaultId; the retired vaultAiName and canonicalUsername fields '
        'are gone', () {
      final src = _read('lib/main.dart');
      // Positive: the four fields the corrected product model uses.
      expect(RegExp(r'String\?\s+get\s+vaultName\b').hasMatch(src), isTrue);
      expect(src.contains('String? displayName;'), isTrue);
      expect(src.contains('String? vaultHandle;'), isTrue);
      expect(src.contains('String? vaultId;'), isTrue);
      // Negative: retired interim symbols must be gone.
      expect(src.contains('String? vaultAiName;'), isFalse,
          reason: 'vault_ai_name was folded back into vault_name');
      expect(src.contains('String? canonicalUsername;'), isFalse,
          reason: 'canonical_username is not a separate product concept');
      expect(src.contains('String? displayUsername;'), isFalse,
          reason: 'displayUsername was renamed to displayName');
    });

    test(
        'hydrate reads /auth/me\'s vault_name and display_username; '
        'NativeSecureStore keys migrate from legacy SharedPreferences', () {
      final src = _read('lib/main.dart');
      // /auth/me consumption
      expect(src.contains("me['vault_name']"), isTrue);
      expect(src.contains("me['display_username']"), isTrue,
          reason: 'backend /auth/me still returns display_username '
              'for legacy vaults; frontend field is displayName');
      // Native secure storage is authoritative on Android; legacy
      // SharedPreferences keys remain readable as one-time fallbacks
      // so existing users' typed names are preserved.
      expect(
          src.contains(
              "NativeSecureStore.readString('last_vault_name')"),
          isTrue);
      expect(src.contains("sp.getString('last_canonical_username')"), isTrue,
          reason: 'legacy key must be readable as a one-time fallback '
              'so existing users\' typed names are preserved');
      expect(
          src.contains(
              "NativeSecureStore.readString('last_display_name')"),
          isTrue);
      expect(src.contains("sp.getString('last_display_username')"), isTrue,
          reason: 'legacy display key fallback');
    });

    test(
        'clearSession(keepLastVaultName=false) wipes the new keys AND '
        'the legacy keys (defense in depth)', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('Future<void> clearSession(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 5000).clamp(0, src.length));
      expect(
          window.contains(
              "NativeSecureStore.deleteString('last_vault_name')"),
          isTrue);
      expect(
          window.contains(
              "NativeSecureStore.deleteString('last_display_name')"),
          isTrue);
      expect(
          window.contains(
              "NativeSecureStore.deleteString('last_vault_handle')"),
          isTrue);
      expect(window.contains("sp.remove('last_display_username')"), isTrue);
      expect(window.contains("sp.remove('last_canonical_username')"), isTrue);
      expect(window.contains("sp.remove('last_vault_ai_name')"), isTrue);
    });

    test(
        'setSession accepts vaultNameValue + displayNameValue + '
        'vaultHandleValue; the retired canonicalUsernameValue param is '
        'gone', () {
      final src = _read('lib/main.dart');
      final idx = src.indexOf('Future<void> setSession(');
      expect(idx, greaterThan(-1));
      final window = src.substring(idx, (idx + 2500).clamp(0, src.length));
      expect(window.contains('required String vaultNameValue'), isTrue);
      expect(window.contains('String? displayNameValue'), isTrue);
      expect(window.contains('String? vaultHandleValue'), isTrue);
      expect(window.contains('canonicalUsernameValue'), isFalse);
      expect(window.contains('displayUsernameValue'), isFalse);
    });
  });

  group('Profile menu = displayName only', () {
    test(
        'the top-right profile menu reads displayName ?? "Account"; '
        'never vaultName, vaultHandle, canonicalUsername, vaultAiName', () {
      final src = _read('lib/main.dart');
      final re = RegExp(r"app\.displayName\s*\?\?\s*'Account'");
      expect(re.allMatches(src).length, greaterThanOrEqualTo(2),
          reason: 'both PopupMenu header and account chip must read '
              'displayName with the neutral "Account" fallback');
      expect(src.contains("'SVaultAI User'"), isFalse);
    });
  });

  group('Typing indicator = vaultName only', () {
    test('ChatMessageList declares vaultName (product name)', () {
      final src = _read('lib/ui/chat/chat_message_list.dart');
      expect(src.contains('final String? vaultName;'), isTrue);
      // The interim edf366b field name must be gone.
      expect(src.contains('final String? vaultAiName;'), isFalse);
    });

    test('the typing-label source is widget.vaultName?.trim()', () {
      final src = _read('lib/ui/chat/chat_message_list.dart');
      expect(src.contains('widget.vaultName?.trim()'), isTrue);
      expect(src.contains('widget.vaultAiName?.trim()'), isFalse);
    });

    test(
        'main.dart caller passes vaultName: app.vaultName '
        '(not vaultAiName, not app.vaultHandle)', () {
      final src = _read('lib/main.dart');
      expect(src.contains('vaultName: app.vaultName'), isTrue);
      expect(src.contains('vaultAiName: app.vaultName'), isFalse,
          reason: 'the interim edf366b caller pattern must be gone');
    });

    testWidgets(
        'TypingPulse renders "SVaultAI is thinking..." when '
        'vaultName is null', (tester) async {
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
              vaultName: null,
            ),
          ),
        ),
      );
      await tester.pump();
      expect(find.text('SVaultAI is thinking...'), findsOneWidget);
    });

    testWidgets(
        'TypingPulse renders "Nova is thinking..." when '
        'vaultName is "Nova"', (tester) async {
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
              vaultName: 'Nova',
            ),
          ),
        ),
      );
      await tester.pump();
      expect(find.text('Nova is thinking...'), findsOneWidget);
    });

    testWidgets('empty streaming placeholder does not render an ellipsis bubble',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          locale: const Locale('en'),
          home: Scaffold(
            body: ChatMessageList(
              messages: <ChatMessage>[
                ChatMessage(
                  'assistant',
                  '',
                  requestId: 'request-under-test',
                ),
              ],
              thinking: true,
              streaming: true,
              isMobile: true,
              vaultName: 'Nova',
            ),
          ),
        ),
      );
      await tester.pump();
      expect(find.text('...'), findsNothing);
      expect(find.text('Nova is thinking...'), findsOneWidget);
    });
  });

  group('Wire protocol carries vault_name for register + login backfill', () {
    test(
        'registerVault takes vaultName as its required param and sends '
        'it as the ``vault_name`` request field', () {
      final src = _read('lib/services/zk_auth_service.dart');
      final idx = src.indexOf('Future<RegisterResult> registerVault(');
      expect(idx, greaterThan(-1));
      final endIdx = src.indexOf('Future<LoginResult> loginVault(', idx);
      final window = src.substring(idx, endIdx);
      expect(window.contains('required String vaultName'), isTrue,
          reason: 'the retired ``username`` param name is gone; '
              'the caller passes the user-typed vault name');
      expect(window.contains("'vault_name': vaultName"), isTrue,
          reason: 'the vault name is sent in the register-finalize '
              'body so the server can store it authoritatively');
    });

    test(
        'loginVault takes vaultName as an optional param and sends '
        'it on login-finalize for opportunistic backfill', () {
      final src = _read('lib/services/zk_auth_service.dart');
      final idx = src.indexOf('Future<LoginResult> loginVault(');
      expect(idx, greaterThan(-1));
      final endIdx = src.indexOf('/// Transparent legacy adoption', idx);
      final window = src.substring(idx, endIdx);
      expect(window.contains('String? vaultName'), isTrue);
      // The backfill body carries vault_name on login-finalize.
      expect(window.contains("'vault_name': vaultName"), isTrue);
    });

    test('LoginResult carries the SERVER-authoritative vaultName', () {
      final src = _read('lib/services/zk_auth_service.dart');
      final classIdx = src.indexOf('class LoginResult');
      final endIdx = src.indexOf('}', classIdx);
      final window = src.substring(classIdx, endIdx);
      expect(window.contains('final String? vaultName;'), isTrue,
          reason: 'the login-finalize response now returns vault_name '
              'so the client can populate app.vaultName with the '
              'server-authoritative value');
    });
  });

  group('No retired vault_ai_name symbols in the frontend surface', () {
    test(
        'no vaultAiName identifier remains in main.dart / '
        'chat_message_list.dart / api_client.dart / zk_auth_service.dart '
        '(back-compat cleanups of the retired SharedPreferences key '
        '``last_vault_ai_name`` are allowed)', () {
      // Retired Dart identifiers must not appear anywhere. The
      // string literal ``last_vault_ai_name`` may still appear in
      // main.dart for the back-compat sp.remove()/sp.getString()
      // cleanups documented in hydrate() + clearSession(); it
      // does NOT come with a matching Dart identifier.
      const forbiddenIdentifiers = ['vaultAiName', 'VaultAiName'];
      for (final path in [
        'lib/main.dart',
        'lib/ui/chat/chat_message_list.dart',
        'lib/api_client.dart',
        'lib/services/zk_auth_service.dart',
      ]) {
        final src = _read(path);
        for (final id in forbiddenIdentifiers) {
          expect(src.contains(id), isFalse, reason: '$path :: $id');
        }
      }
    });

    test(
        'api_client exposes setVaultName (not setVaultAiName); '
        'endpoint is /vault/name (not /vault/ai-name)', () {
      final src = _read('lib/api_client.dart');
      expect(src.contains('Future<String?> setVaultName('), isTrue);
      expect(src.contains('setVaultAiName'), isFalse);
      expect(src.contains("'\$baseUrl/vault/name'"), isTrue);
      expect(src.contains("/vault/ai-name"), isFalse);
    });
  });
}
