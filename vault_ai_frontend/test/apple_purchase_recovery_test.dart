import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:vault_ai_frontend/services/apple_iap_service.dart';
import 'package:vault_ai_frontend/services/apple_purchase_recovery.dart';

const verified = <String, dynamic>{'verified': true, 'status': 'active'};

PurchaseDetails purchase({
  String? id = 'transaction-1',
  String receipt = 'signed-transaction-1',
  String? product,
  PurchaseStatus status = PurchaseStatus.purchased,
}) =>
    PurchaseDetails(
      purchaseID: id,
      productID: product ?? appleStorageProductIds[1]!,
      verificationData: PurchaseVerificationData(
        localVerificationData: '',
        serverVerificationData: receipt,
        source: 'app_store',
      ),
      transactionDate: '1234',
      status: status,
    )..pendingCompletePurchase = true;

class FakeAppleStore implements AppleStoreAdapter {
  final updates = StreamController<List<PurchaseDetails>>.broadcast(sync: true);
  final product = ProductDetails(
    id: appleStorageProductIds[1]!,
    title: '50 GB',
    description: 'Monthly storage',
    price: '\$14.99',
    rawPrice: 14.99,
    currencyCode: 'USD',
  );
  int buys = 0;
  int restores = 0;
  int finishes = 0;
  PurchaseParam? lastBuy;
  String? lastRestoreToken;
  Completer<bool>? buyGate;
  Completer<void>? restoreGate;
  Completer<void>? finishGate;
  bool failFinish = false;

  @override
  Stream<List<PurchaseDetails>> get purchaseStream => updates.stream;
  @override
  Future<bool> isAvailable() async => true;
  @override
  Future<ProductDetailsResponse> queryProductDetails(
          Set<String> identifiers) async =>
      ProductDetailsResponse(productDetails: [product], notFoundIDs: []);
  @override
  Future<bool> buy(PurchaseParam purchaseParam) async {
    buys++;
    lastBuy = purchaseParam;
    return buyGate == null ? true : await buyGate!.future;
  }

  @override
  Future<void> restore(String appAccountToken) async {
    restores++;
    lastRestoreToken = appAccountToken;
    if (restoreGate != null) await restoreGate!.future;
  }

  @override
  Future<void> finish(PurchaseDetails purchase) async {
    finishes++;
    if (failFinish) throw StateError('Store unavailable');
    if (finishGate != null) await finishGate!.future;
  }
}

void main() {
  group('bounded transaction recovery', () {
    test('transient failures retry verification only, then finish once',
        () async {
      final delays = <Duration>[];
      final recovery =
          ApplePurchaseRecovery(delay: (delay) async => delays.add(delay));
      var verifies = 0;
      var finishes = 0;
      final result = await recovery.recover(
        accountKey: 'vault-session',
        transactionKey: 'same-transaction',
        verify: () async {
          verifies++;
          if (verifies == 1) throw const ApplePurchaseVerificationException();
          if (verifies == 2) {
            throw const ApplePurchaseVerificationException(statusCode: 502);
          }
          return verified;
        },
        finish: () async => finishes++,
      );
      expect(result.handled, isTrue);
      expect(verifies, 3);
      expect(finishes, 1);
      expect(delays,
          [const Duration(milliseconds: 500), const Duration(seconds: 1)]);
    });

    test('three transient failures stop, retain recovery and never finish',
        () async {
      final recovery = ApplePurchaseRecovery(delay: (_) async {});
      var verifies = 0;
      var finishes = 0;
      Future<ApplePurchaseRecoveryResult> recover() => recovery.recover(
            accountKey: 'vault-session',
            transactionKey: 'same-transaction',
            verify: () async {
              verifies++;
              throw const ApplePurchaseVerificationException(statusCode: 503);
            },
            finish: () async => finishes++,
          );
      await expectLater(
          recover(), throwsA(isA<ApplePurchaseVerificationException>()));
      expect(verifies, 3);
      expect(finishes, 0);
      // Restore/redelivery can retry the SAME unfinished transaction later.
      await expectLater(
          recover(), throwsA(isA<ApplePurchaseVerificationException>()));
      expect(verifies, 6);
      expect(finishes, 0);
    });

    for (final failure in [
      const ApplePurchaseVerificationException(statusCode: 400),
      const ApplePurchaseVerificationException(statusCode: 401),
      const ApplePurchaseVerificationException(statusCode: 403),
      const ApplePurchaseVerificationException(statusCode: 404),
      const ApplePurchaseVerificationException(statusCode: 409),
      const ApplePurchaseVerificationException(statusCode: 429),
      const ApplePurchaseVerificationException(
          statusCode: 503, code: 'apple_billing_not_configured'),
    ]) {
      test(
          'permanent ${failure.statusCode}/${failure.code} is not retried or finished',
          () async {
        var verifies = 0;
        var finishes = 0;
        final recovery =
            ApplePurchaseRecovery(delay: (_) async => fail('Unexpected retry'));
        await expectLater(
          recovery.recover(
            accountKey: 'vault-session',
            transactionKey: 'same-transaction',
            verify: () async {
              verifies++;
              throw failure;
            },
            finish: () async => finishes++,
          ),
          throwsA(same(failure)),
        );
        expect(verifies, 1);
        expect(finishes, 0);
      });
    }

    test('duplicate callbacks coalesce and completed redelivery is ignored',
        () async {
      final gate = Completer<Map<String, dynamic>>();
      final recovery = ApplePurchaseRecovery();
      var verifies = 0;
      var finishes = 0;
      Future<ApplePurchaseRecoveryResult> recover() => recovery.recover(
            accountKey: 'vault-session',
            transactionKey: 'same-transaction',
            verify: () {
              verifies++;
              return gate.future;
            },
            finish: () async => finishes++,
          );
      final first = recover();
      final duplicate = recover();
      gate.complete(verified);
      expect((await first).handled, isTrue);
      expect((await duplicate).handled, isFalse);
      expect((await recover()).handled, isFalse);
      expect(verifies, 1);
      expect(finishes, 1);
    });

    test('a different vault/session must independently verify ownership',
        () async {
      final recovery = ApplePurchaseRecovery();
      var finishes = 0;
      await recovery.recover(
        accountKey: 'first-vault-session',
        transactionKey: 'same-transaction',
        verify: () async => verified,
        finish: () async => finishes++,
      );
      await expectLater(
        recovery.recover(
          accountKey: 'other-vault-session',
          transactionKey: 'same-transaction',
          verify: () async => throw const ApplePurchaseVerificationException(
              statusCode: 409,
              code: 'subscription_bound_to_another_active_account'),
          finish: () async => finishes++,
        ),
        throwsA(isA<ApplePurchaseVerificationException>()),
      );
      expect(finishes, 1);
    });

    test('HTTP success without explicit verification never finishes', () async {
      var finishes = 0;
      final recovery = ApplePurchaseRecovery();
      await expectLater(
        recovery.recover(
          accountKey: 'vault-session',
          transactionKey: 'same-transaction',
          verify: () async => {'verified': false},
          finish: () async => finishes++,
        ),
        throwsA(isA<ApplePurchaseVerificationException>()),
      );
      expect(finishes, 0);
    });
  });

  group('StoreKit adapter and pending transaction recovery', () {
    late FakeAppleStore store;
    late AppleIapService service;
    setUp(() {
      store = FakeAppleStore();
      service = AppleIapService.forTesting(store: store)..initialize();
    });
    tearDown(() async {
      await service.disposeForTesting();
      await store.updates.close();
    });

    test('rapid checkout taps call Apple only once and use opaque token',
        () async {
      store.buyGate = Completer<bool>();
      final first =
          service.buy(product: store.product, appAccountToken: 'opaque-token');
      expect(
          await service.buy(
              product: store.product, appAccountToken: 'opaque-token'),
          isFalse);
      store.buyGate!.complete(true);
      expect(await first, isTrue);
      expect(
          await service.buy(
              product: store.product, appAccountToken: 'opaque-token'),
          isFalse);
      expect(store.buys, 1);
      expect(store.lastBuy!.applicationUserName, 'opaque-token');
    });

    test(
        'unrelated cancellation does not unlock an outstanding pending purchase',
        () async {
      store.updates.add([purchase(status: PurchaseStatus.pending)]);
      store.updates
          .add([purchase(id: 'other', status: PurchaseStatus.canceled)]);
      expect(service.hasPendingStoreRequest, isTrue);
      expect(
          await service.buy(
              product: store.product, appAccountToken: 'opaque-token'),
          isFalse);
      expect(store.buys, 0);
    });

    test(
        'unverified purchase survives other batches, reopens and resume replay',
        () async {
      final saved = purchase();
      store.updates.add([saved]);
      store.updates
          .add([purchase(id: 'unrelated', status: PurchaseStatus.canceled)]);
      expect(await service.transactions.first, [saved]);
      final replay = service.transactions.skip(1).first;
      service.replayPendingTransactions();
      expect(await replay, [saved]);
      expect(service.hasPendingActivation, isTrue);
      await expectLater(
          service.buy(product: store.product, appAccountToken: 'opaque-token'),
          throwsStateError);
      expect(store.buys, 0);
      expect(store.finishes, 0);
    });

    test(
        'failed verification then Restore activates same purchase without new charge',
        () async {
      final saved = purchase();
      store.updates.add([saved]);
      var rejects = true;
      final recovery = ApplePurchaseRecovery(delay: (_) async {});
      Future<ApplePurchaseRecoveryResult> recover(
              PurchaseDetails transaction) =>
          recovery.recover(
            accountKey: 'vault-session',
            transactionKey: appleTransactionKey(transaction),
            verify: () async {
              if (rejects) {
                throw const ApplePurchaseVerificationException(statusCode: 502);
              }
              return verified;
            },
            finish: () => service.finish(transaction),
          );
      await expectLater(
          recover(saved), throwsA(isA<ApplePurchaseVerificationException>()));
      expect(store.finishes, 0);
      expect(service.hasPendingActivation, isTrue);
      rejects = false;
      final replay = service.transactions.skip(1).first;
      await service.restore(appAccountToken: 'opaque-token');
      expect((await recover((await replay).single)).handled, isTrue);
      expect(store.lastRestoreToken, 'opaque-token');
      expect(store.restores, 1);
      expect(store.finishes, 1);
      expect(store.buys, 0);
      expect(service.hasPendingActivation, isFalse);
    });

    test('concurrent Restore calls coalesce; empty Restore can be repeated',
        () async {
      store.restoreGate = Completer<void>();
      final first = service.restore(appAccountToken: 'opaque-token');
      final duplicate = service.restore(appAccountToken: 'opaque-token');
      expect(store.restores, 1);
      store.restoreGate!.complete();
      await Future.wait([first, duplicate]);
      await service.restore(appAccountToken: 'opaque-token');
      expect(store.restores, 2);
      expect(service.hasPendingActivation, isFalse);
      expect(store.buys, 0);
    });

    test('finish runs once even with concurrent duplicate callbacks', () async {
      final saved = purchase();
      store.updates.add([saved]);
      store.finishGate = Completer<void>();
      final first = service.finish(saved);
      final duplicate = service.finish(saved);
      expect(store.finishes, 1);
      store.finishGate!.complete();
      await Future.wait([first, duplicate]);
      await service.finish(saved);
      expect(store.finishes, 1);
      expect(service.hasPendingActivation, isFalse);
    });

    test('failed StoreKit finish remains recoverable by redelivery', () async {
      final saved = purchase();
      store.updates.add([saved]);
      store.failFinish = true;
      await expectLater(service.finish(saved), throwsStateError);
      expect(service.hasPendingActivation, isTrue);
      expect(await service.transactions.first, [saved]);
      store.failFinish = false;
      await service.finish(saved);
      expect(store.finishes, 2);
      expect(service.hasPendingActivation, isFalse);
    });

    test(
        'finishing a null-ID purchase does not discard another null-ID purchase',
        () async {
      final first = purchase(id: null, receipt: 'signed-first');
      final second = purchase(id: null, receipt: 'signed-second');
      store.updates.add([first, second]);
      await service.finish(first);
      expect(await service.transactions.first, [second]);
      expect(service.hasPendingActivation, isTrue);
    });

    test(
        'exact historical products restore, but never enter new-purchase catalog',
        () async {
      expect(appleLegacyStorageProductIds.length, 8);
      for (final id in appleLegacyStorageProductIds) {
        expect(isAppleStorageProduct(id), isTrue);
        expect(blocksForAppleProduct(id), isNull);
      }
      expect(isAppleStorageProduct('svaultai.storage.unrecognized.monthly'),
          isFalse);
      expect(isAppleStorageProduct('com.svaultai.app.unrecognized'), isFalse);
    });
  });

  test('pending, ownership and configuration messages never advise rebuying',
      () {
    for (final failure in [
      const ApplePurchaseVerificationException(),
      const ApplePurchaseVerificationException(statusCode: 404),
      const ApplePurchaseVerificationException(
          statusCode: 503, code: 'apple_billing_not_configured'),
      const ApplePurchaseVerificationException(
          statusCode: 409,
          code: 'subscription_bound_to_another_active_account'),
      const ApplePurchaseVerificationException(
          statusCode: 409, code: 'apple_transaction_superseded'),
    ]) {
      expect(
          failure.userMessage.toLowerCase(), contains('do not purchase again'));
      expect(failure.userMessage, contains('Restore Purchases'));
    }
    expect(
        const ApplePurchaseVerificationException(
                statusCode: 409, code: 'apple_transaction_superseded')
            .userTitle,
        'Storage plan already updated');
  });
}
