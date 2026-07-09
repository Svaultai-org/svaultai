

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:vault_ai_frontend/main.dart';

const int _oneGigabyte    = 1024 * 1024 * 1024;          
const int _fiftyGigabytes = 50 * 1024 * 1024 * 1024;     
const int _oneHundredGigabytes = 100 * 1024 * 1024 * 1024; 

void main() {
  
  
  group('AppState.effectiveStorageLimitBytes', () {
    test('returns billing limit when /billing/me has loaded', () {
      final s = AppState();
      s.billingEffectiveLimitBytes = _oneHundredGigabytes;
      s.storageLimitBytes          = _oneGigabyte; 
      expect(s.effectiveStorageLimitBytes, _oneHundredGigabytes);
    });

    test('falls back to vault-stats limit when billing has not loaded yet',
        () {
      final s = AppState();
      s.billingEffectiveLimitBytes = 0;             
      s.storageLimitBytes          = _fiftyGigabytes;
      expect(s.effectiveStorageLimitBytes, _fiftyGigabytes);
    });

    test('falls back to 1 GB constant when neither source is set', () {
      final s = AppState();
      s.billingEffectiveLimitBytes = 0;
      s.storageLimitBytes          = 0;
      expect(s.effectiveStorageLimitBytes, _oneGigabyte);
    });

    test('billing wins even when stats limit is non-zero', () {
      
      
      final s = AppState();
      s.billingEffectiveLimitBytes = _oneHundredGigabytes;
      s.storageLimitBytes          = _oneGigabyte;
      expect(s.effectiveStorageLimitBytes, _oneHundredGigabytes);
      
      expect(s.effectiveStorageLimitBytes, isNot(_oneGigabyte));
    });

    test('does not stack billing on top of stats — paid replaces free',
        () {
      
      
      final s = AppState();
      s.billingEffectiveLimitBytes = _fiftyGigabytes;
      s.billingIncludedBytes       = _oneGigabyte;
      s.storageLimitBytes          = _oneGigabyte;
      expect(s.effectiveStorageLimitBytes, _fiftyGigabytes);
      
      expect(s.effectiveStorageLimitBytes,
             isNot(_fiftyGigabytes + _oneGigabyte));
    });
  });

  
  group('AppState.planLabel', () {
    test('returns "Free Vault Plan" pre-load (but surfaces must NOT '
         'render it during this window — they gate on isBillingLoading)', () {
      
      
      final s = AppState();
      expect(s.billingLoadState, BillingLoadState.initial);
      expect(s.planLabel, 'Free Vault Plan');
    });

    test('shows "Free Vault Plan" when block_count == 0', () {
      final s = AppState();
      s.billingBlockCount     = 0;
      s.billingPurchasedBytes = 0;
      s.billingIncludedBytes  = _oneGigabyte;
      expect(s.planLabel, 'Free Vault Plan');
    });

    test('shows "50 GB Storage Plan" when 1 block is purchased', () {
      final s = AppState();
      s.billingBlockCount     = 1;
      s.billingPurchasedBytes = _fiftyGigabytes;
      expect(s.planLabel, '50 GB Storage Plan');
    });

    test('shows "100 GB Storage Plan" when 2 blocks are purchased '
         '(the production case)', () {
      final s = AppState();
      s.billingBlockCount     = 2;
      s.billingPurchasedBytes = _oneHundredGigabytes;
      expect(s.planLabel, '100 GB Storage Plan');
    });

    test('shows "Free Vault Plan" when subscription expired (purchased '
         'collapsed to 0)', () {
      
      
      final s = AppState();
      s.billingBlockCount     = 1;
      s.billingPurchasedBytes = 0;
      expect(s.planLabel, 'Free Vault Plan');
    });
  });

  
  group('AppState.resetLocalState', () {
    test('clears billing fields so plan ghosting cannot cross sessions',
        () async {
      
      
      TestWidgetsFlutterBinding.ensureInitialized();
      SharedPreferences.setMockInitialValues({});

      final s = AppState();
      s.billingEffectiveLimitBytes = _oneHundredGigabytes;
      s.billingBlockCount          = 2;
      s.billingPurchasedBytes      = _oneHundredGigabytes;
      s.billingIncludedBytes       = _oneGigabyte;

      await s.resetLocalState();

      expect(s.billingEffectiveLimitBytes, 0);
      expect(s.billingBlockCount,          0);
      expect(s.billingPurchasedBytes,      0);
      expect(s.billingIncludedBytes,       0);

      
      expect(s.effectiveStorageLimitBytes, _oneGigabyte);
      expect(s.planLabel,                  'Free Vault Plan');
    });

    test('clears billingLoadState/billingLoadError so a fresh sign-in '
         'does not inherit prior session state', () async {
      
      
      TestWidgetsFlutterBinding.ensureInitialized();
      SharedPreferences.setMockInitialValues({});

      final s = AppState();
      s.billingLoadState = BillingLoadState.loaded;
      s.billingLoadError = 'some prior error';

      await s.resetLocalState();

      expect(s.billingLoadState, BillingLoadState.initial);
      expect(s.billingLoadError, isNull);
      expect(s.isBillingLoaded,  isFalse);
      expect(s.isBillingLoading, isTrue);   
      expect(s.isBillingError,   isFalse);
    });
  });

  
  group('AppState.billingLoadState', () {
    test('initial state is "initial" and reads as loading (not loaded)', () {
      
      
      final s = AppState();
      expect(s.billingLoadState, BillingLoadState.initial);
      expect(s.isBillingLoading, isTrue);
      expect(s.isBillingLoaded,  isFalse);
      expect(s.isBillingError,   isFalse);
    });

    test('loaded state is the only one that flips isBillingLoaded to true',
        () {
      final s = AppState();

      s.billingLoadState = BillingLoadState.loading;
      expect(s.isBillingLoading, isTrue);
      expect(s.isBillingLoaded,  isFalse);

      s.billingLoadState = BillingLoadState.error;
      expect(s.isBillingError,   isTrue);
      expect(s.isBillingLoaded,  isFalse);
      expect(s.isBillingLoading, isFalse);

      s.billingLoadState = BillingLoadState.loaded;
      expect(s.isBillingLoaded,  isTrue);
      expect(s.isBillingLoading, isFalse);
      expect(s.isBillingError,   isFalse);
    });

    test('isBillingLoading covers BOTH initial AND loading', () {
      
      
      final s = AppState();
      s.billingLoadState = BillingLoadState.initial;
      expect(s.isBillingLoading, isTrue,
        reason: 'initial state must read as loading for the surface card');
      s.billingLoadState = BillingLoadState.loading;
      expect(s.isBillingLoading, isTrue);
    });

    test('only one helper is true at any time — they are mutually exclusive',
        () {
      
      
      final s = AppState();
      for (final st in BillingLoadState.values) {
        s.billingLoadState = st;
        final trues = [
          s.isBillingLoading,
          s.isBillingLoaded,
          s.isBillingError,
        ].where((b) => b).length;
        expect(trues, 1,
          reason: 'exactly one of isBilling{Loading,Loaded,Error} must be '
                  'true (state=$st)');
      }
    });
  });

  
  group('AppState.retryBilling', () {
    test('exists as a no-arg method (Retry button binds to it)', () {
      
      
      final s = AppState();
      
      
      final Future<void> Function() retry = s.retryBilling;
      expect(retry, isNotNull);
    });
  });

  
  group('AppState.applyBillingPayload', () {
    test(
        'merges the four billing fields, flips state to loaded, '
        'and notifies listeners', () {
      final s = AppState();
      var notifyCount = 0;
      s.addListener(() => notifyCount++);

      
      s.applyBillingPayload(<String, dynamic>{
        'effective_limit_bytes': 4 * 50 * 1024 * 1024 * 1024,
        'block_count':           4,
        'purchased_bytes':       4 * 50 * 1024 * 1024 * 1024,
        'included_bytes':        1024 * 1024 * 1024,
      });

      expect(s.billingBlockCount, 4);
      expect(s.billingEffectiveLimitBytes, 4 * 50 * 1024 * 1024 * 1024);
      expect(s.billingPurchasedBytes,      4 * 50 * 1024 * 1024 * 1024);
      expect(s.billingIncludedBytes,       1024 * 1024 * 1024);
      expect(s.billingLoadState, BillingLoadState.loaded);
      expect(s.isBillingLoaded, isTrue);
      expect(s.billingLoadError, isNull);
      expect(notifyCount, 1,
          reason: 'applyBillingPayload must notifyListeners exactly once '
                  'per call so the Settings card and dashboard hero '
                  'rebuild against the new entitlement');
    });

    test(
        'preserves last-known values for missing keys '
        '(partial payload safe)', () {
      
      
      final s = AppState();
      s.applyBillingPayload(<String, dynamic>{
        'effective_limit_bytes': 100 * 1024 * 1024 * 1024,
        'block_count':           2,
        'purchased_bytes':       100 * 1024 * 1024 * 1024,
        'included_bytes':        1024 * 1024 * 1024,
      });
      
      
      s.applyBillingPayload(<String, dynamic>{
        'effective_limit_bytes': 150 * 1024 * 1024 * 1024,
      });
      expect(s.billingEffectiveLimitBytes, 150 * 1024 * 1024 * 1024);
      expect(s.billingBlockCount, 2,
          reason: 'block_count missing → keep last-known');
      expect(s.billingPurchasedBytes, 100 * 1024 * 1024 * 1024,
          reason: 'purchased_bytes missing → keep last-known');
      expect(s.billingLoadState, BillingLoadState.loaded);
    });

    test(
        'after a prior error, applyBillingPayload clears the error '
        'string and flips loaded', () {
      
      
      final s = AppState();
      s.billingLoadState = BillingLoadState.error;
      s.billingLoadError = 'transient blip';
      s.applyBillingPayload(<String, dynamic>{
        'effective_limit_bytes': 50 * 1024 * 1024 * 1024,
        'block_count':           1,
        'purchased_bytes':       50 * 1024 * 1024 * 1024,
        'included_bytes':        1024 * 1024 * 1024,
      });
      expect(s.billingLoadState, BillingLoadState.loaded);
      expect(s.billingLoadError, isNull);
      expect(s.isBillingError, isFalse);
    });
  });

  
  group('billing load-state gating in surface code', () {
    late String mainSource;

    setUpAll(() {
      mainSource = File('lib/main.dart').readAsStringSync();
    });

    test('Settings Current plan card branches on app.isBillingLoading', () {
      
      
      final headerIdx = mainSource.indexOf("'Current plan'");
      expect(headerIdx, greaterThan(-1),
          reason: 'Settings "Current plan" header must exist');
      
      
      final window = mainSource.substring(
        headerIdx,
        (headerIdx + 3000).clamp(0, mainSource.length),
      );
      expect(window, contains('app.isBillingLoading'),
          reason: 'Current plan card must gate on isBillingLoading');
      expect(window, contains('_BillingLoadingCard'),
          reason: 'Current plan card must render the skeleton');
      expect(window, contains('app.isBillingError'),
          reason: 'Current plan card must handle the error state');
      expect(window, contains('_BillingErrorCard'),
          reason: 'Current plan error card must render with Retry');
      expect(window, contains('app.retryBilling'),
          reason: 'Retry button must wire to app.retryBilling');
    });

    test('Vault overview hero card branches on app.isBillingLoading', () {
      
      
      final heroIdx = mainSource.indexOf('Widget _buildDashboardHome');
      expect(heroIdx, greaterThan(-1),
          reason: '_buildDashboardHome must exist');
      final window = mainSource.substring(
        heroIdx,
        (heroIdx + 5000).clamp(0, mainSource.length),
      );
      expect(window, contains('app.isBillingLoading'),
          reason: 'Vault overview hero must gate on isBillingLoading');
      expect(window, contains('_BillingLoadingCard'));
      expect(window, contains('app.isBillingError'));
      expect(window, contains('_BillingErrorCard'));
    });

    test('_checkUploadSize skips the headroom check until billing is loaded',
        () {
      
      
      final idx = mainSource.indexOf('_checkUploadSize(int sizeBytes)');
      expect(idx, greaterThan(-1),
          reason: '_checkUploadSize must exist');
      final body = mainSource.substring(
        idx,
        (idx + 1500).clamp(0, mainSource.length),
      );
      expect(body, contains('app.isBillingLoaded'),
          reason: '_checkUploadSize must gate on app.isBillingLoaded');
    });

    test('the literal "Free Vault Plan" appears ONLY in places that '
         'are not direct UI render sites', () {
      
      
      expect(
        mainSource,
        isNot(contains("const Text(\n                      'Free Vault Plan'")),
        reason: 'The hardcoded "Free Vault Plan" Text widget that caused '
                'the flash must not return. Use app.planLabel inside the '
                'isBillingLoaded branch.',
      );
    });
  });
}
