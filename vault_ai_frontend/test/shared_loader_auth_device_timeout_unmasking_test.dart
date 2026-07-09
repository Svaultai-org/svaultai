


import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:vault_ai_frontend/api_client.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_balance_reason.dart';
import 'package:vault_ai_frontend/services/crypto_wallet_dashboard_reason.dart';


String _readLib(String rel) {
  return File('${Directory.current.path}/lib/$rel').readAsStringSync()
      .replaceAll('\r\n', '\n');
}




class _FakeClient extends VaultAIClient {
  final Future<Map<String, dynamic>> Function() onReceive;
  final Future<Map<String, dynamic>> Function()? onBalance;
  _FakeClient({required this.onReceive, this.onBalance})
      : super(baseUrl: 'http://mock');

  @override
  Future<Map<String, dynamic>> getCryptoWalletReceiveNetwork({
    required String network,
    required String asset,
    required String authToken,
  }) => onReceive();

  @override
  Future<Map<String, dynamic>> getCryptoWalletBalanceNetwork({
    required String network,
    required String asset,
    required String authToken,
    required String address,
  }) {
    if (onBalance == null) {
      throw StateError('balance not expected');
    }
    return onBalance!();
  }
}


void main() {


  group('Part 1 — Shared loader UNMASKS auth/device/timeout '
      '(user Rule 4: no more auth failure surfaced as rpc_error)', () {

    test('AuthExpiredException on receive → reason("auth_expired") — '
        'NOT rpc_error', () async {
      final s = await loadAssetWalletState(
        apiClient: _FakeClient(
          onReceive: () => Future.error(const AuthExpiredException()),
        ),
        authToken: 't', network: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(s.kind, DashboardAssetLiveStateKind.reason);
      expect(s.backendReason, kDashboardReasonAuthExpired);
      expect(s.backendReason, isNot('rpc_error'),
          reason: 'auth failure must NOT be masked as rpc_error.');
    });

    test('DeviceNotTrustedException on receive → '
        'reason("device_not_trusted") — NOT rpc_error', () async {
      final s = await loadAssetWalletState(
        apiClient: _FakeClient(
          onReceive: () => Future.error(const DeviceNotTrustedException(
            message: 'pending approval',
          )),
        ),
        authToken: 't', network: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(s.kind, DashboardAssetLiveStateKind.reason);
      expect(s.backendReason, kDashboardReasonDeviceNotTrusted);
    });

    test('TimeoutException on receive → reason("receive_timeout")',
        () async {
      final s = await loadAssetWalletState(
        apiClient: _FakeClient(
          onReceive: () => Future.delayed(
            const Duration(seconds: 30), () => <String, dynamic>{},
          ),
        ),
        authToken: 't', network: 'ethereum_mainnet', asset: 'ETH',
        receiveTimeout: const Duration(milliseconds: 30),
      );
      expect(s.kind, DashboardAssetLiveStateKind.reason);
      expect(s.backendReason, kDashboardReasonReceiveTimeout,
          reason: 'a slow receive must map to receive_timeout — not '
              'a generic rpc_error — so the user knows to retry.');
    });

    test('Generic HTTP error on receive → reason("rpc_error") still '
        '(backwards compat for the truly-unknown class)',
        () async {
      final s = await loadAssetWalletState(
        apiClient: _FakeClient(
          onReceive: () => Future.error(Exception('500 upstream failure')),
        ),
        authToken: 't', network: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(s.kind, DashboardAssetLiveStateKind.reason);
      expect(s.backendReason, 'rpc_error');
    });
  });



  group('Part 2 — Balance side unmasks the same way — receive succeeded, '
      'balance timed out', () {

    Map<String, dynamic> _ready() => {
      'wallet_engine': 'receive_ready',
      'publicAddress': 'ADDR_MOCK',
    };

    test('AuthExpiredException on balance → reason("auth_expired")',
        () async {
      final s = await loadAssetWalletState(
        apiClient: _FakeClient(
          onReceive: () => Future.value(_ready()),
          onBalance: () => Future.error(const AuthExpiredException()),
        ),
        authToken: 't', network: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(s.kind, DashboardAssetLiveStateKind.reason);
      expect(s.backendReason, kDashboardReasonAuthExpired);
    });

    test('DeviceNotTrustedException on balance → '
        'reason("device_not_trusted")', () async {
      final s = await loadAssetWalletState(
        apiClient: _FakeClient(
          onReceive: () => Future.value(_ready()),
          onBalance: () => Future.error(
            const DeviceNotTrustedException(message: 'x'),
          ),
        ),
        authToken: 't', network: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(s.backendReason, kDashboardReasonDeviceNotTrusted);
    });

    test('TimeoutException on balance → reason("balance_timeout") '
        '(distinct from receive_timeout so we can tell them apart in logs)',
        () async {
      final s = await loadAssetWalletState(
        apiClient: _FakeClient(
          onReceive: () => Future.value(_ready()),
          onBalance: () => Future.delayed(
            const Duration(seconds: 30), () => <String, dynamic>{},
          ),
        ),
        authToken: 't', network: 'ethereum_mainnet', asset: 'ETH',
        receiveTimeout: const Duration(seconds: 5),
        balanceTimeout: const Duration(milliseconds: 30),
      );
      expect(s.backendReason, kDashboardReasonBalanceTimeout,
          reason: 'balance-side timeouts must be distinguishable from '
              'receive-side timeouts in logs and UI.');
    });

    test('preserves publicAddress on classified balance failure — '
        'the wallet DOES exist, we just could not check its balance',
        () async {
      final s = await loadAssetWalletState(
        apiClient: _FakeClient(
          onReceive: () => Future.value(_ready()),
          onBalance: () => Future.error(const AuthExpiredException()),
        ),
        authToken: 't', network: 'ethereum_mainnet', asset: 'ETH',
      );
      expect(s.publicAddressPresent, isTrue,
          reason: 'even on classified balance failure, we must remember '
              'that the wallet exists.');
    });
  });



  group('Part 3 — Card render maps each closed-set reason to honest, '
      'compact copy — no more "Balance temporarily unavailable" for '
      'auth/device', () {

    test('auth_expired → "Session expired. Sign in again to see balance."',
        () {
      final r = walletBalanceReasonRender(
        reason: 'auth_expired', asset: 'ETH',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.bodyKey, kWalletBalanceReasonKeyAuthExpired);
      expect(r.message, kWalletBalanceCopyAuthExpired);
      expect(r.message.toLowerCase().contains('sign in'), isTrue);



      expect(r.message, isNot(kWalletBalanceCopyRpcError));
    });

    test('device_not_trusted → device-specific copy', () {
      final r = walletBalanceReasonRender(
        reason: 'device_not_trusted', asset: 'ETH',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.bodyKey, kWalletBalanceReasonKeyDeviceNotTrusted);
      expect(r.message.toLowerCase().contains('device'), isTrue);
      expect(r.message, isNot(kWalletBalanceCopyRpcError));
    });

    test('receive_timeout / balance_timeout → "taking longer than '
        'expected" — distinct from generic rpc_error', () {
      for (final reason in ['receive_timeout', 'balance_timeout']) {
        final r = walletBalanceReasonRender(
          reason: reason, asset: 'ETH',
          networkKind: WalletNetworkKind.ethereum,
        );
        expect(r.message.toLowerCase().contains('taking longer'), isTrue,
            reason: '$reason should surface timeout copy, not rpc_error');
      }
    });

    test('generic rpc_error / unknown still hit the calm '
        '"Balance temporarily unavailable" copy', () {
      final r = walletBalanceReasonRender(
        reason: 'rpc_error', asset: 'ETH',
        networkKind: WalletNetworkKind.ethereum,
      );
      expect(r.message, kWalletBalanceCopyRpcError);
    });
  });



  group('Part 4 — closed-set reason surface + secret-safety in loader '
      'classified logs', () {

    test('classified log labels never contain address/token/'
        'RPC/API key/private secret', () {
      final src = _readLib('services/crypto_wallet_dashboard_reason.dart');




      final logLineRegex = RegExp(
        r"'((?:receive_call_failed|balance_call_failed) asset="
        r"[^']*)'",
        multiLine: true,
      );
      final matches = logLineRegex.allMatches(src).toList();
      expect(matches.length, greaterThanOrEqualTo(2),
          reason: 'both receive_call_failed and balance_call_failed '
              'log lines must be present');

      const banned = [
        'publicaddress', 'public_address',
        'wallet_address', 'wallet_addr',
        'rpc_url', 'api_key', 'apikey',
        'authorization: bearer', 'bearer eyj',
        'private_key', 'privatekey',
        'seed_phrase', 'seedphrase', 'mnemonic',
        'tx_hash', 'txhash', 'encrypted_secret',
      ];
      for (final m in matches) {
        final line = (m.group(1) ?? '').toLowerCase();
        for (final b in banned) {
          expect(line.contains(b), isFalse,
              reason: 'log line "$line" must not literal-mention "$b"');
        }
      }
    });

    test('receive_call_failed log includes both error runtime type AND '
        'the classified closed-set label (so devs see both raw type '
        'and mapped reason)', () {
      final src = _readLib('services/crypto_wallet_dashboard_reason.dart');
      expect(
        src.contains('error=\${e.runtimeType} classified=\$classified'),
        isTrue,
        reason: 'the closed-set classifier must be threaded into the '
            'error log so DevTools shows exactly what mapped to what.',
      );
    });

    test('closed-set reason string constants are exported and stable', () {
      expect(kDashboardReasonAuthExpired, 'auth_expired');
      expect(kDashboardReasonDeviceNotTrusted, 'device_not_trusted');
      expect(kDashboardReasonReceiveTimeout, 'receive_timeout');
      expect(kDashboardReasonBalanceTimeout, 'balance_timeout');
    });
  });
}
