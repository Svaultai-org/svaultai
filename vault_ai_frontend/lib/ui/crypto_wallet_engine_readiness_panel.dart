
import 'package:flutter/material.dart';

import '../api_client.dart';
import 'crypto_wallet_engine_design.dart';


const String kReadinessPanelKey = 'crypto_wallet_readiness_panel';
const String kReadinessPanelTitleKey = 'crypto_wallet_readiness_panel_title';
const String kReadinessPanelRefreshBtnKey =
    'crypto_wallet_readiness_panel_refresh';
const String kReadinessPanelLoadingKey =
    'crypto_wallet_readiness_panel_loading';
const String kReadinessPanelErrorKey =
    'crypto_wallet_readiness_panel_error';
const String kReadinessPanelRowKeyPrefix =
    'crypto_wallet_readiness_panel_row_';
const String kReadinessPanelSummaryChipKey =
    'crypto_wallet_readiness_panel_summary_chip';


const String kReadinessPanelTitle = 'Crypto Vault — provider readiness';
const String kReadinessPanelSubtitle =
    'Per-asset operator readiness. Booleans and env-var names only — '
    'never raw RPC URLs, API keys, contract values, wallet addresses, '
    'tx hashes, or user PII.';
const String kReadinessPanelLoadingLabel =
    'Loading readiness…';
const String kReadinessPanelForbiddenLabel =
    'Readiness endpoint requires an admin token.';
const String kReadinessPanelUnknownErrorLabel =
    'Could not load readiness.';
const String kReadinessPanelSecretSafeAttestation =
    'Values shown are booleans and enum strings only. No RPC URL, '
    'no API key, no token contract value, no wallet address, no tx '
    'hash, no private key or seed.';


const String kReadinessLabelFeatureEnabled = 'Feature enabled';
const String kReadinessLabelRpcConfigured = 'RPC/API configured';
const String kReadinessLabelTokenContract = 'Token contract configured';
const String kReadinessLabelBalanceRouteReady = 'Balance route ready';
const String kReadinessLabelLastBalanceReason = 'Last balance reason';
const String kReadinessLabelReceiveEnabled = 'Receive enabled';
const String kReadinessLabelSendEnabled = 'Send enabled';
const String kReadinessLabelSendPaused = 'Send paused';
const String kReadinessLabelActivityConnected = 'Activity connected';
const String kReadinessLabelStatusReady = 'Status route ready';
const String kReadinessLabelFeeReady = 'Fee route ready';
const String kReadinessLabelUsdtContractConfigured =
    'USDT contract configured';
const String kReadinessLabelXmrScannerMode = 'XMR scanner mode';
const String kReadinessLabelXmrClientScannerSupported =
    'Client scanner supported';
const String kReadinessLabelXmrBackendScannerEnabled =
    'Backend scanner enabled';
const String kReadinessLabelWalletGeneration = 'Wallet generation';


class ReadinessRowConfig {
  final String rowId;
  final String assetKey;
  final String displayName;
  final String? networkLabel;

  const ReadinessRowConfig({
    required this.rowId,
    required this.assetKey,
    required this.displayName,
    this.networkLabel,
  });
}


const List<ReadinessRowConfig> kReadinessDisplayOrder = [
  ReadinessRowConfig(
    rowId: 'ethereum_mainnet_eth',
    assetKey: 'ETH',
    displayName: 'ETH',
    networkLabel: 'Ethereum Mainnet',
  ),
  ReadinessRowConfig(
    rowId: 'ethereum_mainnet_usdt_erc20',
    assetKey: 'USDT_ERC20',
    displayName: 'USDT (ERC20)',
    networkLabel: 'Ethereum Mainnet',
  ),
  ReadinessRowConfig(
    rowId: 'ethereum_mainnet_usdc_erc20',
    assetKey: 'USDC_ERC20',
    displayName: 'USDC (ERC20)',
    networkLabel: 'Ethereum Mainnet',
  ),
  ReadinessRowConfig(
    rowId: 'solana_mainnet_sol',
    assetKey: 'SOL',
    displayName: 'SOL',
    networkLabel: 'Solana Mainnet',
  ),
  ReadinessRowConfig(
    rowId: 'tron_mainnet_usdt_trc20',
    assetKey: 'USDT_TRC20',
    displayName: 'USDT (TRC20)',
    networkLabel: 'TRON Mainnet',
  ),
  ReadinessRowConfig(
    rowId: 'monero_mainnet_xmr',
    assetKey: 'XMR',
    displayName: 'XMR',
    networkLabel: 'Monero Mainnet',
  ),
];


class CryptoWalletEngineReadinessPanel extends StatefulWidget {
  final VaultAIClient client;
  final String authToken;
  final String? adminToken;

  const CryptoWalletEngineReadinessPanel({
    super.key,
    required this.client,
    required this.authToken,
    this.adminToken,
  });

  @override
  State<CryptoWalletEngineReadinessPanel> createState() =>
      _CryptoWalletEngineReadinessPanelState();
}

class _CryptoWalletEngineReadinessPanelState
    extends State<CryptoWalletEngineReadinessPanel> {
  bool _loading = false;
  Map<String, dynamic>? _features;
  Map<String, dynamic>? _diagnosis;
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
      final features = await widget.client.getCryptoWalletFeatures(
        authToken: widget.authToken,
      );
      Map<String, dynamic>? diag;
      try {
        diag = await widget.client.getCryptoWalletDiagnosis(
          authToken: widget.authToken,
          adminToken: widget.adminToken,
        );
      } catch (e) {
        final msg = e.toString().toLowerCase();
        if (msg.contains('403') || msg.contains('forbidden')) {
          if (!mounted) return;
          setState(() {
            _features = features;
            _diagnosis = null;
            _loading = false;
            _error = kReadinessPanelForbiddenLabel;
          });
          return;
        }
        rethrow;
      }
      if (!mounted) return;
      setState(() {
        _features = features;
        _diagnosis = diag;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = kReadinessPanelUnknownErrorLabel;
      });
    }
  }

  Map<String, Map<String, dynamic>> get _rowsByRowId {
    final assets = (_diagnosis?['assets'] as List?) ?? const [];
    final out = <String, Map<String, dynamic>>{};
    for (final a in assets) {
      if (a is Map) {
        final row = a.cast<String, dynamic>();
        final id = row['rowId']?.toString();
        if (id != null && id.isNotEmpty) out[id] = row;
      }
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key(kReadinessPanelKey),
      decoration: walletPageBackground(),
      padding: const EdgeInsets.all(16),
      child: SingleChildScrollView(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 900),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _buildHeader(),
                const SizedBox(height: 10),
                if (_loading) _buildLoading()
                else if (_error != null) _buildError(_error!)
                else _buildBody(),
                const SizedBox(height: 14),
                _buildSecretSafeAttestation(),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: const [
              Text(
                kReadinessPanelTitle,
                key: Key(kReadinessPanelTitleKey),
                style: kWalletHeadingStyle,
              ),
              SizedBox(height: 4),
              Text(
                kReadinessPanelSubtitle,
                style: kWalletBodyStyle,
              ),
            ],
          ),
        ),
        IconButton(
          key: const Key(kReadinessPanelRefreshBtnKey),
          icon: const Icon(
            Icons.refresh_rounded,
            color: kWalletTextSecondary,
          ),
          onPressed: _loading ? null : _refresh,
        ),
      ],
    );
  }

  Widget _buildLoading() {
    return Padding(
      key: const Key(kReadinessPanelLoadingKey),
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: const [
          SizedBox(
            width: 16, height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 10),
          Text(kReadinessPanelLoadingLabel, style: kWalletBodyStyle),
        ],
      ),
    );
  }

  Widget _buildError(String message) {
    return Container(
      key: const Key(kReadinessPanelErrorKey),
      padding: const EdgeInsets.all(12),
      decoration: walletWarningPanel(),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded,
              size: 18, color: kWalletAccentWarning),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(
                color: kWalletAccentWarning,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBody() {
    final rows = _rowsByRowId;
    final features = _features ?? const <String, dynamic>{};
    final ready = _diagnosis?['assetsReady'];
    final total = _diagnosis?['assetsTotal'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (ready is int && total is int)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Container(
              key: const Key(kReadinessPanelSummaryChipKey),
              padding: const EdgeInsets.symmetric(
                horizontal: 10, vertical: 6,
              ),
              decoration: BoxDecoration(
                color: kWalletSurfaceElevated,
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: kWalletBorder),
              ),
              child: Text(
                '$ready of $total assets ready',
                style: kWalletBodyStyle,
              ),
            ),
          ),
        for (final cfg in kReadinessDisplayOrder)
          _buildAssetCard(cfg, rows[cfg.rowId], features),
      ],
    );
  }

  Widget _buildAssetCard(
    ReadinessRowConfig cfg,
    Map<String, dynamic>? row,
    Map<String, dynamic> features,
  ) {
    final ready = row?['balanceRouteReady'] == true;
    final reason = row?['lastBalanceReason']?.toString() ?? '—';
    return Container(
      key: Key('$kReadinessPanelRowKeyPrefix${cfg.rowId}'),
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.all(12),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      cfg.displayName,
                      style: const TextStyle(
                        color: kWalletTextPrimary,
                        fontWeight: FontWeight.w800,
                        fontSize: 15,
                      ),
                    ),
                    if (cfg.networkLabel != null)
                      Text(
                        cfg.networkLabel!,
                        style: kWalletMutedStyle,
                      ),
                  ],
                ),
              ),
              _readyBadge(ready),
            ],
          ),
          const SizedBox(height: 8),
          ..._buildRowFields(cfg, row, features),
          if (reason != '—') ...[
            const SizedBox(height: 4),
            _kv(
              kReadinessLabelLastBalanceReason,
              reason,
              valueKey: Key(
                'crypto_wallet_readiness_reason_${cfg.rowId}',
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _readyBadge(bool ready) {
    final label = ready ? 'READY' : 'NOT READY';
    final color = ready ? kWalletAccentSuccess : kWalletAccentWarning;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontWeight: FontWeight.w800,
          fontSize: 11,
        ),
      ),
    );
  }

  List<Widget> _buildRowFields(
    ReadinessRowConfig cfg,
    Map<String, dynamic>? row,
    Map<String, dynamic> features,
  ) {
    if (row == null) {
      return [
        _kv(
          kReadinessLabelFeatureEnabled,
          _diagnosis == null
              ? 'diagnosis not available'
              : 'unknown',
        ),
      ];
    }
    final r = row;
    final children = <Widget>[
      _kv(
        kReadinessLabelFeatureEnabled,
        _bool(r['featureEnabled']),
      ),
      _kv(
        kReadinessLabelRpcConfigured,
        _bool(r['rpcConfigured']),
      ),
    ];
    if (r['tokenContractRequired'] == true) {
      children.add(_kv(
        kReadinessLabelTokenContract,
        _bool(r['tokenContractConfigured']),
      ));
    }
    children.add(_kv(
      kReadinessLabelBalanceRouteReady,
      _bool(r['balanceRouteReady']),
    ));
    switch (cfg.rowId) {
      case 'solana_mainnet_sol':
        children.add(_kv(
          kReadinessLabelReceiveEnabled,
          _bool(features['solanaReceiveEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelSendEnabled,
          _bool(features['solanaSendEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelStatusReady,
          _bool(features['solanaStatusReady']),
        ));
        children.add(_kv(
          kReadinessLabelFeeReady,
          _bool(features['solanaFeeReady']),
        ));
        children.add(_kv(
          kReadinessLabelActivityConnected,
          _bool(features['solanaActivityConnected']),
        ));
        break;
      case 'tron_mainnet_usdt_trc20':
        children.add(_kv(
          kReadinessLabelReceiveEnabled,
          _bool(features['tronReceiveEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelSendEnabled,
          _bool(features['tronSendEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelSendPaused,
          _bool(features['tronSendPaused']),
        ));
        children.add(_kv(
          kReadinessLabelUsdtContractConfigured,
          _bool(features['tronUsdtContractConfigured']),
        ));
        children.add(_kv(
          kReadinessLabelActivityConnected,
          _bool(features['tronActivityConnected']),
        ));
        break;
      case 'monero_mainnet_xmr':
        children.add(_kv(
          kReadinessLabelReceiveEnabled,
          _bool(features['xmrReceiveEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelSendEnabled,
          _bool(features['xmrSendEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelXmrScannerMode,
          '${features['xmrScannerMode'] ?? r['scannerMode'] ?? '—'}',
        ));
        children.add(_kv(
          kReadinessLabelXmrClientScannerSupported,
          _bool(features['xmrClientScannerSupported']),
        ));
        children.add(_kv(
          kReadinessLabelXmrBackendScannerEnabled,
          _bool(features['xmrBackendScannerEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelWalletGeneration,
          '${r['walletGenerationStatus'] ?? '—'}',
        ));
        break;
      case 'ethereum_mainnet_eth':
        children.add(_kv(
          kReadinessLabelReceiveEnabled,
          _bool(features['mainnetReceiveEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelSendEnabled,
          _bool(features['mainnetSendEnabled']),
        ));
        children.add(_kv(
          kReadinessLabelSendPaused,
          _bool(features['mainnetSendPaused']),
        ));
        break;
      case 'ethereum_mainnet_usdt_erc20':
      case 'ethereum_mainnet_usdc_erc20':
        children.add(_kv(
          kReadinessLabelReceiveEnabled,
          _bool(features['mainnetErc20ReceiveEnabled']),
        ));
        break;
    }
    return children;
  }

  Widget _buildSecretSafeAttestation() {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: walletSuccessPanel(),
      child: Row(
        children: const [
          Icon(Icons.shield_outlined,
              size: 16, color: kWalletAccentSuccess),
          SizedBox(width: 8),
          Expanded(
            child: Text(
              kReadinessPanelSecretSafeAttestation,
              style: TextStyle(
                color: kWalletAccentSuccess,
                fontSize: 12,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _bool(dynamic v) {
    if (v == true) return 'yes';
    if (v == false) return 'no';
    return '—';
  }

  Widget _kv(String label, String value, {Key? valueKey}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 180,
            child: Text(
              label,
              style: kWalletMutedStyle,
            ),
          ),
          Expanded(
            child: Text(
              value,
              key: valueKey,
              style: const TextStyle(
                color: kWalletTextPrimary,
                fontSize: 12,
                fontFamily: 'monospace',
              ),
            ),
          ),
        ],
      ),
    );
  }
}
