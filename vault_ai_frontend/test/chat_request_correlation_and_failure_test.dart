import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/ui/chat/chat_failure_localization.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/chat/chat_request_lifecycle.dart';

void main() {
  group('offline multilingual provider failure copy', () {
    final cases = <String, String>{
      'reply in Spanish': 'español',
      'reply in French': 'français',
      'reply in Tagalog': 'Tagalog',
      'reply in Filipino': 'Tagalog',
      'reply in Arabic': 'العربية',
      'reply in Somali': 'Af-Soomaali',
      'reply in Japanese': '日本語',
      'reply in Hindi': 'हिंदी',
      'reply in Swahili': 'Kiswahili',
      'reply in Persian': 'فارسی',
    };

    for (final entry in cases.entries) {
      test(entry.key, () {
        final copy = friendlyChatGenerationFailure(entry.key);
        expect(copy, contains(entry.value));
        expect(copy.toLowerCase(), isNot(contains('provider')));
        expect(copy.toLowerCase(), isNot(contains('billing')));
        expect(copy.toLowerCase(), isNot(contains('request id')));
      });
    }

    test('unknown language is safe and actionable', () {
      final copy = friendlyChatGenerationFailure('reply in Klingon');
      expect(copy, unknownLanguageFailure);
      expect(copy, contains('continue in English'));
      expect(copy, contains('try again'));
      expect(copy, contains('cancel'));
    });

    test('timeout copy is generic and never impersonates a vault', () {
      expect(chatTimeoutRecovery,
          'That took too long to finish. Please try again. Your vault was not changed by this failed request.');
      expect(chatTimeoutRecovery.toLowerCase(), isNot(contains('brain')));
      expect(chatTimeoutRecovery.toLowerCase(), isNot(contains('alex')));
      expect(chatTimeoutRecovery.toLowerCase(), isNot(contains('testy')));
    });
  });

  group('immutable turn correlation', () {
    ChatMessage user(String request) => ChatMessage(
          'user',
          'prompt',
          messageId: 'user_$request',
          requestId: request,
        );
    ChatMessage assistant(String request) => ChatMessage(
          'assistant',
          '',
          messageId: 'assistant_$request',
          requestId: request,
          replyToMessageId: 'user_$request',
        );

    test('out-of-order completion stays with originating user turn', () {
      final messages = <ChatMessage>[
        user('r1'),
        assistant('r1'),
        user('r2'),
        assistant('r2'),
      ];
      final r2 =
          messages.indexWhere((m) => m.requestId == 'r2' && m.isAssistant);
      messages[r2] = ChatMessage('assistant', 'second response')
          .withCorrelationFrom(messages[r2]);
      final r1 =
          messages.indexWhere((m) => m.requestId == 'r1' && m.isAssistant);
      messages[r1] = ChatMessage('assistant', 'first response')
          .withCorrelationFrom(messages[r1]);
      expect(messages[r1].replyToMessageId, 'user_r1');
      expect(messages[r2].replyToMessageId, 'user_r2');
      expect(messages[r1].text, 'first response');
      expect(messages[r2].text, 'second response');
    });

    test('replacement preserves immutable request and message IDs', () {
      final original = assistant('request-old');
      final replacement =
          ChatMessage('assistant', 'done').withCorrelationFrom(original);
      expect(replacement.messageId, original.messageId);
      expect(replacement.requestId, 'request-old');
      expect(replacement.replyToMessageId, 'user_request-old');
    });

    test('retry uses a new identity and cannot overwrite cancelled turn', () {
      final cancelled = assistant('request-1');
      final retry = assistant('request-2');
      expect(retry.requestId, isNot(cancelled.requestId));
      expect(retry.messageId, isNot(cancelled.messageId));
      expect(retry.replyToMessageId, isNot(cancelled.replyToMessageId));
    });
  });

  group('request lifecycle', () {
    test('runtime exposes safe iterator ownership and cleanup', () {
      final runtime = ChatRequestRuntime();
      final ticket = runtime.begin(nowMicros: 1);
      expect(runtime.hasActiveIterator, isFalse);
      final marker = Object();
      runtime.assignIterator(ticket.requestId, marker);
      expect(runtime.hasActiveIterator, isTrue);
      expect(runtime.activeRequestId, ticket.requestId);
      expect(runtime.takeIterator<Object>(), same(marker));
      expect(runtime.hasActiveIterator, isFalse);
      expect(runtime.activeRequestId, isNull);
    });

    test('unique IDs remain distinct at the same timestamp', () {
      final coordinator = ChatRequestCoordinator();
      final first = coordinator.begin(nowMicros: 42);
      final second = coordinator.begin(nowMicros: 42);
      expect(first.requestId, isNot(second.requestId));
      expect(first.assistantMessageId, isNot(second.assistantMessageId));
    });

    test('controlled out-of-order completions remain independently valid', () {
      final coordinator = ChatRequestCoordinator();
      final first = coordinator.begin(nowMicros: 1);
      final second = coordinator.begin(nowMicros: 2);
      coordinator.complete(second.requestId);
      expect(coordinator.acceptsEvents(second.requestId), isFalse);
      expect(coordinator.acceptsEvents(first.requestId), isTrue);
      coordinator.complete(first.requestId);
      expect(coordinator.acceptsEvents(first.requestId), isFalse);
    });

    test('late event after cancellation is rejected', () {
      final coordinator = ChatRequestCoordinator();
      final ticket = coordinator.begin(nowMicros: 1);
      coordinator.cancel(ticket.requestId);
      expect(coordinator.acceptsEvents(ticket.requestId), isFalse);
    });

    test('retry cancels old ID and creates a new pending request', () {
      final coordinator = ChatRequestCoordinator();
      final first = coordinator.begin(nowMicros: 1);
      final retry = coordinator.retry(first.requestId, nowMicros: 2);
      expect(coordinator.acceptsEvents(first.requestId), isFalse);
      expect(coordinator.acceptsEvents(retry.requestId), isTrue);
      expect(retry.requestId, isNot(first.requestId));
    });
  });
}
