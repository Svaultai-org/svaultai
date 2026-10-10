import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vault_ai_frontend/services/native_store_experience.dart';
import 'package:vault_ai_frontend/ui/native_store_experience.dart';

class _Store extends NativeStoreGateway {
  NativeStoreUpdate? next;
  bool fail = false;
  bool failOpen = false;
  bool opened = true;
  int checks = 0, opens = 0, reviews = 0;
  Completer<bool>? reviewRead;
  Completer<NativeStoreUpdate?>? checkRead;
  Completer<bool>? openRead;
  @override
  Future<NativeStoreUpdate?> availableUpdate() async {
    checks++;
    if (fail) throw StateError('unavailable');
    if (checkRead != null) return checkRead!.future;
    return next;
  }

  @override
  Future<bool> openUpdate() async {
    opens++;
    if (failOpen) throw StateError('store unavailable');
    return openRead?.future ?? opened;
  }

  @override
  Future<bool> reviewAvailable() async => reviewRead?.future ?? true;
  @override
  Future<void> requestReview() async {
    reviews++;
  }
}

Map<String, dynamic> _apple(
        {String version = '1.0.22',
        String minimumOS = '13.0',
        String bundle = kSVaultPackageId,
        int track = kSVaultAppleId}) =>
    {
      'results': [
        {
          'trackId': track,
          'bundleId': bundle,
          'kind': 'software',
          'version': version,
          'minimumOsVersion': minimumOS,
        }
      ]
    };

class _PreservedChild extends StatefulWidget {
  const _PreservedChild();
  @override
  State<_PreservedChild> createState() => _PreservedChildState();
}

class _PreservedChildState extends State<_PreservedChild> {
  int count = 0;
  @override
  Widget build(BuildContext context) => Scaffold(
      body: Center(
          child: TextButton(
              onPressed: () => setState(() => count++),
              child: Text('Saved state $count'))));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const appleChannel = MethodChannel('com.svaultai.app/storefront');
  const playChannel = MethodChannel('de.ffuf.in_app_update/methods');
  const reviewChannel = MethodChannel('dev.britannio.in_app_review');
  setUp(() {
    PackageInfo.setMockInitialValues(
      appName: 'SVaultAI',
      packageName: kSVaultPackageId,
      version: '1.0.21',
      buildNumber: '63',
      buildSignature: '',
    );
  });
  tearDown(() {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    for (final channel in [appleChannel, playChannel, reviewChannel]) {
      messenger.setMockMethodCallHandler(channel, null);
    }
    debugDefaultTargetPlatformOverride = null;
  });

  test('numeric versions do not compare lexicographically', () {
    expect(compareStoreVersions('1.0.10', '1.0.9'), 1);
    expect(compareStoreVersions('1.2', '1.2.0'), 0);
    expect(compareStoreVersions('1.2.beta', '1.0.0'), isNull);
    expect(compareStoreVersions('99999999999999999999.0', '1.0'), isNull);
  });
  test('Apple update requires exact identity, newer release and compatible OS',
      () {
    NativeStoreUpdate? parse(Object? response, {String os = '26.5'}) =>
        parseAppleStoreUpdate(
            response: response, installedVersion: '1.0.21', systemVersion: os);
    expect(parse(_apple())?.label, '1.0.22');
    expect(parse(_apple(version: '1.0.21')), isNull);
    expect(parse(_apple(version: '1.0.19')), isNull);
    expect(parse(_apple(bundle: 'another.app')), isNull);
    expect(parse(_apple(track: 123)), isNull);
    expect(parse(_apple(minimumOS: '27.0')), isNull);
    expect(parse(_apple(), os: 'invalid'), isNull);
    expect(parse({'results': []}), isNull);
    expect(
        parse({
          'results': ['bad']
        }),
        isNull);
    expect(
        parse({
          'results': [..._apple()['results'], ..._apple()['results']]
        }),
        isNull);
  });
  test('store outage immediately releases a previously verified blocker',
      () async {
    final store = _Store()..fail = true;
    final controller = NativeStoreController(store);
    await controller.check();
    expect(controller.updateRequired, false);
    store.fail = false;
    store.next = const NativeStoreUpdate('1.0.22');
    await controller.check();
    expect(controller.updateRequired, true);
    store.fail = true;
    await controller.check();
    expect(controller.updateRequired, false);
    controller.dispose();
  });
  test('update refresh is single-flight and withdrawing release unblocks',
      () async {
    final store = _Store()..next = const NativeStoreUpdate('1.0.22');
    final controller = NativeStoreController(store);
    await Future.wait(
        [controller.check(), controller.check(), controller.check()]);
    expect(store.checks, 1);
    expect(controller.updateRequired, true);
    store.next = null;
    await controller.check();
    expect(controller.updateRequired, false);
    await controller.openUpdate();
    expect(store.opens, 0);
    controller.dispose();
  });
  for (final failure in ['false', 'throw', 'timeout']) {
    test('update opening $failure releases blocker without altering app data',
        () async {
      final store = _Store()..next = const NativeStoreUpdate('1.0.22');
      if (failure == 'false') store.opened = false;
      if (failure == 'throw') store.failOpen = true;
      if (failure == 'timeout') store.openRead = Completer<bool>();
      final controller = NativeStoreController(store,
          openTimeout: const Duration(milliseconds: 1));
      await controller.check();
      await Future.wait([controller.openUpdate(), controller.openUpdate()]);
      expect(store.opens, 1);
      expect(controller.updateRequired, false);
      expect(controller.opening, false);
      expect(controller.error, isNotNull);
      store.openRead?.complete(true);
      await Future<void>.delayed(Duration.zero);
      expect(controller.updateRequired, false);
      controller.dispose();
    });
  }
  test('timed-out check cannot reinstate a late update', () async {
    final store = _Store()..next = const NativeStoreUpdate('1.0.22');
    final controller = NativeStoreController(store,
        checkTimeout: const Duration(milliseconds: 1));
    await controller.check();
    expect(controller.updateRequired, true);
    store.checkRead = Completer<NativeStoreUpdate?>();
    await controller.check();
    expect(controller.updateRequired, false);
    store.checkRead!.complete(const NativeStoreUpdate('1.0.23'));
    await Future<void>.delayed(Duration.zero);
    expect(controller.updateRequired, false);
    controller.dispose();
  });
  test('disposing an outstanding check prevents late notification', () async {
    final store = _Store()..checkRead = Completer<NativeStoreUpdate?>();
    final controller = NativeStoreController(store);
    var notifications = 0;
    controller.addListener(() => notifications++);
    final checking = controller.check();
    controller.dispose();
    store.checkRead!.complete(const NativeStoreUpdate('1.0.22'));
    await checking;
    expect(notifications, 0);
    expect(controller.updateRequired, false);
  });
  test('Apple lookup uses account storefront and no vault credentials',
      () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            appleChannel,
            (_) async => {
                  'country': 'GB',
                  'systemVersion': '26.5',
                  'productionReceipt': true,
                });
    var calls = 0;
    final client = MockClient((request) async {
      calls++;
      expect(request.url.scheme, 'https');
      expect(request.url.host, 'itunes.apple.com');
      expect(request.url.path, '/lookup');
      expect(request.url.queryParameters['country'], 'gb');
      expect(request.url.queryParameters['id'], '$kSVaultAppleId');
      expect(request.url.queryParameters['_'], isNotEmpty);
      expect(request.headers['Cache-Control'], 'no-cache');
      expect(request.headers.keys.map((key) => key.toLowerCase()),
          isNot(contains('authorization')));
      expect(request.headers.keys.map((key) => key.toLowerCase()),
          isNot(contains('x-device-id')));
      return http.Response(jsonEncode(_apple()), 200);
    });
    final gateway = PlatformNativeStoreGateway(client: client);
    expect((await gateway.availableUpdate())?.label, '1.0.22');
    expect(calls, 1);
    client.close();
  });
  for (final info in <Map<String, dynamic>>[
    {'country': 'US', 'systemVersion': '26.5', 'productionReceipt': false},
    {'country': '', 'systemVersion': '26.5', 'productionReceipt': true},
    {'country': 'USA', 'systemVersion': '26.5', 'productionReceipt': true},
    {'country': 'US', 'systemVersion': '26.5'},
  ]) {
    test('unknown or beta Apple install cannot force an update: $info',
        () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(appleChannel, (_) async => info);
      var calls = 0;
      final client = MockClient((_) async {
        calls++;
        return http.Response(jsonEncode(_apple()), 200);
      });
      final gateway = PlatformNativeStoreGateway(client: client);
      expect(await gateway.availableUpdate(), isNull);
      expect(calls, 0);
      client.close();
    });
  }
  test('TestFlight and simulator review skip does not consume local quota',
      () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    SharedPreferences.setMockInitialValues({
      'svaultai_native_review_v1_first':
          DateTime(2026, 1, 1).millisecondsSinceEpoch,
      'svaultai_native_review_v1_sessions': 4,
    });
    final preferences = await SharedPreferences.getInstance();
    final policy =
        OccasionalReviewPolicy(preferences, now: () => DateTime(2026, 10, 9));
    var pluginCalls = 0;
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(
        appleChannel,
        (_) async => {
              'country': '',
              'systemVersion': '26.5',
              'productionReceipt': false,
            });
    messenger.setMockMethodCallHandler(reviewChannel, (_) async {
      pluginCalls++;
      return true;
    });
    final gateway = PlatformNativeStoreGateway();
    await policy.maybeRequest(gateway, allowed: () => true);
    expect(pluginCalls, 0);
    expect(policy.eligible, true);
    expect(preferences.containsKey('svaultai_native_review_v1_last'), false);
    gateway.dispose();
  });
  test('production Apple review uses only supported system request', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    final calls = <String>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(
        appleChannel, (_) async => {'productionReceipt': true});
    messenger.setMockMethodCallHandler(reviewChannel, (call) async {
      calls.add(call.method);
      return call.method == 'isAvailable' ? true : null;
    });
    final gateway = PlatformNativeStoreGateway();
    await gateway.requestReview();
    expect(calls, ['isAvailable', 'requestReview']);
    gateway.dispose();
  });
  for (final installer in <String?>[null, 'com.android.vending']) {
    test('Android review is limited to a Play-installed app: $installer',
        () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      PackageInfo.setMockInitialValues(
        appName: 'SVaultAI',
        packageName: kSVaultPackageId,
        version: '1.0.21',
        buildNumber: '63',
        buildSignature: '',
        installerStore: installer,
      );
      var calls = 0;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(reviewChannel, (_) async {
        calls++;
        return true;
      });
      final gateway = PlatformNativeStoreGateway();
      expect(
          await gateway.reviewAvailable(), installer == 'com.android.vending');
      expect(calls, installer == null ? 0 : 1);
      gateway.dispose();
    });
  }
  for (final reply in [
    http.Response('not JSON', 200),
    http.Response('offline', 503)
  ]) {
    test(
        'Apple lookup failure releases a prior verified update: ${reply.statusCode}',
        () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(
              appleChannel,
              (_) async => {
                    'country': 'US',
                    'systemVersion': '26.5',
                    'productionReceipt': true,
                  });
      var first = true;
      final client = MockClient((_) async =>
          first ? http.Response(jsonEncode(_apple()), 200) : reply);
      final controller =
          NativeStoreController(PlatformNativeStoreGateway(client: client));
      await controller.check();
      expect(controller.updateRequired, true);
      first = false;
      await controller.check();
      expect(controller.updateRequired, false);
      controller.dispose();
      client.close();
    });
  }
  Map<String, dynamic> playInfo(
          {bool allowed = true,
          int availability = 2,
          String package = kSVaultPackageId}) =>
      {
        'updateAvailability': availability,
        'immediateAllowed': allowed,
        'flexibleAllowed': false,
        'availableVersionCode': 64,
        'installStatus': 0,
        'packageName': package,
        'clientVersionStalenessDays': 2,
        'updatePriority': 4,
      };
  test('each Android update retry gets a fresh store intent', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    final calls = <String>[];
    var opens = 0;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(playChannel, (call) async {
      calls.add(call.method);
      if (call.method == 'checkForUpdate') return playInfo();
      opens++;
      if (opens == 1) throw PlatformException(code: 'USER_DENIED_UPDATE');
      return null;
    });
    final gateway = PlatformNativeStoreGateway();
    expect(await gateway.availableUpdate(), isNotNull);
    expect(await gateway.openUpdate(), false);
    expect(await gateway.openUpdate(), true);
    expect(calls, [
      'checkForUpdate',
      'checkForUpdate',
      'performImmediateUpdate',
      'checkForUpdate',
      'performImmediateUpdate'
    ]);
    gateway.dispose();
  });
  for (final info in [
    playInfo(allowed: false),
    playInfo(availability: 1),
    playInfo(package: 'another.app')
  ]) {
    test('changed Android eligibility prevents update launch: $info', () async {
      debugDefaultTargetPlatformOverride = TargetPlatform.android;
      final calls = <String>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(playChannel, (call) async {
        calls.add(call.method);
        return info;
      });
      final gateway = PlatformNativeStoreGateway();
      expect(await gateway.openUpdate(), false);
      expect(calls, ['checkForUpdate']);
      gateway.dispose();
    });
  }
  test('review requires age and sessions; once per 120 days and three per year',
      () async {
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    var now = DateTime(2026, 10, 9);
    OccasionalReviewPolicy policy() =>
        OccasionalReviewPolicy(preferences, now: () => now);
    var current = policy();
    await current.startSession();
    await current.startSession();
    expect(current.eligible, false);
    current = policy();
    await current.startSession();
    current = policy();
    await current.startSession();
    expect(current.eligible, false);
    now = now.add(const Duration(days: 7));
    expect(current.eligible, true);
    final store = _Store();
    await Future.wait([
      current.maybeRequest(store, allowed: () => true),
      current.maybeRequest(store, allowed: () => true)
    ]);
    expect(store.reviews, 1);
    expect(current.eligible, false);
    now = now.add(const Duration(days: 120));
    await current.maybeRequest(store, allowed: () => true);
    expect(store.reviews, 2);
    now = now.add(const Duration(days: 120));
    await current.maybeRequest(store, allowed: () => true);
    expect(store.reviews, 3);
    now = now.add(const Duration(days: 120));
    expect(current.eligible, false);
    now = now.add(const Duration(days: 6));
    expect(current.eligible, true);
    for (final key in preferences.getKeys()) {
      expect(key, startsWith('svaultai_native_review_v1_'));
    }
  });
  test('locking during review availability prevents the request', () async {
    SharedPreferences.setMockInitialValues({
      'svaultai_native_review_v1_first':
          DateTime(2026, 1, 1).millisecondsSinceEpoch,
      'svaultai_native_review_v1_sessions': 4,
    });
    final policy = OccasionalReviewPolicy(await SharedPreferences.getInstance(),
        now: () => DateTime(2026, 10, 9));
    final store = _Store()..reviewRead = Completer<bool>();
    var allowed = true;
    final future = policy.maybeRequest(store, allowed: () => allowed);
    allowed = false;
    store.reviewRead!.complete(true);
    await future;
    expect(store.reviews, 0);
    expect(policy.eligible, true);
  });
  testWidgets('mandatory gate preserves child state; unsafe route defers',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final store = _Store();
    final controller = NativeStoreController(store);
    var safe = true;
    await tester.pumpWidget(MaterialApp(
        home: NativeStoreExperience(
            enabled: true,
            controller: controller,
            updateAllowed: () => safe,
            reviewAllowed: () => false,
            child: const _PreservedChild())));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Saved state 0'));
    await tester.pump();
    final before = tester.state(find.byType(_PreservedChild));
    store.next = const NativeStoreUpdate('1.0.22');
    await controller.check();
    await tester.pump();
    expect(find.byKey(const Key('native_required_update')), findsOneWidget);
    expect(tester.state(find.byType(_PreservedChild)), same(before));
    expect(find.text('Saved state 1'), findsOneWidget);
    safe = false;
    await controller.check();
    await tester.pump();
    expect(find.byKey(const Key('native_required_update')), findsNothing);
    expect(tester.state(find.byType(_PreservedChild)), same(before));
    store.next = null;
    await controller.check();
    await tester.pump();
    expect(find.text('Saved state 1'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
  testWidgets('web/debug bypass does not call stores', (tester) async {
    final store = _Store();
    final controller = NativeStoreController(store);
    await tester.pumpWidget(MaterialApp(
        home: NativeStoreExperience(
            enabled: false,
            controller: controller,
            updateAllowed: () => true,
            reviewAllowed: () => true,
            child: const Text('Existing app'))));
    await tester.pump(const Duration(minutes: 10));
    expect(store.checks, 0);
    expect(store.reviews, 0);
    expect(find.text('Existing app'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
  testWidgets(
      'builder-level blocker protects Back and preserves Navigator routes',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final store = _Store();
    final controller = NativeStoreController(store);
    final observer = NativeStoreRouteObserver();
    final navigator = GlobalKey<NavigatorState>();
    await tester.pumpWidget(MaterialApp(
      navigatorKey: navigator,
      navigatorObservers: [observer],
      initialRoute: '/login',
      routes: {
        '/login': (_) => const Scaffold(body: Text('Login route')),
        '/chat': (_) => const _PreservedChild(),
      },
      builder: (context, child) => NativeStoreExperience(
        enabled: true,
        controller: controller,
        routeObserver: observer,
        updateAllowed: () => observer.updateAllowed,
        reviewAllowed: () => false,
        child: child!,
      ),
    ));
    await tester.pumpAndSettle();
    unawaited(navigator.currentState!.pushNamed('/chat'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Saved state 0'));
    await tester.pump();
    final childState = tester.state(find.byType(_PreservedChild));
    final navigatorState = navigator.currentState;
    store.next = const NativeStoreUpdate('1.0.22');
    await controller.check();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('native_required_update')), findsOneWidget);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(navigator.currentState, same(navigatorState));
    expect(tester.state(find.byType(_PreservedChild)), same(childState));
    expect(find.text('Saved state 1'), findsOneWidget);
    expect(find.text('Login route'), findsNothing);
    // An outage releases the overlay and its PopEntry, not app state.
    store.fail = true;
    await controller.check();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('native_required_update')), findsNothing);
    expect(tester.state(find.byType(_PreservedChild)), same(childState));
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('Login route'), findsOneWidget);
    expect(find.text('Saved state 1'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
  testWidgets('wallet, modal and closing transitions defer interruption',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final store = _Store();
    final controller = NativeStoreController(store);
    final observer = NativeStoreRouteObserver();
    final navigator = GlobalKey<NavigatorState>();
    await tester.pumpWidget(MaterialApp(
      navigatorKey: navigator,
      navigatorObservers: [observer],
      initialRoute: '/chat',
      routes: {
        '/chat': (_) => const Scaffold(body: Text('Main route')),
        '/wallet': (_) => const Scaffold(body: Text('Transaction route')),
      },
      builder: (context, child) => NativeStoreExperience(
        enabled: true,
        controller: controller,
        routeObserver: observer,
        updateAllowed: () => observer.updateAllowed,
        reviewAllowed: () => observer.reviewAllowed,
        child: child!,
      ),
    ));
    await tester.pumpAndSettle();
    unawaited(navigator.currentState!.pushNamed('/wallet'));
    await tester.pumpAndSettle();
    store.next = const NativeStoreUpdate('1.0.22');
    await controller.check();
    await tester.pump();
    expect(observer.updateAllowed, false);
    expect(observer.reviewAllowed, false);
    expect(find.byKey(const Key('native_required_update')), findsNothing);
    expect(find.text('Transaction route'), findsOneWidget);
    navigator.currentState!.pop();
    await tester.pump();
    expect(observer.updateAllowed, false);
    expect(find.byKey(const Key('native_required_update')), findsNothing);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('native_required_update')), findsOneWidget);
    // A real route-changing modal removes the blocker until it has closed.
    unawaited(showDialog<void>(
      context: navigator.currentContext!,
      builder: (_) => const AlertDialog(title: Text('Purchase confirmation')),
    ));
    await tester.pumpAndSettle();
    expect(observer.updateAllowed, false);
    expect(find.byKey(const Key('native_required_update')), findsNothing);
    expect(find.text('Purchase confirmation'), findsOneWidget);
    navigator.currentState!.pop();
    await tester.pump();
    expect(observer.reviewAllowed, false);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('native_required_update')), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
}
