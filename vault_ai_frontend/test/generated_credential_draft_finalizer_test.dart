import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:vault_ai_frontend/services/generated_credential_draft_finalizer.dart';

void main() {
  test('rapid saves share one operation and one success', () async {
    final finalizer = GeneratedCredentialDraftFinalizer();
    final gate = Completer<void>();
    var writes = 0;

    Future<void> write() async {
      writes += 1;
      await gate.future;
    }

    final first = finalizer.save('vault:draft', write);
    final second = finalizer.save('vault:draft', write);
    expect(writes, 1);
    gate.complete();
    expect(await first, isTrue);
    expect(await second, isFalse);
    expect(writes, 1);
  });

  test('completed replay cannot write again', () async {
    final finalizer = GeneratedCredentialDraftFinalizer();
    var writes = 0;
    expect(
      await finalizer.save('vault:draft', () async => writes += 1),
      isTrue,
    );
    expect(
      await finalizer.save('vault:draft', () async => writes += 1),
      isFalse,
    );
    expect(writes, 1);
  });

  test('cancel is terminal and save after cancel performs no write', () async {
    final finalizer = GeneratedCredentialDraftFinalizer();
    var writes = 0;
    expect(await finalizer.cancel('vault:draft', () async {}), isTrue);
    expect(
      await finalizer.save('vault:draft', () async => writes += 1),
      isFalse,
    );
    expect(writes, 0);
  });

  test('cancel during save waits and cannot undo successful save', () async {
    final finalizer = GeneratedCredentialDraftFinalizer();
    final gate = Completer<void>();
    final save = finalizer.save('vault:draft', () => gate.future);
    final cancel = finalizer.cancel('vault:draft', () async {
      fail('server cancel must not run after a successful save');
    });
    gate.complete();
    expect(await save, isTrue);
    expect(await cancel, isFalse);
  });

  test('separate drafts may each create a same-service credential', () async {
    final finalizer = GeneratedCredentialDraftFinalizer();
    var writes = 0;
    expect(
      await finalizer.save('vault:draft-1', () async => writes += 1),
      isTrue,
    );
    expect(
      await finalizer.save('vault:draft-2', () async => writes += 1),
      isTrue,
    );
    expect(writes, 2);
  });
}
