

import 'package:flutter/material.dart';

import '../api_client.dart';

const String kAdminHealthPanelKey =
    'crypto_wallet_engine_admin_health_panel';
const String kAdminHealthPanelNetworkCardKey =
    'crypto_wallet_engine_admin_health_network_card';
const String kAdminHealthPanelOverallChipKey =
    'crypto_wallet_engine_admin_health_overall_chip';
const String kAdminHealthPanelRefreshBtnKey =
    'crypto_wallet_engine_admin_health_refresh_btn';
const String kAdminHealthPanelErrorBannerKey =
    'crypto_wallet_engine_admin_health_error_banner';


const String kAdminHealthPanelTitle = 'Crypto Wallet — production health';
const String kAdminHealthPanelOverallReady = 'READY';
const String kAdminHealthPanelOverallDegraded = 'DEGRADED';
const String kAdminHealthPanelOverallNotReady = 'NOT READY';
const String kAdminHealthPanelUnauthorizedBanner =
    'Health endpoint requires an admin token.';
const String kAdminHealthPanelLoadingLabel = 'Loading health…';

class CryptoWalletEngineAdminHealthPanel extends StatefulWidget {
  final VaultAIClient client;
  final String authToken;
  final String? adminToken;

  const CryptoWalletEngineAdminHealthPanel({
    super.key,
    required this.client,
    required this.authToken,
    this.adminToken,
  });

  @override
  State<CryptoWalletEngineAdminHealthPanel> createState() =>
      _CryptoWalletEngineAdminHealthPanelState();
}

class _CryptoWalletEngineAdminHealthPanelState
    extends State<CryptoWalletEngineAdminHealthPanel> {
  bool _loading = false;
  Map<String, dynamic>? _envelope;
  String? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final body = await widget.client.getCryptoWalletHealth(
        authToken: widget.authToken,
        adminToken: widget.adminToken,
      );
      if (!mounted) return;
      setState(() {
        _envelope = body;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      
      
      final msg = e.toString().toLowerCase();
      String safe;
      if (msg.contains('403') || msg.contains('forbidden')) {
        safe = kAdminHealthPanelUnauthorizedBanner;
      } else {
        safe = 'Could not load health.';
      }
      setState(() {
        _envelope = null;
        _loading = false;
        _error = safe;
      });
    }
  }

  String _overallLabel(String? raw) {
    switch (raw) {
      case 'ready':
        return kAdminHealthPanelOverallReady;
      case 'degraded':
        return kAdminHealthPanelOverallDegraded;
      case 'not_ready':
        return kAdminHealthPanelOverallNotReady;
    }
    return raw?.toUpperCase() ?? '—';
  }

  Color _overallColor(String? raw) {
    switch (raw) {
      case 'ready':
        return const Color(0xFF2E6B2E);
      case 'degraded':
        return const Color(0xFF995500);
      case 'not_ready':
        return const Color(0xFF8B1A1A);
    }
    return Colors.black54;
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key(kAdminHealthPanelKey),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  kAdminHealthPanelTitle,
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              IconButton(
                key: const Key(kAdminHealthPanelRefreshBtnKey),
                icon: const Icon(Icons.refresh),
                onPressed: _loading ? null : _refresh,
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (_loading)
            Row(
              mainAxisSize: MainAxisSize.min,
              children: const [
                SizedBox(
                  width: 14, height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                SizedBox(width: 8),
                Text(kAdminHealthPanelLoadingLabel),
              ],
            )
          else if (_error != null)
            Container(
              key: const Key(kAdminHealthPanelErrorBannerKey),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFFFDECEC),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: const Color(0xFFE5A0A0)),
              ),
              child: Text(
                _error!,
                style: const TextStyle(
                  color: Color(0xFF8B1A1A),
                ),
              ),
            )
          else if (_envelope != null)
            ..._buildEnvelopeBody(_envelope!),
        ],
      ),
    );
  }

  List<Widget> _buildEnvelopeBody(Map<String, dynamic> env) {
    final overall = env['overallStatus']?.toString();
    final networks = (env['networks'] as List?) ?? const [];
    final features = (env['features'] as Map?)?.cast<String, dynamic>()
        ?? const <String, dynamic>{};
    return [
      Row(
        children: [
          const Text(
            'Overall: ',
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
          Container(
            key: const Key(kAdminHealthPanelOverallChipKey),
            padding: const EdgeInsets.symmetric(
              horizontal: 8, vertical: 3,
            ),
            decoration: BoxDecoration(
              color: _overallColor(overall).withOpacity(0.12),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: _overallColor(overall)),
            ),
            child: Text(
              _overallLabel(overall),
              style: TextStyle(
                color: _overallColor(overall),
                fontWeight: FontWeight.w800,
                fontSize: 12,
              ),
            ),
          ),
        ],
      ),
      const SizedBox(height: 10),
      for (final net in networks)
        if (net is Map)
          _buildNetworkCard(net.cast<String, dynamic>()),
      const SizedBox(height: 8),
      _buildFeatureCard(features),
    ];
  }

  Widget _buildNetworkCard(Map<String, dynamic> net) {
    final status = net['status']?.toString();
    final tokens = (net['tokens'] as List?) ?? const [];
    final send = (net['send'] as Map?)?.cast<String, dynamic>()
        ?? const <String, dynamic>{};
    final networkId = (net['id'] ?? '').toString();
    return Container(
      key: Key(
        '$kAdminHealthPanelNetworkCardKey'
        '_$networkId',
      ),
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F7F7),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFE0E0E0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  net['displayName']?.toString() ?? '—',
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 14,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 6, vertical: 2,
                ),
                decoration: BoxDecoration(
                  color: _overallColor(status).withOpacity(0.12),
                  borderRadius: BorderRadius.circular(4),
                  border: Border.all(color: _overallColor(status)),
                ),
                child: Text(
                  _overallLabel(status),
                  style: TextStyle(
                    color: _overallColor(status),
                    fontWeight: FontWeight.w700,
                    fontSize: 11,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          _kv('RPC configured', '${net['rpcConfigured']}'),
          _kv('RPC reachable', '${net['rpcReachable']}'),
          _kv('Chain ID expected', '${net['chainIdExpected'] ?? '—'}'),
          _kv('Chain ID observed', '${net['chainIdObserved'] ?? '—'}'),
          _kv('Indexer configured', '${net['txIndexerConfigured']}'),
          _kv('Indexer reachable', '${net['txIndexerReachable']}'),
          for (final t in tokens)
            if (t is Map)
              _kv(
                '${t['asset']}',
                t['configured'] == true
                    ? (t['readable'] == true
                        ? 'configured + readable'
                        : 'configured · ${t['reason'] ?? 'unverified'}')
                    : (t['reason']?.toString() ?? 'missing'),
              ),
          if (send.isNotEmpty) const SizedBox(height: 4),
          for (final entry in send.entries)
            _kv(entry.key, '${entry.value}'),
        ],
      ),
    );
  }

  Widget _buildFeatureCard(Map<String, dynamic> features) {
    if (features.isEmpty) return const SizedBox.shrink();
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F7F7),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFE0E0E0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Feature flags',
            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
          ),
          const SizedBox(height: 6),
          for (final entry in features.entries)
            _kv(entry.key, '${entry.value}'),
        ],
      ),
    );
  }

  Widget _kv(String k, String v) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 170,
            child: Text(
              k,
              style: const TextStyle(
                fontSize: 12,
                color: Colors.black54,
              ),
            ),
          ),
          Expanded(
            child: Text(
              v,
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
