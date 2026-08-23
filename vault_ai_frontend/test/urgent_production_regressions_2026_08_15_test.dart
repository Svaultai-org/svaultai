import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart';
import 'package:vault_ai_frontend/services/credential_v2_api.dart';
import 'package:vault_ai_frontend/services/credential_v2_repository.dart';

void main() {
  group('production memory and credential routing boundaries', () {
    test('trailing save language stays on the local memory path', () {
      final fact = parseLocalMemoryFact("my mother's name is Iodato, save it");

      expect(fact, isNotNull);
      expect(fact!.subject, "mother's name");
      expect(fact.value, 'Iodato');
      expect(fact.relationship, 'mother');
      expect(fact.attribute, 'name');
      expect(fact.memoryType, 'identity');
      expect(fact.normalized, 'mother:name');
      expect(fact.tags, containsAll(<String>['family', 'mother', 'name']));
    });

    test('leading and trailing memory directives accept natural variants', () {
      for (final text in <String>[
        "please remember that my mother's name is Iodato",
        "my mother's name is Iodato, please save this",
      ]) {
        expect(hasExplicitLocalMemorySaveDirective(text), isTrue);
        final fact = parseLocalMemoryFact(text);
        expect(fact, isNotNull);
        expect(fact!.subject, "mother's name");
        expect(fact.value, 'Iodato');
      }
    });

    test('family-name saves accept no-as and with-as forms', () {
      for (final text in <String>[
        "save my mother's name lodato kendra",
        'save my mother’s name lodato kendra',
        "save my mother's name as lodato kendra",
        "remember my mother's name is lodato kendra",
      ]) {
        expect(hasExplicitLocalMemorySaveDirective(text), isTrue);
        final fact = parseLocalMemoryFact(text);
        expect(fact, isNotNull, reason: text);
        expect(fact!.relationship, 'mother', reason: text);
        expect(fact.attribute, 'name', reason: text);
        expect(fact.value, 'lodato kendra', reason: text);
        expect(fact.normalized, 'mother:name', reason: text);
      }
    });

    test('family-memory recall precedes generic private arbitration', () {
      final source = File('lib/main.dart').readAsStringSync();
      final sendRoute = source.substring(
        source.indexOf('if (await _tryLocalMemoryV2ContextSave(text, app))'),
        source.indexOf('if (privateLocalRouting',
            source.indexOf('if (await _tryLocalMemoryV2ContextSave(text, app))')),
      );
      expect(
        sendRoute.indexOf('_tryLocalMemoryV2LookupReply'),
        lessThan(sendRoute.indexOf('_tryLocalPrivateDomainArbitration')),
      );
      for (final wording in <String>[
        "what is my mother's name",
        "what's my mom's name",
        "do you remember my mother's name",
      ]) {
        expect(parseLocalMemoryLookupIntent(wording), isNotNull,
            reason: wording);
      }
    });

    test('authoritative Memory V2 write precedes success acknowledgement', () {
      final source = File('lib/main.dart').readAsStringSync();
      final start =
          source.indexOf('Future<bool> _tryLocalMemoryV2ContextSave');
      final end = source.indexOf('\n  Future<void> _send()', start + 1);
      final method = source.substring(start, end);
      final create = method.indexOf('await MemoryV2Repository(');
      final success = method.indexOf("_appendAssistantMessage('Saved:");
      final failure = method.indexOf(
          "_appendAssistantMessage('Could not save that memory securely.')");
      expect(create, greaterThanOrEqualTo(0));
      expect(success, greaterThan(create));
      expect(failure, greaterThan(success));
    });

    test('saved mother-name Memory V2 row is listable and recallable', () {
      final intent = parseLocalMemoryLookupIntent("what is my mother's name");
      expect(intent, isNotNull);
      final rows = <Map<String, dynamic>>[
        <String, dynamic>{
          'id': 'memory-test',
          'memory_type': 'identity',
          'title': 'mother:name',
          'value': 'lodato kendra',
          'tags': <String>['family', 'mother', 'name'],
        },
      ];
      final result = matchLocalMemoryRecords(intent!, rows);
      expect(result.ambiguous, isFalse);
      expect(result.records, hasLength(1));
      expect(result.records.single['value'], 'lodato kendra');

      final memoryPage = File('lib/ui/dashboards/memory_page.dart')
          .readAsStringSync();
      expect(memoryPage, contains('MemoryV2Repository('));
      expect(memoryPage, contains('.listDecrypted()'));
    });

    test('explicit login creation honors the write rollout gate', () {
      final source = File('lib/main.dart').readAsStringSync();
      final method = source.substring(
        source.indexOf('Future<bool> _tryLocalCredentialV2CreateReply'),
        source.indexOf(
          'Future<bool> _tryLocalPrivateDeleteReply',
          source.indexOf('Future<bool> _tryLocalCredentialV2CreateReply'),
        ),
      );

      expect(
          method, contains('if (!zkV2CredentialWriteEnabled) return false;'));
    });

    test('natural explicit login creation remains a credential intent', () {
      const text = 'create me a facebook logins';
      final intent = parseCredentialV2CreateIntent(text);

      expect(intent, isNotNull);
      expect(intent!.service, 'facebook');
      expect(parseCredentialV2LookupIntent(text), isNull);
      expect(extractInventoryPrivateLookupTopic(text), isNull);
      expect(looksLikePrivateCredentialQuery(text), isTrue);
      expect(shouldAttemptCredentialV2Lookup(text), isFalse);
    });

    test('credential assertions bypass the private-command catch-all', () {
      const assertion =
          'username audit-user password Audit-pass! is my AuditService login';

      expect(
        shouldRouteCredentialV2CreateToBackend(
          assertion,
          localWriteEnabled: false,
        ),
        isTrue,
      );
      expect(
        shouldRouteCredentialV2CreateToBackend(
          assertion,
          localWriteEnabled: true,
        ),
        isFalse,
      );
      expect(
        shouldRouteCredentialV2CreateToBackend(
          'what is my password',
          localWriteEnabled: false,
        ),
        isFalse,
      );

      final source = File('lib/main.dart').readAsStringSync();
      expect(source, contains('!credentialCreateRequiresBackend &&'));
    });

    test('explicit credential reads still use the local lookup route', () {
      expect(
          shouldAttemptCredentialV2Lookup('show me my github login'), isTrue);
      expect(
          shouldAttemptCredentialV2Lookup('what is my login password'), isTrue);
      expect(shouldAttemptCredentialV2Lookup('what are you'), isFalse);
    });

    test('known legacy credential edits cannot divert into a v2 upsert', () {
      final apiSource = File('lib/api_client.dart').readAsStringSync();
      final mainSource = File('lib/main.dart').readAsStringSync();

      expect(apiSource, contains('bool forceLegacyTransport = false'));
      expect(
        apiSource,
        contains('if (!forceLegacyTransport && '
            'zk_mvk_store.ZkActiveMvk.current() != null)'),
      );
      expect(
        mainSource,
        contains('forceLegacyTransport: true,'),
      );
    });

    test('feature-route mismatch has actionable non-network recovery', () {
      final copy = safeCredentialInventoryRecoveryMessage(
        const CredentialV2RequestException(404),
      );

      expect(copy, contains('out of sync'));
      expect(copy, contains('Tap Retry'));
      expect(copy, isNot(contains('connection')));
    });
  });

  group('Brain transport deadlines', () {
    test('stalled chat streams resolve with a typed timeout', () async {
      final never = StreamController<String>();
      addTearDown(never.close);

      await expectLater(
        boundedChatResponseStream(
          never.stream,
          firstEventTimeout: const Duration(milliseconds: 10),
          idleTimeout: const Duration(milliseconds: 10),
        ).drain<void>(),
        throwsA(isA<ChatResponseTimeoutException>()),
      );
    });

    test('active long responses are not cut off while chunks arrive', () async {
      final events = Stream<String>.periodic(
        const Duration(milliseconds: 5),
        (index) => 'chunk-$index',
      ).take(3);

      expect(
        await boundedChatResponseStream(
          events,
          firstEventTimeout: const Duration(milliseconds: 30),
          idleTimeout: const Duration(milliseconds: 30),
        ).toList(),
        ['chunk-0', 'chunk-1', 'chunk-2'],
      );
    });

    test('typed timeout recovery is not overwritten by empty-stream copy', () {
      final source = File('lib/main.dart').readAsStringSync();

      expect(source, contains('terminalFailureRendered = true;'));
      expect(source, contains('else if (!terminalFailureRendered &&'));
    });
  });
}
