import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/main.dart' show
    kEnableZkGeneralChatBridge, kEnableZkGeneralOnlyChatBridge;
import 'package:vault_ai_frontend/services/zk_general_chat_bridge.dart';
import 'package:vault_ai_frontend/services/zk_private_chat.dart';

void main() {
  test('transitional route is off in an ordinary build', () {
    expect(kEnableZkGeneralChatBridge, isFalse);
    expect(kEnableZkGeneralOnlyChatBridge, isFalse);
  }, skip: const bool.fromEnvironment('VAULTAI_ENABLE_ZK_GENERAL_CHAT_BRIDGE') ||
      const bool.fromEnvironment('VAULTAI_ENABLE_ZK_GENERAL_ONLY_CHAT_BRIDGE'));

  test('general-only rollout leaves every private and unavailable turn on the working path', () {
    ZkGeneralBridgeRoute route(String prompt, {
      bool handle = true,
      bool mvk = true,
      bool matches = true,
      bool attachment = false,
    }) => resolveZkGeneralBridgeRoute(
      enabled: true,
      hasZkHandle: handle,
      hasMvk: mvk,
      mvkMatchesVault: matches,
      hasAttachments: attachment,
      prompt: prompt,
      vaultName: 'Synthetic vault',
      preserveLegacyPrivateChat: true,
    );
    expect(route('What is encryption?'), ZkGeneralBridgeRoute.general);
    expect(route('What is encryption?', handle: false),
        ZkGeneralBridgeRoute.legacy);
    expect(route('What is encryption?', mvk: false),
        ZkGeneralBridgeRoute.legacy);
    expect(route('What is encryption?', matches: false),
        ZkGeneralBridgeRoute.legacy);
    expect(route('Find my red photo'), ZkGeneralBridgeRoute.legacy);
    expect(route('What about that file?'), ZkGeneralBridgeRoute.legacy);
    expect(route('What is encryption?', attachment: true),
        ZkGeneralBridgeRoute.legacy);
  });

  test('only explicit general questions qualify', () {
    for (final prompt in [
      'What is end-to-end encryption?',
      'How does two-factor authentication work?',
      'Explain zero-knowledge encryption in simple terms.',
      'Could you explain zero-knowledge encryption in more detail?',
    ]) {
      expect(isClearlyGeneralChatPrompt(prompt), isTrue, reason: prompt);
    }
    for (final prompt in [
      'show it',
      'What about that file?',
      'What about the second one?',
      'What is the second one?',
      'Explain the other one.',
      "What is Alice's birthday?",
      'What is the address for Alice?',
      'How do I find my passport?',
      'What is my GitHub recovery code?',
      'What is the PIN?',
      'Explain the private key',
      'Find a photo of me in red clothes',
      'Explain my saved login',
      'What was there earlier?',
      'What is 1234567890?',
      'What is contact@example.com?',
      'What is https://example.com/secret?',
      'Save a note for me',
    ]) {
      expect(isClearlyGeneralChatPrompt(prompt), isFalse, reason: prompt);
    }
    expect(
      isClearlyGeneralChatPrompt('What is Brain?', vaultName: 'Brain'),
      isFalse,
    );
  });

  test('OPAQUE bridge has no legacy chat fallback', () {
    ZkGeneralBridgeRoute route(
      String prompt, {
      bool enabled = true,
      bool handle = true,
      bool mvk = true,
      bool matches = true,
      bool attachment = false,
    }) =>
        resolveZkGeneralBridgeRoute(
          enabled: enabled,
          hasZkHandle: handle,
          hasMvk: mvk,
          mvkMatchesVault: matches,
          hasAttachments: attachment,
          prompt: prompt,
          vaultName: 'Synthetic vault',
        );

    expect(route('What is encryption?', enabled: false),
        ZkGeneralBridgeRoute.legacy);
    expect(route('What is encryption?', handle: false, mvk: false),
        ZkGeneralBridgeRoute.legacy);
    expect(route('What is encryption?', mvk: false),
        ZkGeneralBridgeRoute.unavailable);
    expect(route('What is encryption?', matches: false),
        ZkGeneralBridgeRoute.unavailable);
    expect(route('What is encryption?'), ZkGeneralBridgeRoute.general);
    expect(route('What is encryption?', handle: false),
        ZkGeneralBridgeRoute.general);
    expect(route('Find my red photo'), ZkGeneralBridgeRoute.privateLocal);
    expect(route('What about that file?'), ZkGeneralBridgeRoute.privateLocal);
    expect(
        route('What about the second one?'), ZkGeneralBridgeRoute.privateLocal);
    expect(route('What is the second one?'), ZkGeneralBridgeRoute.privateLocal);
    expect(route('What is encryption?', attachment: true),
        ZkGeneralBridgeRoute.privateLocal);
  });

  test('same-session follow-up uses only successful general history', () async {
    final seen = <List<ZkGeneralChatTurn>>[];
    final bridge = ZkGeneralChatBridge(
      accessIsCurrent: () => true,
      sendGeneral: (prompt, history) async {
        seen.add(history);
        return 'Answer ${seen.length}';
      },
    );
    expect(await bridge.send('What is end-to-end encryption?'), 'Answer 1');
    expect(
      await bridge.send('Explain zero-knowledge encryption in more detail.'),
      'Answer 2',
    );
    expect(seen[0], isEmpty);
    expect(seen[1].length, 2);
    expect(seen[1][0].content, 'What is end-to-end encryption?');
    expect(seen[1][1].content, 'Answer 1');
    await expectLater(bridge.send('show it'), throwsStateError);
    expect(seen.length, 2);
    bridge.clear();
    await bridge.send('What is encryption?');
    expect(seen[2], isEmpty);
  });

  test('errors and a changed session never fall back or retain a turn',
      () async {
    var calls = 0;
    var current = true;
    var fail = true;
    final seen = <List<ZkGeneralChatTurn>>[];
    final bridge = ZkGeneralChatBridge(
      accessIsCurrent: () => current,
      sendGeneral: (_, history) async {
        calls++;
        seen.add(history);
        if (fail) throw StateError('synthetic network failure');
        return 'safe answer';
      },
    );
    await expectLater(
      bridge.send('What is encryption?'),
      throwsStateError,
    );
    fail = false;
    expect(await bridge.send('What is encryption?'), 'safe answer');
    expect(seen[1], isEmpty);
    current = false;
    await expectLater(
      bridge.send('Explain encryption.'),
      throwsStateError,
    );
    expect(calls, 2);
  });

  test('bridge uses authenticated PIN-free wire body for general turns',
      () async {
    final captured = <Map<String, dynamic>>[];
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        expect(request.url.path, '/chat/zk/general');
        expect(request.headers['Authorization'], 'Bearer synthetic-token');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body.keys.toSet(), {'message', 'history'});
        expect(request.body, isNot(contains('"pin"')));
        expect(request.body, isNot(contains('vault_name')));
        expect(request.body, isNot(contains('synthetic-private-file')));
        captured.add(body);
        return http.Response('{"reply":"safe answer","mode":"general"}', 200);
      }),
    );
    final bridge = ZkGeneralChatBridge(
      accessIsCurrent: () => true,
      vaultName: 'Synthetic Vault Name',
      sendGeneral: (prompt, history) => client.zkGeneralChat(
        authToken: 'synthetic-token',
        message: prompt,
        history: history,
        accessGuard: () {},
      ),
    );
    await expectLater(
      bridge.send('What about that file?'),
      throwsStateError,
    );
    expect(captured, isEmpty);
    await expectLater(
      bridge.send('What is Synthetic Vault Name?'),
      throwsStateError,
    );
    expect(captured, isEmpty);
    await bridge.send('What is end-to-end encryption?');
    await bridge.send('Explain zero-knowledge encryption in more detail.');
    expect(captured.length, 2);
    expect(captured[1]['history'], hasLength(2));
  });
}
