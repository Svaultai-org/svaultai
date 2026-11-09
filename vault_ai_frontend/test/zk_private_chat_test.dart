import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/zk_private_chat.dart';

void main() {
  const recoveryFile = ZkLocalChatRecord(
    kind: ZkLocalChatKind.file,
    id: 'synthetic-file-1',
    title: 'github-recovery-codes.txt',
  );
  const login = ZkLocalChatRecord(
    kind: ZkLocalChatKind.savedItem,
    id: 'synthetic-item-1',
    title: 'GitHub login',
  );

  test('vault file lookup stays local and selects the best title match', () {
    final result = ZkLocalChatRouter.resolve(
      prompt: 'Find my GitHub recovery codes',
      savedItems: const [login],
      files: const [recoveryFile],
    );
    expect(result.disposition, ZkLocalChatDisposition.found);
    expect(result.selection?.id, recoveryFile.id);
    expect(result.maySendToGeneralAi, isFalse);
  });

  test('follow-up show it keeps the selected local file', () {
    final result = ZkLocalChatRouter.resolve(
      prompt: 'show it',
      savedItems: const [login],
      files: const [recoveryFile],
      previousSelection: recoveryFile,
    );
    expect(result.selection, same(recoveryFile));
    expect(result.action, ZkLocalChatAction.open);
    expect(result.maySendToGeneralAi, isFalse);
  });

  test('exact file follow-ups stay local and bound to the selection', () {
    const file = ZkLocalChatRecord(
      kind: ZkLocalChatKind.file,
      id: 'private-text',
      title: 'journal.txt',
      searchText: '🗝️abcdef',
    );
    for (final (prompt, action) in <(String, ZkLocalChatAction)>[
      ('please open it', ZkLocalChatAction.open),
      ('download that', ZkLocalChatAction.download),
      ('what does it say?', ZkLocalChatAction.readText),
      ('what colors are in it?', ZkLocalChatAction.inspectImage),
      ('what is its resolution?', ZkLocalChatAction.inspectImage),
    ]) {
      expect(ZkLocalChatRouter.isSelectedFileFollowUp(prompt), isTrue);
      final result = ZkLocalChatRouter.resolve(
        prompt: prompt, savedItems: const [], files: const [file],
        previousSelection: file,
      );
      expect(result.selection?.id, file.id);
      expect(result.action, action);
      expect(result.maySendToGeneralAi, isFalse);
    }
    expect(ZkLocalChatRouter.isSelectedFileFollowUp('open my other file'),
        isFalse);
    final unbound = ZkLocalChatRouter.resolve(
      prompt: 'what does it say?', savedItems: const [], files: const [file],
    );
    expect(unbound.disposition, ZkLocalChatDisposition.notFound);
    expect(unbound.maySendToGeneralAi, isFalse);
    final imageQuestion = ZkLocalChatRouter.resolve(
      prompt: 'what colors are in it?',
      savedItems: const [], files: const [file],
    );
    expect(imageQuestion.disposition, ZkLocalChatDisposition.notFound);
    expect(imageQuestion.maySendToGeneralAi, isFalse);
    final excerpt = localFileTextExcerpt(file, maxCharacters: 3);
    expect(excerpt, contains('🗝️a'));
    expect(excerpt, isNot(contains('bcdef')));
    expect(excerpt, contains('Excerpt shown'));
    expect(localFileTextExcerpt(recoveryFile), isNull);
    expect(localFileTextExcerpt(login), isNull);
  });

  test('private miss does not fall through to general AI', () {
    final result = ZkLocalChatRouter.resolve(
      prompt: 'Where is my passport?',
      savedItems: const [login],
      files: const [recoveryFile],
    );
    expect(result.disposition, ZkLocalChatDisposition.notFound);
    expect(result.maySendToGeneralAi, isFalse);
  });

  test('unindexed visual description reports the missing private index', () {
    final result = ZkLocalChatRouter.resolve(
      prompt: 'Find a photo of me in red cloth and black shoes',
      savedItems: const [],
      files: const [recoveryFile],
    );
    expect(result.disposition, ZkLocalChatDisposition.needsPrivateIndex);
    expect(result.maySendToGeneralAi, isFalse);
  });

  test('media lookup does not show a file matching only part of the scene', () {
    const redOnly = ZkLocalChatRecord(
      kind: ZkLocalChatKind.file,
      id: 'red-only',
      title: 'red-coat.jpg',
      mediaKind: ZkLocalMediaKind.photo,
      searchText: 'red coat at a party',
    );
    const fullScene = ZkLocalChatRecord(
      kind: ZkLocalChatKind.file,
      id: 'full-scene',
      title: 'holiday.jpg',
      mediaKind: ZkLocalMediaKind.photo,
      searchText: 'red coat with black shoes',
    );
    const prompt = 'Find my photo wearing a red coat with black shoes';
    final partial = ZkLocalChatRouter.resolve(
      prompt: prompt,
      savedItems: const [],
      files: const [redOnly],
    );
    expect(partial.disposition, ZkLocalChatDisposition.needsPrivateIndex);
    expect(partial.maySendToGeneralAi, isFalse);

    final exact = ZkLocalChatRouter.resolve(
      prompt: prompt,
      savedItems: const [],
      files: const [redOnly, fullScene],
    );
    expect(exact.selection?.id, 'full-scene');
    expect(exact.maySendToGeneralAi, isFalse);
  });

  test('two equally matching local records stay ambiguous', () {
    const other = ZkLocalChatRecord(
      kind: ZkLocalChatKind.savedItem,
      id: 'synthetic-item-2',
      title: 'GitHub recovery login',
    );
    final result = ZkLocalChatRouter.resolve(
      prompt: 'Find my GitHub recovery',
      savedItems: const [other],
      files: const [recoveryFile],
    );
    expect(result.disposition, ZkLocalChatDisposition.ambiguous);
    expect(result.matches.length, 2);
    expect(result.maySendToGeneralAi, isFalse);
  });

  test('general follow-up can use the separate AI route', () {
    final result = ZkLocalChatRouter.resolve(
      prompt: 'How does two-factor authentication work?',
      savedItems: const [login],
      files: const [recoveryFile],
    );
    expect(result.disposition, ZkLocalChatDisposition.general);
    expect(result.maySendToGeneralAi, isTrue);
  });

  test('general how-to question is not mistaken for vault lookup', () {
    final result = ZkLocalChatRouter.resolve(
      prompt: 'How do I change my password?',
      savedItems: const [login],
      files: const [recoveryFile],
    );
    expect(result.disposition, ZkLocalChatDisposition.general);
  });

  test('unbound show-it follow-up does not reach general AI', () {
    final result = ZkLocalChatRouter.resolve(
      prompt: 'show it',
      savedItems: const [login],
      files: const [recoveryFile],
    );
    expect(result.disposition, ZkLocalChatDisposition.notFound);
    expect(result.maySendToGeneralAi, isFalse);
  });

  test('general chat wire body contains only user text and bounded history',
      () {
    final body = buildZkGeneralChatBody(
      message: 'Could you explain that again?',
      history: const [
        ZkGeneralChatTurn(role: 'user', content: 'What is 2FA?'),
        ZkGeneralChatTurn(role: 'assistant', content: 'A second login check.'),
      ],
    );
    expect(body.keys.toSet(), {'message', 'history'});
    expect(body.toString(), isNot(contains('synthetic-file-1')));
    expect(body.toString(), isNot(contains('synthetic-item-1')));
    expect(body.toString(), isNot(contains('pin')));
    expect(body.toString(), isNot(contains('vault_key')));
  });

  test('general chat transport sends no PIN or vault record to server',
      () async {
    var requests = 0;
    final mock = MockClient((request) async {
      requests++;
      expect(request.method, 'POST');
      expect(request.url.path, '/chat/zk/general');
      expect(request.headers['Authorization'], 'Bearer synthetic-token');
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      expect(body.keys.toSet(), {'message', 'history'});
      expect(request.body, isNot(contains('synthetic-file-1')));
      expect(request.body, isNot(contains('synthetic-item-1')));
      expect(request.body, isNot(contains('"pin"')));
      return http.Response(
          '{"reply":"A general answer","mode":"general"}', 200);
    });
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: mock,
    );
    final reply = await client.zkGeneralChat(
      authToken: 'synthetic-token',
      message: 'How does two-factor authentication work?',
      vaultName: 'Synthetic Vault Name',
    );
    expect(reply, 'A general answer');
    expect(requests, 1);
  });

  test('general chat transport rejects private turns before network',
      () async {
    var requests = 0;
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        requests++;
        return http.Response('{"reply":"unexpected","mode":"general"}', 200);
      }),
    );
    Future<void> blocked(String message, {
      String vaultName = 'Synthetic Vault Name',
      List<ZkGeneralChatTurn> history = const [],
    }) async {
      await expectLater(
        client.zkGeneralChat(
          authToken: 'synthetic-token',
          message: message,
          vaultName: vaultName,
          history: history,
        ),
        throwsStateError,
      );
    }

    await blocked('What is my PIN?');
    await blocked('What is Synthetic Vault Name?');
    await blocked('How does encryption work?', vaultName: '');
    await blocked('How does encryption work?', history: const [
      ZkGeneralChatTurn(role: 'user', content: 'Find my recovery codes'),
      ZkGeneralChatTurn(role: 'assistant', content: 'No match'),
    ]);
    expect(requests, 0);
  });

  test('general chat transport drops caller-supplied assistant history',
      () async {
    var requests = 0;
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid',
      httpClient: MockClient((request) async {
        requests++;
        expect(request.url.path, '/chat/zk/general');
        expect(request.body, isNot(contains('synthetic-private-canary')));
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['history'], [
          {'role': 'user', 'content': 'What is encryption?'},
        ]);
        return http.Response('{"reply":"safe answer","mode":"general"}', 200);
      }),
    );
    final reply = await client.zkGeneralChat(
      authToken: 'synthetic-token',
      message: 'Explain symmetric encryption.',
      vaultName: 'Synthetic Vault Name',
      history: const [
        ZkGeneralChatTurn(role: 'user', content: 'What is encryption?'),
        ZkGeneralChatTurn(
          role: 'assistant', content: 'synthetic-private-canary',
        ),
      ],
    );
    expect(reply, 'safe answer');
    expect(requests, 1);
  });

  test('private index transport sends only bearer-scoped ciphertext GETs',
      () async {
    var requests = 0;
    final mock = MockClient((request) async {
      requests++;
      expect(request.method, 'GET');
      expect(request.url.path, '/vault/file-v2/synthetic-file-1/manifest');
      expect(request.url.query, isEmpty);
      expect(request.body, isEmpty);
      expect(request.headers['Authorization'], 'Bearer synthetic-token');
      expect(request.toString(), isNot(contains('synthetic-pin')));
      return http.Response('{"file_id":"synthetic-file-1"}', 200);
    });
    final client = VaultAIClient(
      baseUrl: 'https://example.invalid', httpClient: mock,
    );
    final result = await client.zkPrivateChatCiphertextGet(
      authToken: 'synthetic-token',
      path: '/vault/file-v2/synthetic-file-1/manifest',
    );
    expect((result as Map)['file_id'], 'synthetic-file-1');
    await expectLater(
      client.zkPrivateChatCiphertextGet(
        authToken: 'synthetic-token', path: '/auth/login',
      ),
      throwsArgumentError,
    );
    expect(requests, 1);
  });

  test('dispatch never sends saved-item or file lookup to general AI',
      () async {
    var sent = 0;
    Future<String> sendGeneral(String message) async {
      sent++;
      return 'general answer';
    }

    final local = await ZkLocalChatRouter.dispatch(
      prompt: 'Find my GitHub recovery codes',
      savedItems: const [login],
      files: const [recoveryFile],
      sendGeneral: sendGeneral,
    );
    expect(local.local.selection?.id, recoveryFile.id);
    expect(local.generalReply, isNull);
    expect(sent, 0);

    final general = await ZkLocalChatRouter.dispatch(
      prompt: 'How does two-factor authentication work?',
      savedItems: const [login],
      files: const [recoveryFile],
      sendGeneral: sendGeneral,
    );
    expect(general.generalReply, 'general answer');
    expect(sent, 1);
  });
}
