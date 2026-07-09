

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/ask_brain_handoff.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';

void main() {
  group('askBrainUserPromptLabel', () {
    test('uses fileName when no saved_name', () {
      expect(
        askBrainUserPromptLabel(fileName: 'fema application.pdf'),
        'Show me fema application.pdf',
      );
    });

    test('prefers saved_name over fileName', () {
      expect(
        askBrainUserPromptLabel(
          fileName: 'abcd1234.pdf',
          savedName: 'FEMA application',
        ),
        'Show me FEMA application',
      );
    });

    test('falls back to fileName when saved_name is blank', () {
      expect(
        askBrainUserPromptLabel(
          fileName: 'encrypt.py',
          savedName: '   ',
        ),
        'Show me encrypt.py',
      );
    });
  });

  group('buildAskBrainHandoff', () {
    test('produces a user bubble naming the file', () {
      final msgs = buildAskBrainHandoff(
        fileId: 'file-abc',
        fileName: 'fema application.pdf',
      );
      final userBubble = msgs.firstWhere((m) => m.isUser);
      expect(userBubble.text, 'Show me fema application.pdf');
    });

    test('produces an assistant vault_file card keyed by file_id', () {
      final msgs = buildAskBrainHandoff(
        fileId: 'file-abc',
        fileName: 'fema application.pdf',
        mimeType: 'application/pdf',
      );
      final card = msgs.firstWhere((m) => m.isAssistant);
      expect(card.kind, ChatMessage.kVaultFile);
      expect(card.fileId, 'file-abc');
      expect(card.fileName, 'fema application.pdf');
      expect(card.mimeType, 'application/pdf');
    });

    test('threads relative_path / asset_type / saved_name / size into payload',
        () {
      final msgs = buildAskBrainHandoff(
        fileId: 'file-abc',
        fileName: 'abcd1234.pdf',
        savedName: 'FEMA application',
        mimeType: 'application/pdf',
        assetType: 'file',
        relativePath: 'Documents/FEMA/abcd1234.pdf',
        sizeBytes: 2048,
      );
      final card = msgs.firstWhere((m) => m.isAssistant);
      final p = card.payload!;
      expect(p['saved_name'], 'FEMA application');
      expect(p['relative_path'], 'Documents/FEMA/abcd1234.pdf');
      expect(p['asset_type'], 'file');
      expect(p['size_bytes'], 2048);
    });

    test('uses saved_name as the visible label when present', () {
      final msgs = buildAskBrainHandoff(
        fileId: 'file-abc',
        fileName: 'abcd1234.pdf',
        savedName: 'FEMA application',
      );
      final userBubble = msgs.firstWhere((m) => m.isUser);
      expect(userBubble.text, 'Show me FEMA application');
    });

    test('omits saved_name from payload when blank', () {
      final msgs = buildAskBrainHandoff(
        fileId: 'file-abc',
        fileName: 'encrypt.py',
        savedName: '',
        relativePath: '',
      );
      final card = msgs.firstWhere((m) => m.isAssistant);
      
      if (card.payload != null) {
        expect(card.payload!.containsKey('saved_name'), isFalse);
        expect(card.payload!.containsKey('relative_path'), isFalse);
      }
    });

    test('never produces a generic "Show me my file from Vault" string',
        () {
      final msgs = buildAskBrainHandoff(
        fileId: 'file-abc',
        fileName: 'fema application.pdf',
        savedName: 'FEMA application',
      );
      for (final m in msgs) {
        expect(
          m.text,
          isNot(contains('my file from')),
          reason: 'Bug 1: hand-off must name the specific file, '
                  'never a generic "Show me my file from <Vault>" string',
        );
      }
    });

    test('hand-off contains exactly two messages: one user, one assistant',
        () {
      final msgs = buildAskBrainHandoff(
        fileId: 'file-abc',
        fileName: 'doculetter.html',
      );
      expect(msgs.length, 2);
      expect(msgs.where((m) => m.isUser).length, 1);
      expect(msgs.where((m) => m.isAssistant).length, 1);
    });

    test('user bubble carries the file label even when only fileName is set',
        () {
      final msgs = buildAskBrainHandoff(
        fileId: 'file-z',
        fileName: 'doculetter.html',
      );
      final userBubble = msgs.firstWhere((m) => m.isUser);
      expect(userBubble.text, contains('doculetter.html'));
    });
  });
}
