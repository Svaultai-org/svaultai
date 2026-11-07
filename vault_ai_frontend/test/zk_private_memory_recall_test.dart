import 'dart:async';
import 'dart:convert';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/session_termination.dart' as st;
import 'package:vault_ai_frontend/services/vault_key_hierarchy.dart'
    as hierarchy;
import 'package:vault_ai_frontend/services/zk_active_mvk.dart';
import 'package:vault_ai_frontend/services/zk_private_memory_recall.dart';

const _base = 'https://synthetic.invalid';
const _token = 'synthetic-private-memory-token';
const _secret = '12 April 2030';

void _bindPrivateVault() {
  st.SessionTermination.instance.bindSession(_token);
  PrivateZkPinTransportSession.bind(_token);
  ZkActiveMvk.set(
    mvk: SecretKey(List<int>.generate(32, (index) => index + 1)),
    vaultId: 'synthetic-vault',
    vaultHandle: 'synthetic-handle',
  );
}

Future<Map<String, dynamic>> _envelope({
  required String id,
  required String title,
  required String value,
}) async {
  final key = await hierarchy.VaultKeyHierarchy(
    ZkActiveMvk.current()!,
  ).memoryKey();
  return <String, dynamic>{
    'memory_id': id,
    'memory_type': 'note',
    'payload_ciphertext': hierarchy.b64urlEncode(
      await hierarchy.aesGcmWrap(
        key,
        utf8.encode(
          jsonEncode(<String, dynamic>{
            'title': title,
            'memory_key': title,
            'value': value,
          }),
        ),
      ),
    ),
  };
}

void main() {
  setUp(() {
    st.SessionTermination.instance.reset();
    PrivateZkPinTransportSession.clear();
    ZkActiveMvk.clear();
    setApiClientDeviceId('synthetic-memory-device');
  });
  tearDown(() {
    st.SessionTermination.instance.reset();
    PrivateZkPinTransportSession.clear();
    ZkActiveMvk.clear();
    setApiClientDeviceId('');
  });

  test(
    'natural recall decrypts a V2 memory locally with ciphertext-only GET',
    () async {
      _bindPrivateVault();
      final ready = await _envelope(
        id: 'legacy-memory-v2-17-snapshot',
        title: 'Project Atlas launch date',
        value: _secret,
      );
      expect(jsonEncode(ready), isNot(contains(_secret)));
      var requests = 0;
      final client = VaultAIClient(
        baseUrl: _base,
        httpClient: MockClient((request) async {
          requests++;
          expect(request.method, 'GET');
          expect(request.url.path, '/vault/ciphertext/vault-ai-memory');
          expect(request.url.query, isEmpty);
          expect(request.body, isEmpty);
          expect(request.headers['authorization'], 'Bearer $_token');
          expect(request.headers['x-device-id'], 'synthetic-memory-device');
          expect(request.url.toString(), isNot(contains(_secret)));
          expect(request.url.toString().toLowerCase(), isNot(contains('pin')));
          return http.Response(jsonEncode([ready]), 200);
        }),
      );
      final reply = await tryZkPrivateMemoryRecall(
        prompt: 'What is my Project Atlas launch date?',
        readMemories: () => client.listZkMemories(authToken: _token, limit: 0),
        accessIsCurrent: () => true,
      );
      expect(requests, 1);
      expect(reply, contains(_secret));
      expect(reply, contains('Project Atlas launch date'));
    },
  );

  test(
    'explicit missing memory is qualified because legacy rows may be hidden',
    () async {
      var reads = 0;
      final reply = await tryZkPrivateMemoryRecall(
        prompt: 'What do you remember about Project Atlas?',
        readMemories: () async {
          reads++;
          return <String, dynamic>{
            'engine': 'ciphertext',
            'items': <Map<String, dynamic>>[],
            'unavailable_count': 0,
          };
        },
        accessIsCurrent: () => true,
      );
      expect(reads, 1);
      expect(
        reply,
        contains('Older memories may still need a private upgrade'),
      );
    },
  );

  test('unrelated question makes no memory request', () async {
    var reads = 0;
    final reply = await tryZkPrivateMemoryRecall(
      prompt: 'How does two-factor authentication work?',
      readMemories: () async {
        reads++;
        return <String, dynamic>{'engine': 'ciphertext', 'items': []};
      },
      accessIsCurrent: () => true,
    );
    expect(reply, isNull);
    expect(reads, 0);
    expect(
      await tryZkPrivateMemoryRecall(
        prompt: 'What is two-factor authentication?',
        readMemories: () async {
          reads++;
          return <String, dynamic>{'engine': 'ciphertext', 'items': []};
        },
        accessIsCurrent: () => true,
      ),
      isNull,
    );
    expect(reads, 0);
  });

  test('equal title matches never reveal either memory value', () async {
    final reply = await tryZkPrivateMemoryRecall(
      prompt: 'Show my memory about Project Atlas',
      readMemories: () async => <String, dynamic>{
        'engine': 'ciphertext',
        'items': <Map<String, dynamic>>[
          {'id': 'first', 'title': 'Project Atlas', 'value': 'first secret'},
          {'id': 'second', 'title': 'Project Atlas', 'value': 'second secret'},
        ],
      },
      accessIsCurrent: () => true,
    );
    expect(reply, contains('Several private memories match'));
    expect(reply, isNot(contains('first secret')));
    expect(reply, isNot(contains('second secret')));
  });

  test('unreadable ciphertext cannot be reported as an absent memory',
      () async {
    final reply = await tryZkPrivateMemoryRecall(
      prompt: 'Show my memory called Project Atlas',
      readMemories: () async => <String, dynamic>{
        'engine': 'ciphertext',
        'items': <Map<String, dynamic>>[],
        'unavailable_count': 1,
      },
      accessIsCurrent: () => true,
    );
    expect(reply, contains('could not be opened'));
    expect(reply, isNot(contains('No saved memory')));
  });

  test('vault switch during read drops the result', () async {
    final pending = Completer<Map<String, dynamic>>();
    var current = true;
    final recall = tryZkPrivateMemoryRecall(
      prompt: 'What do you remember about Project Atlas?',
      readMemories: () => pending.future,
      accessIsCurrent: () => current,
    );
    current = false;
    pending.complete(<String, dynamic>{
      'engine': 'ciphertext',
      'items': <Map<String, dynamic>>[
        {'id': 'old-vault', 'title': 'Project Atlas', 'value': 'old secret'},
      ],
    });
    await expectLater(recall, throwsStateError);
  });
}
