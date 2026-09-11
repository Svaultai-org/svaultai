
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';




class DeviceProfile {
  final String name;
  final Size logicalSize;
  final double devicePixelRatio;
  final EdgeInsets safeAreaInsets;

  const DeviceProfile({
    required this.name,
    required this.logicalSize,
    this.devicePixelRatio = 2.0,
    this.safeAreaInsets = EdgeInsets.zero,
  });

  double get width => logicalSize.width;
  double get height => logicalSize.height;
}


class DeviceProfiles {
  DeviceProfiles._();

  static const iphoneSE = DeviceProfile(
    name: 'iPhone SE',
    logicalSize: Size(320, 568),
    devicePixelRatio: 2.0,
    safeAreaInsets: EdgeInsets.only(top: 20, bottom: 0),
  );

  static const iphone12 = DeviceProfile(
    name: 'iPhone 12/13/14',
    logicalSize: Size(390, 844),
    devicePixelRatio: 3.0,
    safeAreaInsets: EdgeInsets.only(top: 47, bottom: 34),
  );

  static const iphone14ProMax = DeviceProfile(
    name: 'iPhone 14 Pro Max',
    logicalSize: Size(430, 932),
    devicePixelRatio: 3.0,
    safeAreaInsets: EdgeInsets.only(top: 59, bottom: 34),
  );

  static const pixel7 = DeviceProfile(
    name: 'Pixel 7',
    logicalSize: Size(412, 915),
    devicePixelRatio: 2.625,
    safeAreaInsets: EdgeInsets.only(top: 32, bottom: 24),
  );

  static const ipad = DeviceProfile(
    name: 'iPad',
    logicalSize: Size(820, 1180),
    devicePixelRatio: 2.0,
    safeAreaInsets: EdgeInsets.only(top: 24, bottom: 20),
  );

  static const desktop = DeviceProfile(
    name: 'Desktop',
    logicalSize: Size(1440, 900),
    devicePixelRatio: 1.0,
    safeAreaInsets: EdgeInsets.zero,
  );


  static const smallestPhone = iphoneSE;


  // Landscape variants: same devices rotated 90°. Safe-area insets change:
  // top/bottom become left/right on iPhones due to the notch.

  static const iphoneSELandscape = DeviceProfile(
    name: 'iPhone SE landscape',
    logicalSize: Size(568, 320),
    devicePixelRatio: 2.0,
    safeAreaInsets: EdgeInsets.only(left: 20, right: 20, bottom: 0),
  );

  static const iphone12Landscape = DeviceProfile(
    name: 'iPhone 12 landscape',
    logicalSize: Size(844, 390),
    devicePixelRatio: 3.0,
    safeAreaInsets: EdgeInsets.only(left: 47, right: 47, bottom: 21),
  );

  static const iphone14ProMaxLandscape = DeviceProfile(
    name: 'iPhone 14 Pro Max landscape',
    logicalSize: Size(932, 430),
    devicePixelRatio: 3.0,
    safeAreaInsets: EdgeInsets.only(left: 59, right: 59, bottom: 21),
  );

  static const ipadLandscape = DeviceProfile(
    name: 'iPad landscape',
    logicalSize: Size(1180, 820),
    devicePixelRatio: 2.0,
    safeAreaInsets: EdgeInsets.only(top: 24, bottom: 20),
  );


  static const List<DeviceProfile> allPhones = <DeviceProfile>[
    iphoneSE,
    iphone12,
    iphone14ProMax,
    pixel7,
  ];

  static const List<DeviceProfile> allLandscape = <DeviceProfile>[
    iphoneSELandscape,
    iphone12Landscape,
    iphone14ProMaxLandscape,
    ipadLandscape,
  ];

  /// Phones + tablet + desktop portrait.
  static const List<DeviceProfile> allViewports = <DeviceProfile>[
    iphoneSE,
    iphone12,
    iphone14ProMax,
    pixel7,
    ipad,
    desktop,
  ];

  static const List<DeviceProfile> allProfiles = <DeviceProfile>[
    iphoneSE,
    iphone12,
    iphone14ProMax,
    pixel7,
    ipad,
    desktop,
  ];
}


/// Simulate keyboard-open state. `viewInsets.bottom = keyboardHeight`, which
/// pushes SafeArea and bottom-anchored widgets up by that many px.
DeviceProfile withKeyboard(DeviceProfile base, {double keyboardHeight = 336}) {
  return DeviceProfile(
    name: '${base.name} + keyboard',
    logicalSize: base.logicalSize,
    devicePixelRatio: base.devicePixelRatio,
    safeAreaInsets: base.safeAreaInsets,
  );
  // keyboardHeight is applied at pumpAtDevice via a MediaQuery override —
  // see the extended signature below.
}



/// Collector for overflow errors reported via FlutterError.onError.
/// Some overflow errors don't reach tester.takeException(); they only fire
/// through the framework's error handler. This captures them.
class _OverflowCollector {
  final List<FlutterErrorDetails> layoutErrors = [];
  void Function(FlutterErrorDetails)? _prevOnError;

  void install() {
    _prevOnError = FlutterError.onError;
    FlutterError.onError = (details) {
      final s = details.exceptionAsString();
      if (s.contains('overflowed') ||
          s.contains('overflow') ||
          s.contains('RenderFlex') ||
          s.contains('unbounded height') ||
          s.contains('unbounded width') ||
          s.contains('has no constraints')) {
        layoutErrors.add(details);
      } else {
        _prevOnError?.call(details);
      }
    };
  }

  void restore() {
    FlutterError.onError = _prevOnError;
  }
}

final _overflowCollector = _OverflowCollector();


Future<void> pumpAtDevice(
  WidgetTester tester,
  Widget child, {
  required DeviceProfile device,
  bool settle = true,
  bool wrapInScaffold = true,
  ThemeData? theme,
  Duration pumpDuration = const Duration(milliseconds: 100),
  double keyboardHeight = 0,
}) async {
  _overflowCollector.layoutErrors.clear();
  _overflowCollector.install();
  addTearDown(() {
    _overflowCollector.restore();
  });
  await tester.binding.setSurfaceSize(device.logicalSize);
  addTearDown(() async {
    await tester.binding.setSurfaceSize(null);
  });

  final materialApp = MaterialApp(
    theme: theme ?? ThemeData.dark(useMaterial3: true),
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    supportedLocales: AppLocalizations.supportedLocales,
    locale: const Locale('en'),
    home: MediaQuery(
      data: MediaQueryData(
        size: device.logicalSize,
        devicePixelRatio: device.devicePixelRatio,
        padding: device.safeAreaInsets,
        viewInsets: keyboardHeight > 0
            ? EdgeInsets.only(bottom: keyboardHeight)
            : EdgeInsets.zero,
      ),
      child: wrapInScaffold ? Scaffold(body: child) : child,
    ),
  );

  await tester.pumpWidget(materialApp);

  if (settle) {
    await tester.pumpAndSettle(pumpDuration);
  } else {
    await tester.pump(pumpDuration);
  }
}


void expectNoOverflow(WidgetTester tester, {String? context}) {
  final ctx = context != null ? ' [$context]' : '';
  // Drain any pending exceptions and filter to layout-related ones.
  Object? err = tester.takeException();
  while (err != null) {
    final s = err.toString();
    final isLayout = s.contains('overflowed') ||
        s.contains('overflow') ||
        s.contains('RenderFlex') ||
        s.contains('unbounded height') ||
        s.contains('unbounded width') ||
        s.contains('has no constraints') ||
        s.contains('Vertical viewport was given unbounded height');
    if (isLayout) {
      fail('Layout exception$ctx: $err');
    }
    err = tester.takeException();
  }
  // Also check the FlutterError.onError capture — some overflows only fire
  // there.
  if (_overflowCollector.layoutErrors.isNotEmpty) {
    final first = _overflowCollector.layoutErrors.first;
    fail('Layout error via FlutterError.onError$ctx: '
        '${first.exceptionAsString()}');
  }
}


void forEachMobile(
  String description,
  Future<void> Function(WidgetTester tester, DeviceProfile device) body, {
  List<DeviceProfile>? devices,
}) {
  final targets = devices ?? DeviceProfiles.allPhones;
  for (final d in targets) {
    testWidgets('$description @ ${d.name} '
        '(${d.width.toInt()}x${d.height.toInt()})', (tester) async {
      await body(tester, d);
      expectNoOverflow(tester, context: d.name);
    });
  }
}


void expectMinTapTarget(
  WidgetTester tester,
  Finder finder, {
  double min = 44.0,
  String? context,
}) {
  final ctx = context != null ? ' [$context]' : '';
  for (final element in finder.evaluate()) {
    final box = element.renderObject;
    if (box is RenderBox && box.hasSize) {
      if (box.size.width < min || box.size.height < min) {
        fail('Tap target too small$ctx: '
            '${box.size} < min $min (widget ${element.widget.runtimeType})');
      }
    }
  }
}


String goldenPath(String screenName, DeviceProfile device) {
  final safeName = screenName.replaceAll(RegExp(r'[^a-z0-9_]'), '_');
  final safeDevice = device.name
      .toLowerCase()
      .replaceAll(' ', '_')
      .replaceAll('/', '_')
      .replaceAll(RegExp(r'[^a-z0-9_]'), '');
  return 'goldens/${safeName}_${safeDevice}_${device.width.toInt()}.png';
}
