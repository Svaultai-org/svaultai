import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:in_app_purchase_android/billing_client_wrappers.dart';
import 'package:in_app_purchase_android/in_app_purchase_android.dart';
import 'package:vault_ai_frontend/services/apple_iap_service.dart';
import 'package:vault_ai_frontend/services/google_play_iap_service.dart';
import 'package:vault_ai_frontend/services/google_play_verification.dart';

import 'google_play_test_fixtures.dart';

void main() {
  test('only Android supports Google; Apple and desktop gates unchanged', () {
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    expect(supportsGooglePlayIap, isTrue);
    expect(supportsAppleIap, isFalse);
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    expect(supportsGooglePlayIap, isFalse);
    expect(supportsAppleIap, isTrue);
    debugDefaultTargetPlatformOverride = TargetPlatform.linux;
    expect(supportsGooglePlayIap, isFalse);
    expect(supportsAppleIap, isFalse);
  });

  group('server and store catalog', () {
    test('closed eight total tiers includes Google300GB not Apple2TB/5TB', () {
      final catalog =
          GooglePlayProviderCatalog.fromProviders(googleProvidersFixture());
      expect(catalog.quantities.values.toList(), [1, 2, 3, 4, 5, 6, 10, 20]);
      expect(catalog.accountToken, googleAccountToken);
      expect(catalog.toString(), isNot(contains(googleAccountToken)));
    });
    for (final mutation in <void Function(Map)>[
      (g) => g['account_token'] = 'Brain',
      (g) => g['base_plan_id'] = 'prepaid',
      (g) => g['products'][0]['quantity'] = 100,
      (g) => g['products'][0]['product_id'] = 'unverified.product',
      (g) => g['products'][0]['storage_entitlement_bytes'] = 1,
      (g) => g['products'][0]['billing_period'] = 'P1Y',
      (g) => g['products'].add(g['products'][0]),
    ]) {
      test('malformed/unknown catalog fails closed ${mutation.hashCode}', () {
        final data = googleProvidersFixture();
        mutation(data['google_play'] as Map);
        expect(() => GooglePlayProviderCatalog.fromProviders(data),
            throwsFormatException);
      });
    }
    test(
        'localized regular monthly base plan only, no introductory price inference',
        () async {
      final store = FakeGooglePlayStore()
        ..products = [
          googleProductFixture(),
          googleProductFixture(quantity: 2, offerId: 'trial'),
          googleProductFixture(quantity: 3, basePlan: 'annual'),
          googleProductFixture(quantity: 4, period: 'P1Y'),
          googleProductFixture(
              quantity: 5, recurrence: RecurrenceMode.nonRecurring),
          googleProductFixture(quantity: 6),
          googleProductFixture(quantity: 10, offerToken: ''),
        ];
      final service = GooglePlayIapService.forTesting(store: store);
      addTearDown(service.disposeForTesting);
      final catalog = await service.loadCatalog(
          GooglePlayProviderCatalog.fromProviders(googleProvidersFixture()));
      expect(catalog.products.keys.toList(), [1, 6]);
      expect(catalog.products[1]!.price, '£14.99');
      expect(store.queriedIds, googlePlayStorageProductIds.values.toSet());
    });
    test('store unavailable never offers a price or checkout', () async {
      final store = FakeGooglePlayStore()..available = false;
      final service = GooglePlayIapService.forTesting(store: store);
      addTearDown(service.disposeForTesting);
      final catalog = await service.loadCatalog(
          GooglePlayProviderCatalog.fromProviders(googleProvidersFixture()));
      expect(catalog.canPurchase, isFalse);
      expect(store.buys, 0);
    });
  });

  group('checkout and replacement', () {
    late FakeGooglePlayStore store;
    late GooglePlayIapService service;
    late GooglePlayProviderCatalog provider;
    setUp(() {
      store = FakeGooglePlayStore();
      service = GooglePlayIapService.forTesting(store: store);
      provider =
          GooglePlayProviderCatalog.fromProviders(googleProvidersFixture());
    });
    tearDown(() async {
      await service.disposeForTesting();
      await store.updates.close();
    });
    test(
        'one checkout uses obfuscated account and exact Play offer; duplicate tap no charge',
        () async {
      store.buyGate = Completer<bool>();
      final first = service.buy(
          provider: provider,
          product: googleProductFixture(),
          ownedPurchases: []);
      expect(
          await service.buy(
              provider: provider,
              product: googleProductFixture(),
              ownedPurchases: []),
          isFalse);
      store.buyGate!.complete(true);
      expect(await first, isTrue);
      expect(store.buys, 1);
      expect(store.lastBuy!.applicationUserName, googleAccountToken);
      expect(store.lastBuy!.offerToken, 'synthetic-offer-token');
      expect(store.lastBuy!.changeSubscriptionParam, isNull);
    });
    test('upgrade replaces actual old purchase with time proration', () async {
      final old = googlePurchaseFixture();
      expect(
          await service.buy(
              provider: provider,
              product: googleProductFixture(quantity: 6),
              ownedPurchases: [old],
              currentProductId: old.productID),
          isTrue);
      expect(store.lastBuy!.changeSubscriptionParam!.oldPurchaseDetails,
          same(old));
      expect(store.lastBuy!.changeSubscriptionParam!.replacementMode,
          ReplacementMode.withTimeProration);
    });
    test(
        'downgrade defers exact replacement, never stacks consumable quantities',
        () async {
      final old = googlePurchaseFixture(quantity: 6);
      await service.buy(
          provider: provider,
          product: googleProductFixture(),
          ownedPurchases: [old],
          currentProductId: old.productID);
      expect(store.lastBuy!.changeSubscriptionParam!.replacementMode,
          ReplacementMode.deferred);
    });
    for (final owned in [
      <GooglePlayPurchaseDetails>[],
      [googlePurchaseFixture(accountToken: googleOtherAccountToken)],
      [googlePurchaseFixture(accountToken: null)],
      [
        googlePurchaseFixture(),
        googlePurchaseFixture(quantity: 2, token: 'second')
      ],
    ]) {
      test(
          'missing/foreign/ambiguous actual replacement fails before charge ${owned.length}-${owned.hashCode}',
          () async {
        await expectLater(
            service.buy(
                provider: provider,
                product: googleProductFixture(quantity: 6),
                ownedPurchases: owned,
                currentProductId: googlePlayStorageProductIds[1]),
            throwsStateError);
        expect(store.buys, 0);
      });
    }
    test(
        'deferred new token with OLD product closes checkout and stays recoverable',
        () async {
      final old = googlePurchaseFixture(quantity: 6);
      await service.buy(
          provider: provider,
          product: googleProductFixture(),
          ownedPurchases: [old],
          currentProductId: old.productID);
      // Play keeps the OLD entitlement on the new token until renewal.
      store.updates.add(
          [googlePurchaseFixture(quantity: 6, token: 'replacement-token')]);
      expect(service.hasPendingStoreRequest, isFalse);
      expect(service.hasPendingActivation, isTrue);
      expect(store.finishes, 0);
    });
    test('unrelated cancellation never unlocks unresolved pending purchase',
        () async {
      service.initialize();
      store.updates
          .add([googlePurchaseFixture(status: PurchaseStatus.pending)]);
      store.updates.add([
        googlePurchaseFixture(
            quantity: 2, status: PurchaseStatus.canceled, token: 'other')
      ]);
      expect(service.hasPendingStoreRequest, isTrue);
      expect(
          await service.buy(
              provider: provider,
              product: googleProductFixture(quantity: 6),
              ownedPurchases: []),
          isFalse);
      expect(store.buys, 0);
    });
    test('canceled and error checkout terminal events unlock without finish',
        () async {
      await service.buy(
          provider: provider,
          product: googleProductFixture(),
          ownedPurchases: []);
      store.updates
          .add([googlePurchaseFixture(status: PurchaseStatus.canceled)]);
      expect(service.hasPendingStoreRequest, isFalse);
      expect(store.finishes, 0);
      store.updates.add([googlePurchaseFixture(status: PurchaseStatus.error)]);
      expect(service.hasPendingActivation, isFalse);
    });
    test(
        'launched checkout survives stream error and empty query; no second purchase',
        () async {
      final listener = service.transactions.listen((_) {}, onError: (_) {});
      addTearDown(listener.cancel);
      await service.buy(
          provider: provider,
          product: googleProductFixture(),
          ownedPurchases: []);
      store.updates.addError(StateError('Synthetic disconnect'));
      expect(service.hasPendingStoreRequest, isTrue);
      await service.queryOwnedPurchases(provider);
      expect(
          await service.buy(
              provider: provider,
              product: googleProductFixture(quantity: 6),
              ownedPurchases: []),
          isFalse);
      expect(store.buys, 1);
      expect(store.finishes, 0);
    });
    for (final status in [PurchaseStatus.canceled, PurchaseStatus.error]) {
      test(
          'real plugin blank base $status closes only active checkout; never finishes',
          () async {
        final events = <PurchaseDetails>[];
        final listener = service.transactions.listen(events.addAll);
        addTearDown(listener.cancel);
        await service.buy(
            provider: provider,
            product: googleProductFixture(),
            ownedPurchases: []);
        store.updates.add([googleEmptyCheckoutFixture(status)]);
        await Future<void>.delayed(Duration.zero);
        expect(service.hasPendingStoreRequest, isFalse);
        expect(events.single.status, status);
        expect(events.single.productID, googlePlayStorageProductIds[1]);
        expect(store.finishes, 0);
      });
    }
    test(
        'blank canceled/error without active checkout never resolves unrelated pending receipt',
        () async {
      service.initialize();
      store.updates.add(
          [googlePurchaseFixture(quantity: 6, status: PurchaseStatus.pending)]);
      store.updates.add([
        googleEmptyCheckoutFixture(PurchaseStatus.canceled),
        googleEmptyCheckoutFixture(PurchaseStatus.error)
      ]);
      expect(service.hasPendingStoreRequest, isTrue);
      expect(service.retainedPurchases.length, 1);
      expect(store.finishes, 0);
    });
    test(
        'blank purchased callback never becomes verified receipt or closes checkout',
        () async {
      await service.buy(
          provider: provider,
          product: googleProductFixture(),
          ownedPurchases: []);
      store.updates.add([googleEmptyCheckoutFixture(PurchaseStatus.purchased)]);
      expect(service.hasPendingStoreRequest, isTrue);
      expect(service.hasPendingActivation, isFalse);
      expect(store.finishes, 0);
    });
    test('base error with any nonblank receipt identity cannot close checkout',
        () async {
      final events = <PurchaseDetails>[];
      final listener = service.transactions.listen(events.addAll);
      addTearDown(listener.cancel);
      await service.buy(
          provider: provider,
          product: googleProductFixture(),
          ownedPurchases: []);
      for (final field in ['purchaseID', 'localData', 'serverData']) {
        store.updates.add([
          PurchaseDetails(
              purchaseID: field == 'purchaseID' ? 'possible-order' : '',
              productID: '',
              transactionDate: null,
              status: PurchaseStatus.error,
              verificationData: PurchaseVerificationData(
                  localVerificationData: field == 'localData' ? 'receipt' : '',
                  serverVerificationData: field == 'serverData' ? 'token' : '',
                  source: 'google_play'))
        ]);
        await Future<void>.delayed(Duration.zero);
        expect(service.hasPendingStoreRequest, isTrue);
      }
      expect(events, isEmpty);
      expect(
          await service.buy(
              provider: provider,
              product: googleProductFixture(quantity: 6),
              ownedPurchases: []),
          isFalse);
      expect(store.buys, 1);
      expect(store.finishes, 0);
    });
  });

  group('restore and completion', () {
    test('query empty owned purchases resolves and uses server correlator',
        () async {
      final store = FakeGooglePlayStore();
      final service = GooglePlayIapService.forTesting(store: store);
      addTearDown(service.disposeForTesting);
      final owned = await service.queryOwnedPurchases(
          GooglePlayProviderCatalog.fromProviders(googleProvidersFixture()));
      expect(owned, isEmpty);
      expect(store.lastAccountToken, googleAccountToken);
      expect(service.hasPendingStoreRequest, isFalse);
      expect(store.buys, 0);
    });
    test(
        'duplicate restore queries singleflight; unresolved queue survives later batch',
        () async {
      final store = FakeGooglePlayStore()
        ..queryGate = Completer<QueryPurchaseDetailsResponse>();
      final service = GooglePlayIapService.forTesting(store: store);
      addTearDown(service.disposeForTesting);
      final provider =
          GooglePlayProviderCatalog.fromProviders(googleProvidersFixture());
      final first = service.queryOwnedPurchases(provider),
          second = service.queryOwnedPurchases(provider);
      await Future<void>.delayed(Duration.zero);
      final old = googlePurchaseFixture();
      store.queryGate!
          .complete(QueryPurchaseDetailsResponse(pastPurchases: [old]));
      await first;
      await second;
      expect(store.queries, 1);
      store.updates.add([googlePurchaseFixture(quantity: 2, token: 'second')]);
      final replay = await service.transactions.first;
      expect(replay.length, 2);
    });
    test(
        'finish once for concurrent callbacks; malformed/pending never complete',
        () async {
      final store = FakeGooglePlayStore()..finishGate = Completer<void>();
      final service = GooglePlayIapService.forTesting(store: store);
      addTearDown(service.disposeForTesting);
      final purchase = googlePurchaseFixture();
      final first = service.finish(purchase), second = service.finish(purchase);
      store.finishGate!.complete();
      await first;
      await second;
      await service.finish(purchase);
      expect(store.finishes, 1);
      await expectLater(
          service.finish(googlePurchaseFixture(status: PurchaseStatus.pending)),
          throwsStateError);
      await expectLater(
          service.finish(googlePurchaseFixture(token: '')), throwsStateError);
      expect(store.finishes, 1);
    });
    test('finish failure retains transaction for next restore', () async {
      final store = FakeGooglePlayStore()..failFinish = true;
      final service = GooglePlayIapService.forTesting(store: store);
      addTearDown(service.disposeForTesting);
      service.initialize();
      final purchase = googlePurchaseFixture();
      store.updates.add([purchase]);
      await expectLater(service.finish(purchase), throwsStateError);
      expect(service.hasPendingActivation, isTrue);
      store.failFinish = false;
      await service.finish(purchase);
      expect(store.finishes, 2);
      expect(service.hasPendingActivation, isFalse);
    });
  });

  group('bounded verified recovery', () {
    const result = {
      'verified': true,
      'provider': 'google_play',
      'status': 'active',
      'acknowledged': true
    };
    test(
        'transient same-token verification retries3max, complete once, duplicates deduped',
        () async {
      var verifies = 0, finishes = 0;
      final recovery = GooglePlayPurchaseRecovery(delay: (_) async {});
      Future<GooglePlayRecoveryResult> recover() => recovery.recover(
          accountKey: 'session',
          transactionKey: 'same-token',
          isCurrent: () => true,
          verify: () async {
            verifies++;
            if (verifies < 3) {
              throw const GooglePlayPurchaseVerificationException(
                  statusCode: 503, code: 'google_play_verification_retry');
            }
            return result;
          },
          finish: () async => finishes++);
      expect((await recover()).handled, isTrue);
      expect((await recover()).handled, isFalse);
      expect(verifies, 3);
      expect(finishes, 1);
    });
    for (final error in [
      const GooglePlayPurchaseVerificationException(
          statusCode: 409, code: 'purchase_already_bound'),
      const GooglePlayPurchaseVerificationException(
          statusCode: 503, code: 'google_play_verification_unavailable'),
    ]) {
      test('ownership/configuration does not retry or finish ${error.code}',
          () async {
        var verifies = 0, finishes = 0;
        final recovery = GooglePlayPurchaseRecovery(delay: (_) async {});
        await expectLater(
            recovery.recover(
                accountKey: 'session',
                transactionKey: 'same',
                isCurrent: () => true,
                verify: () async {
                  verifies++;
                  throw error;
                },
                finish: () async => finishes++),
            throwsA(same(error)));
        expect(verifies, 1);
        expect(finishes, 0);
      });
    }
    for (final invalid in [
      {
        'verified': false,
        'provider': 'google_play',
        'acknowledged': true,
        'status': 'active'
      },
      {
        'verified': true,
        'provider': 'apple',
        'acknowledged': true,
        'status': 'active'
      },
      {
        'verified': true,
        'provider': 'google_play',
        'acknowledged': false,
        'status': 'active'
      },
      {
        'verified': true,
        'provider': 'google_play',
        'acknowledged': true,
        'status': 'pending'
      },
    ]) {
      test('unverified/unacknowledged/pending never finish ${invalid.hashCode}',
          () async {
        var finishes = 0;
        final recovery = GooglePlayPurchaseRecovery();
        await expectLater(
            recovery.recover(
                accountKey: 'session',
                transactionKey: 'same',
                isCurrent: () => true,
                verify: () async => invalid,
                finish: () async => finishes++),
            throwsA(isA<GooglePlayPurchaseVerificationException>()));
        expect(finishes, 0);
      });
    }
    test('session changes during verification retain receipt and never finish',
        () async {
      final gate = Completer<Map<String, dynamic>>();
      var current = true, finishes = 0;
      final recovery = GooglePlayPurchaseRecovery();
      final future = recovery.recover(
          accountKey: 'old',
          transactionKey: 'same',
          isCurrent: () => current,
          verify: () => gate.future,
          finish: () async => finishes++);
      current = false;
      gate.complete(result);
      await expectLater(
          future, throwsA(isA<GooglePlayPurchaseVerificationException>()));
      expect(finishes, 0);
    });
    for (final status in ['expired', 'refunded', 'revoked', 'canceled']) {
      test(
          'only server-verified terminal $status retires without financial completion',
          () async {
        var retired = 0, finished = 0;
        final recovery = GooglePlayPurchaseRecovery();
        final result = await recovery.recover(
            accountKey: 'session',
            transactionKey: 'old',
            isCurrent: () => true,
            verify: () async => {
                  'verified': true,
                  'provider': 'google_play',
                  'status': status,
                  'acknowledged': false
                },
            retireTerminal: () async => retired++,
            finish: () async => finished++);
        expect(result.handled, isTrue);
        expect(retired, 1);
        expect(finished, 0);
      });
    }
  });
}
