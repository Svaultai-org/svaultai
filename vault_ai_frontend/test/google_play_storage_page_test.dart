import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/main.dart' show AppState;
import 'package:vault_ai_frontend/services/google_play_iap_service.dart';
import 'package:vault_ai_frontend/services/google_play_verification.dart';
import 'package:vault_ai_frontend/storage_page.dart';

import 'google_play_test_fixtures.dart';

class _BillingClient extends VaultAIClient {
  _BillingClient() : super(baseUrl: 'http://127.0.0.1:9');
  String source = 'none', state = 'ok';
  int blocks = 0, verifies = 0, reconciles = 0;
  List<String>? reconciledTokens;
  GooglePlayPurchaseVerificationException? verificationError;
  Completer<Map<String, dynamic>>? verificationGate;
  String verifiedStatus = 'active';
  @override
  Future<Map<String, dynamic>> getBillingProviders(
          {required String authToken}) async =>
      googleProvidersFixture();
  @override
  Future<Map<String, dynamic>> getGooglePlayBillingProviders(
          {required String authToken,
          bool Function()? responseIsCurrent}) async =>
      getBillingProviders(authToken: authToken);
  @override
  Future<Map<String, dynamic>> getGooglePlayBillingMe(
          {required String authToken,
          bool Function()? responseIsCurrent}) async =>
      getBillingMe(authToken: authToken);
  @override
  Future<Map<String, dynamic>> getBillingMe(
          {required String authToken}) async =>
      {
        'billing_state': state,
        'source': source,
        'provider': source,
        'status': blocks > 0 ? 'active' : 'none',
        'has_active_subscription': blocks > 0,
        'block_count': blocks,
        'purchased_bytes': blocks * 53687091200,
        'effective_limit_bytes': blocks > 0 ? blocks * 53687091200 : 1073741824,
        'included_bytes': 1073741824,
        'used_bytes': 0,
        'percent_used': 0.0,
        'account_type': 'individual',
        'self_service_max_blocks': 100,
        'block_bytes': 53687091200,
        'product_id': blocks > 0 ? googlePlayStorageProductIds[blocks] : null,
        'current_period_end': '2099-01-01T00:00:00Z',
      };
  @override
  Future<Map<String, dynamic>> verifyGooglePlayStoragePurchase(
      {required String authToken,
      required String purchaseToken,
      required String productId,
      bool Function()? responseIsCurrent}) async {
    verifies++;
    if (verificationError != null) throw verificationError!;
    if (verificationGate != null) return await verificationGate!.future;
    if (verifiedStatus != 'active') {
      source = 'none';
      blocks = 0;
      return {
        'verified': true,
        'provider': 'google_play',
        'product_id': productId,
        'status': verifiedStatus,
        'acknowledged': false,
        'transition': 'expired'
      };
    }
    source = 'google_play';
    blocks = 6;
    return {
      'verified': true,
      'provider': 'google_play',
      'product_id': productId,
      'status': 'active',
      'acknowledged': true,
      'transition': 'activated'
    };
  }

  @override
  Future<Map<String, dynamic>> reconcileGooglePlayStoragePurchases(
      {required String authToken,
      List<String> purchaseTokens = const [],
      bool Function()? responseIsCurrent}) async {
    reconciles++;
    reconciledTokens = purchaseTokens;
    return {
      'reconciled': true,
      'provider': 'google_play',
      'status': blocks > 0 ? 'active' : 'none',
      'has_active_subscription': blocks > 0,
      'current_purchase_count': purchaseTokens.length,
      'reconciled_count': purchaseTokens.length,
      'cleared_pending': false
    };
  }
}

Future<void> _mount(WidgetTester tester, AppState app, _BillingClient client,
    GooglePlayIapService service) async {
  tester.view.physicalSize = const Size(1200, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
  await tester.pumpWidget(ChangeNotifierProvider.value(
      value: app,
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        home: StoragePage(client: client, googlePlayService: service),
      )));
  await tester.pumpAndSettle();
  addTearDown(() => debugDefaultTargetPlatformOverride = null);
}

void main() {
  void androidWidgets(
      String description, Future<void> Function(WidgetTester) body) {
    testWidgets(description, (tester) async {
      try {
        await body(tester);
      } finally {
        await tester.pumpWidget(const SizedBox.shrink());
        debugDefaultTargetPlatformOverride = null;
      }
    });
  }

  late FakeGooglePlayStore store;
  late GooglePlayIapService service;
  late _BillingClient client;
  late AppState app;
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    store = FakeGooglePlayStore();
    service = GooglePlayIapService.forTesting(store: store);
    client = _BillingClient();
    app = AppState()..sessionToken = 'synthetic-session';
  });
  tearDown(() async {
    debugDefaultTargetPlatformOverride = null;
    await service.disposeForTesting();
    await store.updates.close();
    app.dispose();
  });

  androidWidgets(
      'Android actual buy picker includes300GB Play price; duplicate taps single checkout',
      (tester) async {
    await _mount(tester, app, client, service);
    expect(client.reconciles, 1);
    expect(client.reconciledTokens, isEmpty);
    expect(find.text('Buy storage'), findsOneWidget);
    expect(find.text('Restore Purchases'), findsOneWidget);
    await tester.tap(find.text('Buy storage'));
    await tester.pumpAndSettle();
    expect(find.textContaining('handled by Google Play'), findsOneWidget);
    expect(find.text('Additional storage  ·  300 GB'), findsOneWidget);
    await tester.tap(find.text('Additional storage  ·  300 GB'));
    await tester.pumpAndSettle();
    expect(store.buys, 1);
    expect(store.lastBuy!.productDetails.id, googlePlayStorageProductIds[6]);
    expect(store.lastBuy!.applicationUserName, googleAccountToken);
    expect(service.hasPendingStoreRequest, isTrue);
    expect(store.finishes, 0);
    expect(app.billingPurchasedBytes, 0);
  });

  androidWidgets(
      'Android callbacks verify then finish once and display only server quota',
      (tester) async {
    await _mount(tester, app, client, service);
    await tester.tap(find.text('Buy storage'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Additional storage  ·  300 GB'));
    await tester.pumpAndSettle();
    final purchase = googlePurchaseFixture(quantity: 6);
    store.updates.add([purchase, purchase]);
    await tester.pumpAndSettle();
    expect(client.verifies, 1);
    expect(store.finishes, 1);
    expect(app.billingEffectiveLimitBytes, 300 * 1024 * 1024 * 1024);
    expect(find.byType(AlertDialog), findsOneWidget);
    store.updates.add([purchase]);
    await tester.pumpAndSettle();
    expect(client.verifies, 1);
    expect(store.finishes, 1);
    expect(find.byType(AlertDialog), findsOneWidget);
  });

  androidWidgets(
      'automatic restore is silent, server quota authoritative, no checkout',
      (tester) async {
    store.owned = [googlePurchaseFixture(acknowledged: true)];
    await _mount(tester, app, client, service);
    expect(client.verifies, 1);
    expect(store.buys, 0);
    expect(find.byType(AlertDialog), findsNothing);
    expect(app.billingEffectiveLimitBytes, 300 * 1024 * 1024 * 1024);
    expect(find.textContaining('purchases checked'), findsOneWidget);
  });

  androidWidgets(
      'failed activation survives successful reconcile without false success notice',
      (tester) async {
    store.owned = [googlePurchaseFixture()];
    client.verificationError = const GooglePlayPurchaseVerificationException(
        statusCode: 409, code: 'purchase_already_bound');
    await _mount(tester, app, client, service);
    expect(client.verifies, 1);
    expect(client.reconciles, 1);
    expect(store.finishes, 0);
    expect(find.textContaining('still awaiting activation'), findsOneWidget);
    expect(find.textContaining('purchases checked'), findsNothing);
    expect(find.byType(AlertDialog), findsNothing);
    expect(service.hasPendingActivation, isTrue);
  });

  androidWidgets(
      'Restore zero purchases completes and foreground resumes recheck without dialogs',
      (tester) async {
    await _mount(tester, app, client, service);
    await tester.tap(find.text('Restore Purchases'));
    await tester.pumpAndSettle();
    expect(client.reconciles, 2);
    expect(store.buys, 0);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(client.reconciles, 3);
    expect(find.byType(AlertDialog), findsNothing);
  });

  androidWidgets(
      'empty Play query retries retained receipt and retires only verified expiry',
      (tester) async {
    store.owned = [googlePurchaseFixture()];
    client.verificationError = const GooglePlayPurchaseVerificationException(
        statusCode: 503, code: 'google_play_verification_unavailable');
    await _mount(tester, app, client, service);
    expect(service.hasPendingActivation, isTrue);
    expect(store.finishes, 0);
    store.owned = [];
    client.verificationError = null;
    client.verifiedStatus = 'expired';
    await tester.tap(find.text('Restore Purchases'));
    await tester.pumpAndSettle();
    expect(client.verifies, 2);
    expect(service.hasPendingActivation, isFalse);
    expect(store.finishes, 0);
    expect(store.buys, 0);
    expect(app.billingPurchasedBytes, 0);
    expect(find.textContaining('still awaiting activation'), findsNothing);
    store.updates.add([googlePurchaseFixture()]);
    await tester.pumpAndSettle();
    expect(service.hasPendingActivation, isFalse);
    expect(client.verifies, 2);
    expect(store.finishes, 0);
    await tester.tap(find.text('Restore Purchases'));
    await tester.pumpAndSettle();
    expect(service.hasPendingActivation, isFalse);
    expect(store.finishes, 0);
  });

  androidWidgets(
      'retained pending rechecks on empty query; verified canceled unlocks without ACK',
      (tester) async {
    store.owned = [googlePurchaseFixture(status: PurchaseStatus.pending)];
    client.verificationError = const GooglePlayPurchaseVerificationException(
        statusCode: 503, code: 'google_play_verification_unavailable');
    await _mount(tester, app, client, service);
    expect(service.hasPendingStoreRequest, isTrue);
    expect(store.finishes, 0);
    store.owned = [];
    client.verificationError = null;
    client.verifiedStatus = 'canceled';
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(service.hasPendingStoreRequest, isFalse);
    expect(service.hasPendingActivation, isFalse);
    expect(store.finishes, 0);
    expect(store.buys, 0);
    expect(app.billingPurchasedBytes, 0);
  });

  androidWidgets(
      'real blank Google cancellation unblocks Android Buy without success or ACK',
      (tester) async {
    await _mount(tester, app, client, service);
    await tester.tap(find.text('Buy storage'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Additional storage  ·  300 GB'));
    await tester.pumpAndSettle();
    store.updates.add([googleEmptyCheckoutFixture(PurchaseStatus.canceled)]);
    await tester.pumpAndSettle();
    expect(service.hasPendingStoreRequest, isFalse);
    expect(client.verifies, 0);
    expect(store.finishes, 0);
    expect(find.byType(AlertDialog), findsNothing);
  });

  androidWidgets(
      'pending payment grants nothing, cancels without finish, can restore on resume',
      (tester) async {
    await _mount(tester, app, client, service);
    store.updates.add([googlePurchaseFixture(status: PurchaseStatus.pending)]);
    await tester.pumpAndSettle();
    expect(client.verifies, 0);
    expect(store.finishes, 0);
    expect(find.textContaining('Payment is pending'), findsOneWidget);
    expect(app.billingPurchasedBytes, 0);
    store.updates.add([googlePurchaseFixture(status: PurchaseStatus.canceled)]);
    await tester.pumpAndSettle();
    expect(store.finishes, 0);
    expect(find.byType(AlertDialog), findsNothing);
  });

  androidWidgets('active Apple owner cannot initiate Google checkout',
      (tester) async {
    client.source = 'apple';
    client.blocks = 1;
    await _mount(tester, app, client, service);
    await tester.tap(find.text('Upgrade storage'));
    await tester.pumpAndSettle();
    expect(find.text('Subscription managed by Apple'), findsOneWidget);
    expect(store.buys, 0);
  });

  androidWidgets(
      'billing safe_default cannot buy even though free quota renders',
      (tester) async {
    client.state = 'safe_default';
    await _mount(tester, app, client, service);
    await tester.tap(find.text('Buy storage'));
    await tester.pumpAndSettle();
    expect(store.buys, 0);
    expect(find.text('Storage verification unavailable'), findsOneWidget);
  });

  androidWidgets(
      'vault changes during verification never finish or apply old entitlement',
      (tester) async {
    await _mount(tester, app, client, service);
    client.verificationGate = Completer<Map<String, dynamic>>();
    store.updates.add([googlePurchaseFixture()]);
    await tester.pump();
    app.sessionToken = 'new-synthetic-session';
    client.verificationGate!.complete({
      'verified': true,
      'provider': 'google_play',
      'status': 'active',
      'acknowledged': true
    });
    await tester.pumpAndSettle();
    expect(store.finishes, 0);
    expect(app.billingPurchasedBytes, 0);
    expect(service.hasPendingActivation, isTrue);
    expect(find.byType(AlertDialog), findsNothing);
  });
}
