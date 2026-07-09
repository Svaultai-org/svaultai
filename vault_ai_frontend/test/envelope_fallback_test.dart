

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

void main() {
  group('ChatMessage — new Phase 8 kinds', () {
    test('exposes all four new kind constants', () {
      expect(ChatMessage.kVaultInventory, equals('vault_inventory'));
      expect(ChatMessage.kTravelReadiness, equals('travel_readiness'));
      expect(ChatMessage.kCredentialFiles, equals('credential_files'));
      expect(ChatMessage.kRelatedFiles, equals('related_files'));
    });

    test('isCard is true for every new kind', () {
      for (final kind in [
        ChatMessage.kVaultInventory,
        ChatMessage.kTravelReadiness,
        ChatMessage.kCredentialFiles,
        ChatMessage.kRelatedFiles,
      ]) {
        final m = ChatMessage(
          'assistant',
          'x',
          kind: kind,
          payload: const <String, dynamic>{},
        );
        expect(m.isCard, isTrue, reason: 'kind=$kind must be a card');
      }
    });
  });

  group('Parser fallback', () {
    test('main.dart still falls back to message text for unknown envelope',
        () async {
      final src = await File('lib/main.dart').readAsString();
      
      
      expect(
        src,
        contains("fallbackMessage = decoded['message']"),
        reason:
            'unknown envelope must still surface ``message`` as text — '
            'never dump raw JSON into chat',
      );
    });
  });

  group('ChatBubble switch', () {
    test('chat_bubble.dart has a default branch', () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      
      
      expect(src, contains('default:'));
      expect(src, contains('SizedBox.shrink()'));
    });

    test('chat_bubble.dart routes all four Phase 8 kinds', () async {
      final src = await File('lib/ui/chat/chat_bubble.dart').readAsString();
      for (final kindRef in [
        'ChatMessage.kVaultInventory',
        'ChatMessage.kTravelReadiness',
        'ChatMessage.kCredentialFiles',
        'ChatMessage.kRelatedFiles',
      ]) {
        expect(
          src,
          contains(kindRef),
          reason: '$kindRef must be wired in chat_bubble.dart',
        );
      }
    });
  });
}
