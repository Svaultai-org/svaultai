// Regression tests for the 2026-07-22 chat typing-indicator
// identity fix, plus the 2026-07-22 correction that removed the
// hardcoded assistant-name constant.
//
// Contract:
//
//   * The typing indicator label is composed from the user-chosen
//     vault name (``AppState.vaultName``), which is dynamic per
//     session.
//   * A user whose vault is named "Brain" sees
//     "Brain is thinking...".
//   * A user whose vault is named "My Safe" sees
//     "My Safe is thinking...".
//   * A user whose vault is named "Family Vault" sees
//     "Family Vault is thinking...".
//   * The typing indicator MUST NEVER be composed from the owner's
//     display name (that was the incident bug — "Chosen is
//     thinking..." for a user named Chosen).
//   * There is NO ``kAssistantName`` / ``vault_identity.dart`` /
//     hardcoded assistant-name literal anywhere in production
//     code. The intermediate hardcode has been removed.

library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/ui/chat/typing_pulse.dart';


/// Example (owner display name, vault name) pairs used only in
/// this test file to prove the label composition is dynamic. No
/// production file may hardcode any of these strings — see the
/// backend companion test
/// ``TestNoHardcodedAssistantIdentityInProduction`` in
/// ``vault_ai_backend/test_chat_e2e_attachment_and_identity_2026_07_22.py``.
const List<(String owner, String vaultName)> _kExamples = [
  ('Chosen', 'Brain'),
  ('Sarah', 'My Safe'),
  ('David', 'Family Vault'),
  ('Yuki', '会計金庫'),
  ('Ada', "Ada's Notes"),
];


void main() {
  group('main.dart typing-indicator wiring', () {
    late String mainDartSrc;

    setUpAll(() {
      mainDartSrc = File('lib/main.dart').readAsStringSync();
    });

    test('ChatMessageList vaultName binds to app.vaultName '
        '(never app.displayName, never a hardcoded literal)', () {
      expect(
        mainDartSrc.contains('vaultName: app.vaultName,'),
        isTrue,
        reason:
            'main.dart must pass app.vaultName as the '
            'ChatMessageList vaultName. This is the per-session '
            'vault identity, dynamic per user.',
      );
      expect(
        mainDartSrc.contains('vaultName: app.displayName,'),
        isFalse,
        reason:
            "main.dart must NOT bind vaultName to app.displayName "
            "— that was the incident bug ('Chosen is thinking...' "
            "for a user named Chosen).",
      );
      expect(
        mainDartSrc.contains('vaultName: kAssistantName,'),
        isFalse,
        reason:
            'main.dart must NOT reference the removed '
            'kAssistantName constant. The intermediate hardcode '
            'was rolled back in the 2026-07-22 correction.',
      );
      // No hardcoded literals for any of our example vault names.
      for (final (_, vault) in _kExamples) {
        expect(
          mainDartSrc.contains("vaultName: '$vault',"),
          isFalse,
          reason:
              "main.dart must not pass '$vault' as a hardcoded "
              "vault-name literal.",
        );
      }
    });

    test('main.dart does not import the removed vault_identity.dart',
        () {
      expect(
        mainDartSrc.contains("import 'vault_identity.dart';"),
        isFalse,
        reason:
            'The vault_identity.dart file (which briefly held '
            'kAssistantName = Brain) has been removed.',
      );
    });

    test('lib/vault_identity.dart file does not exist', () {
      expect(
        File('lib/vault_identity.dart').existsSync(),
        isFalse,
        reason:
            'lib/vault_identity.dart must not exist. The '
            'intermediate hardcode was rolled back — the '
            'assistant identity is per-vault, dynamic.',
      );
    });
  });

  group('TypingPulse renders whatever label is passed', () {
    for (final (owner, vault) in _kExamples) {
      testWidgets(
        'renders "$vault is thinking..." for vault named "$vault" '
        '(owner: "$owner")',
        (WidgetTester tester) async {
          final label = '$vault is thinking...';
          await tester.pumpWidget(
            MaterialApp(
              home: Scaffold(
                body: TypingPulse(label: label),
              ),
            ),
          );
          expect(find.text(label), findsOneWidget,
              reason: 'TypingPulse must render the composed label '
                  'verbatim.');
          // Reflexive negative — the OWNER'S display name must
          // NEVER appear in the typing indicator (that was the
          // incident bug).
          final ownerLabel = '$owner is thinking...';
          if (ownerLabel != label) {
            expect(find.text(ownerLabel), findsNothing,
                reason: "The owner's display name must never "
                    "appear as the typing indicator label.");
          }
        },
      );
    }

    testWidgets(
      'falls back to "SVaultAI is thinking..." literal when label '
      'is null (defensive fallback)',
      (WidgetTester tester) async {
        // Preserved historical fallback: if a caller ever passes
        // null (e.g. app.vaultName not yet populated), the widget
        // renders the neutral "SVaultAI is thinking..." literal
        // rather than crashing.
        await tester.pumpWidget(
          const MaterialApp(
            home: Scaffold(body: TypingPulse()),
          ),
        );
        expect(find.text('SVaultAI is thinking...'), findsOneWidget);
      },
    );
  });
}
