import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:in_app_review/in_app_review.dart';
import 'package:in_app_update/in_app_update.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

const kSVaultAppleId = 6800601455;
const kSVaultPackageId = 'com.svaultai.app';
final kSVaultAppleUrl =
    Uri.parse('https://apps.apple.com/app/id$kSVaultAppleId');

/// Only store-confirmed, device-compatible releases may block the app.
/// This is independent of the web commit marker and contains no vault data.
class NativeStoreUpdate {
  const NativeStoreUpdate(this.label);
  final String label;
}

List<int>? parseStoreVersion(String value) {
  if (!RegExp(r'^\d+\.\d+(?:\.\d+)?$').hasMatch(value)) return null;
  final parts = value.split('.').map(int.tryParse).toList();
  if (parts.any((part) => part == null || part > 1000000)) return null;
  return [...parts.cast<int>(), if (parts.length == 2) 0];
}

int? compareStoreVersions(String left, String right) {
  final a = parseStoreVersion(left);
  final b = parseStoreVersion(right);
  if (a == null || b == null) return null;
  for (var i = 0; i < 3; i++) {
    final result = a[i].compareTo(b[i]);
    if (result != 0) return result;
  }
  return 0;
}

NativeStoreUpdate? parseAppleStoreUpdate({
  required Object? response,
  required String installedVersion,
  required String systemVersion,
}) {
  if (response is! Map || response['results'] is! List) return null;
  final results = response['results'] as List;
  if (results.length != 1 || results.single is! Map) return null;
  final app = results.single as Map;
  if (app['trackId'] != kSVaultAppleId ||
      app['bundleId'] != kSVaultPackageId ||
      app['kind'] != 'software') {
    return null;
  }
  final version = app['version'];
  final minimumOS = app['minimumOsVersion'];
  if (version is! String || minimumOS is! String) return null;
  final newer = compareStoreVersions(version, installedVersion);
  final compatible = compareStoreVersions(systemVersion, minimumOS);
  if (newer == null || newer <= 0 || compatible == null || compatible < 0) {
    return null;
  }
  return NativeStoreUpdate(version);
}

abstract class NativeStoreGateway {
  Future<NativeStoreUpdate?> availableUpdate();
  Future<bool> openUpdate();
  Future<bool> reviewAvailable();
  Future<void> requestReview();
  void dispose() {}
}

class PlatformNativeStoreGateway implements NativeStoreGateway {
  PlatformNativeStoreGateway({http.Client? client})
      : _client = client ?? http.Client(),
        _ownsClient = client == null;
  final http.Client _client;
  final bool _ownsClient;
  static const _storefront = MethodChannel('com.svaultai.app/storefront');

  bool _playUpdateAllowed(AppUpdateInfo info) =>
      info.packageName == kSVaultPackageId &&
      info.immediateUpdateAllowed &&
      (info.updateAvailability == UpdateAvailability.updateAvailable ||
          info.updateAvailability ==
              UpdateAvailability.developerTriggeredUpdateInProgress);

  Future<Map<String, dynamic>?> _appleStoreInfo() => _storefront
      .invokeMapMethod<String, dynamic>('info')
      .timeout(const Duration(seconds: 5));

  @override
  Future<NativeStoreUpdate?> availableUpdate() async {
    if (kIsWeb) return null;
    if (defaultTargetPlatform == TargetPlatform.android) {
      final info = await InAppUpdate.checkForUpdate()
          .timeout(const Duration(seconds: 10));
      // Play eligibility is per-user, per-device and per-release track.
      if (_playUpdateAllowed(info)) {
        return const NativeStoreUpdate('the latest version');
      }
      return null;
    }
    if (defaultTargetPlatform != TargetPlatform.iOS) return null;
    final installed = await PackageInfo.fromPlatform();
    if (installed.packageName != kSVaultPackageId) return null;
    final storefront = await _appleStoreInfo();
    // Never infer the Apple Account country from the device language. Unknown
    // storefronts, TestFlight and simulators fail open rather than trap users.
    final country = storefront?['country'];
    final systemVersion = storefront?['systemVersion'];
    if (storefront?['productionReceipt'] != true ||
        country is! String ||
        !RegExp(r'^[A-Z]{2}$').hasMatch(country) ||
        systemVersion is! String) {
      return null;
    }
    final uri = Uri.https('itunes.apple.com', '/lookup', {
      'id': '$kSVaultAppleId',
      'country': country.toLowerCase(),
      '_': '${DateTime.now().millisecondsSinceEpoch}',
    });
    final response =
        await _client.get(uri, headers: const {'Cache-Control': 'no-cache'});
    if (response.statusCode != 200 || response.body.length > 200000) {
      return null;
    }
    return parseAppleStoreUpdate(
        response: jsonDecode(response.body),
        installedVersion: installed.version,
        systemVersion: systemVersion);
  }

  @override
  Future<bool> openUpdate() async {
    if (kIsWeb) return false;
    if (defaultTargetPlatform == TargetPlatform.android) {
      // AppUpdateInfo intents are single-use. Recheck immediately before every
      // attempt, including retries after cancellation or changed eligibility.
      final info = await InAppUpdate.checkForUpdate()
          .timeout(const Duration(seconds: 10));
      if (!_playUpdateAllowed(info)) return false;
      return await InAppUpdate.performImmediateUpdate() ==
          AppUpdateResult.success;
    }
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      if ((await _appleStoreInfo())?['productionReceipt'] != true) return false;
      return launchUrl(kSVaultAppleUrl, mode: LaunchMode.externalApplication);
    }
    return false;
  }

  @override
  Future<bool> reviewAvailable() async {
    if (kIsWeb) return false;
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      // The review plugin only checks OS support; TestFlight returns true but
      // cannot display a review. Never consume our cooldown for a beta build.
      if ((await _appleStoreInfo())?['productionReceipt'] != true) return false;
    } else if (defaultTargetPlatform != TargetPlatform.android) {
      return false;
    } else {
      final installed = await PackageInfo.fromPlatform();
      if (installed.packageName != kSVaultPackageId ||
          installed.installerStore != 'com.android.vending') {
        return false;
      }
    }
    return InAppReview.instance.isAvailable();
  }

  @override
  Future<void> requestReview() async {
    if (await reviewAvailable()) await InAppReview.instance.requestReview();
  }

  @override
  void dispose() {
    if (_ownsClient) _client.close();
  }
}

class NativeStoreController extends ChangeNotifier {
  NativeStoreController(this.gateway,
      {this.checkTimeout = const Duration(seconds: 10),
      this.openTimeout = const Duration(minutes: 5)});
  final NativeStoreGateway gateway;
  final Duration checkTimeout;
  final Duration openTimeout;
  NativeStoreUpdate? _update;
  bool _checking = false;
  bool _opening = false;
  bool _disposed = false;
  String? error;
  bool get opening => _opening;
  NativeStoreUpdate? get update => _update;
  bool get updateRequired => _update != null;

  Future<void> check() async {
    if (_disposed || _checking || _opening) return;
    _checking = true;
    try {
      final value = await gateway.availableUpdate().timeout(checkTimeout);
      if (_disposed) return;
      _update = value;
      error = null;
      notifyListeners();
    } catch (_) {
      // Store eligibility must be current. An offline, timed-out or withdrawn
      // update must not trap somebody outside their saved vault.
      if (!_disposed) {
        _update = null;
        notifyListeners();
      }
    } finally {
      _checking = false;
    }
  }

  Future<void> openUpdate() async {
    if (_disposed || _opening || !updateRequired) return;
    _opening = true;
    error = null;
    notifyListeners();
    try {
      if (!await gateway.openUpdate().timeout(openTimeout)) {
        error = 'The update did not finish. Please try again.';
        _update = null;
      }
    } catch (_) {
      error = 'The store could not open the update. Please try again.';
      _update = null;
    } finally {
      if (!_disposed) {
        _opening = false;
        notifyListeners();
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    gateway.dispose();
    super.dispose();
  }
}

/// Engagement counters only, on this device. No username, secret, rating,
/// feedback, account ID, or vault content is recorded or sent to a server.
class OccasionalReviewPolicy {
  OccasionalReviewPolicy(this.preferences, {DateTime Function()? now})
      : _now = now ?? DateTime.now;
  final SharedPreferences preferences;
  final DateTime Function() _now;
  static const _prefix = 'svaultai_native_review_v1_';
  bool _requesting = false;
  bool _started = false;

  Future<void> startSession() async {
    if (_started) return;
    _started = true;
    if (!preferences.containsKey('${_prefix}first')) {
      await preferences.setInt(
          '${_prefix}first', _now().millisecondsSinceEpoch);
    }
    await preferences.setInt('${_prefix}sessions',
        (preferences.getInt('${_prefix}sessions') ?? 0) + 1);
  }

  bool get eligible {
    final first = preferences.getInt('${_prefix}first');
    if (first == null || (preferences.getInt('${_prefix}sessions') ?? 0) < 3) {
      return false;
    }
    final current = _now().millisecondsSinceEpoch;
    if (current - first < const Duration(days: 7).inMilliseconds) return false;
    final last = preferences.getInt('${_prefix}last');
    if (last != null &&
        current - last < const Duration(days: 120).inMilliseconds) {
      return false;
    }
    final attempts = preferences.getStringList('${_prefix}attempts') ?? [];
    return attempts.where((value) {
          final timestamp = int.tryParse(value);
          return timestamp != null &&
              current - timestamp < const Duration(days: 365).inMilliseconds;
        }).length <
        3;
  }

  Future<void> maybeRequest(NativeStoreGateway gateway,
      {required bool Function() allowed}) async {
    if (_requesting || !allowed() || !eligible) return;
    _requesting = true;
    try {
      if (!await gateway
              .reviewAvailable()
              .timeout(const Duration(seconds: 5)) ||
          !allowed() ||
          !eligible) {
        return;
      }
      final current = _now().millisecondsSinceEpoch;
      final attempts = (preferences.getStringList('${_prefix}attempts') ?? [])
          .where((value) {
        final timestamp = int.tryParse(value);
        return timestamp != null &&
            current - timestamp < const Duration(days: 365).inMilliseconds;
      }).toList()
        ..add('$current');
      // Record the attempt BEFORE invoking the OS: platforms may intentionally
      // suppress the dialog and do not tell us whether somebody reviewed.
      if (!await preferences.setInt('${_prefix}last', current) ||
          !await preferences.setStringList('${_prefix}attempts', attempts) ||
          !allowed()) {
        return;
      }
      await gateway.requestReview().timeout(const Duration(seconds: 10));
    } catch (_) {
      // Review availability never changes access to any feature.
    } finally {
      _requesting = false;
    }
  }
}
