import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/main.dart' show kEnableZkPrivateChat;
import 'package:vault_ai_frontend/services/zk_private_chat.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_flow.dart';
import 'package:vault_ai_frontend/services/zk_private_chat_index.dart';

void main() {
  test('private chat UI dispatch stays off in an ordinary build', () {
    expect(kEnableZkPrivateChat, isFalse);
  });

  test('private media search and follow-up never call general AI', () async {
    var indexLoads = 0;
    var generalCalls = 0;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async {
        indexLoads++;
        return const ZkPrivateChatIndex(
          savedItems: [],
          files: [
            ZkLocalChatRecord(
              kind: ZkLocalChatKind.file,
              id: 'video-1',
              title: 'standing-at-the-beach.mp4',
              mediaKind: ZkLocalMediaKind.video,
            ),
          ],
          incomplete: false,
        );
      },
      sendGeneral: (_, __) async {
        generalCalls++;
        return 'general reply';
      },
    );
    final found = await flow.run('Find my video standing at the beach');
    expect(found.local.selection?.id, 'video-1');
    final followUp = await flow.run('play it');
    expect(followUp.local.selection?.id, 'video-1');
    expect(indexLoads, 2);
    expect(generalCalls, 0);
  });

  test('general AI history excludes every private turn', () async {
    final received = <List<ZkGeneralChatTurn>>[];
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async => const ZkPrivateChatIndex(
        savedItems: [],
        files: [],
        incomplete: false,
      ),
      sendGeneral: (prompt, history) async {
        received.add(history);
        return 'Answer about $prompt';
      },
    );
    await flow.run('What is encryption?');
    await flow.run('Find my passport file');
    await flow.run('How does it work?');
    expect(received, hasLength(2));
    expect(received.first, isEmpty);
    expect(received.last.map((turn) => turn.content).toList(),
        ['What is encryption?', 'Answer about What is encryption?']);
  });

  test('mutation stops before index and network requests', () async {
    var requests = 0;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => true,
      loadIndex: () async {
        requests++;
        return const ZkPrivateChatIndex(
          savedItems: [],
          files: [],
          incomplete: false,
        );
      },
      sendGeneral: (_, __) async {
        requests++;
        return 'should not be sent';
      },
    );
    final result = await flow.run('Delete my beach video');
    expect(result.local.disposition, ZkLocalChatDisposition.unsupportedAction);
    expect(requests, 0);
  });

  test('lock during a general response discards the reply', () async {
    var current = true;
    final flow = ZkPrivateChatFlow(
      accessIsCurrent: () => current,
      loadIndex: () async => const ZkPrivateChatIndex(
        savedItems: [],
        files: [],
        incomplete: false,
      ),
      sendGeneral: (_, __) async {
        current = false;
        return 'late reply';
      },
    );
    await expectLater(flow.run('What is encryption?'), throwsStateError);
  });
}
