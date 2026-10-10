import 'package:flutter/material.dart';

import '../api_client.dart';
import '../services/asset_catalog.dart';
import '../services/crypto_wallet_features.dart';
import 'crypto_wallet_engine_asset_detail_page.dart';
import 'crypto_wallet_engine_design.dart';

const kAssetsCryptocurrencyRouteName = '/assets/cryptocurrency';

/// Category navigation only. The existing Cryptocurrency page is passed in
/// unchanged; unavailable real-world asset categories have no wallet actions.
class AssetsPage extends StatefulWidget {
  const AssetsPage({
    super.key,
    required this.cryptocurrency,
    this.accessChanges,
    this.registeredAssetApiClient,
    this.authToken,
    this.apiClient,
    this.encryptForVault,
    this.isVaultKeyAvailable,
    this.decryptForVault,
    this.verifyPin,
    this.loadFromAddress,
  });

  final Widget cryptocurrency;
  final Listenable? accessChanges;
  final VaultAIClient? registeredAssetApiClient;
  final String? authToken;
  final VaultAIClient? apiClient;
  final Future<String> Function(String plaintext)? encryptForVault;
  final bool Function()? isVaultKeyAvailable;
  final Future<String> Function(String ciphertext)? decryptForVault;
  final Future<bool> Function(String pin)? verifyPin;
  final Future<String?> Function(String network)? loadFromAddress;

  @override
  State<AssetsPage> createState() => _AssetsPageState();
}

class _AssetsPageState extends State<AssetsPage> {
  VaultAssetCatalog _catalog = const VaultAssetCatalog.unavailable();
  CryptoWalletFeatures _features = const CryptoWalletFeatures.unknown();
  bool _loading = true;
  int _loadGeneration = 0;

  @override
  void initState() {
    super.initState();
    _loadCatalog();
  }

  @override
  void didUpdateWidget(covariant AssetsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.authToken != widget.authToken ||
        oldWidget.apiClient != widget.apiClient) {
      _catalog = const VaultAssetCatalog.unavailable();
      _features = const CryptoWalletFeatures.unknown();
      _loadCatalog();
    }
  }

  Future<void> _loadCatalog() async {
    final generation = ++_loadGeneration;
    final api = widget.apiClient;
    final token = widget.authToken;
    if (mounted) setState(() => _loading = true);
    var catalog = const VaultAssetCatalog.unavailable();
    var features = const CryptoWalletFeatures.unknown();
    if (api != null && token != null && token.isNotEmpty) {
      try {
        bool current() =>
            mounted &&
            generation == _loadGeneration &&
            token == widget.authToken &&
            (widget.isVaultKeyAvailable?.call() ?? true);
        final responses = await Future.wait([
          api.getCryptoWalletAssetCatalog(
              authToken: token, responseIsCurrent: current),
          api.getCryptoWalletFeatures(
              authToken: token, responseIsCurrent: current),
        ]).timeout(const Duration(seconds: 12));
        catalog = VaultAssetCatalog.fromJson(responses[0]);
        features = CryptoWalletFeatures.fromBackend(responses[1]);
      } catch (_) {
        // Missing catalog, offline, or unsupported deployment: no invented
        // balances/actions, and the original Cryptocurrency page still opens.
      }
    }
    if (!mounted ||
        generation != _loadGeneration ||
        token != widget.authToken ||
        !(widget.isVaultKeyAvailable?.call() ?? true)) {
      return;
    }
    setState(() {
      _catalog = catalog;
      _features = features;
      _loading = false;
    });
  }

  bool _categoryAvailable(VaultAssetCategory category) =>
      _catalog.available(category) &&
      _features.walletEngineEnabled &&
      _features.effectiveMainnetReceiveEnabled &&
      _features.effectiveMainnetErc20ReceiveEnabled;

  void _openCategory(VaultAssetCategory category) {
    if (category == VaultAssetCategory.cryptocurrency) {
      Navigator.of(context).push(MaterialPageRoute<void>(
        settings: const RouteSettings(name: kAssetsCryptocurrencyRouteName),
        builder: (_) => _CryptocurrencyAssetCategoryPage(
          cryptocurrency: widget.cryptocurrency,
        ),
      ));
      return;
    }
    final asset = _catalog.assetFor(category);
    if (asset != null &&
        _categoryAvailable(category) &&
        (widget.isVaultKeyAvailable?.call() ?? true)) {
      Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => CryptoWalletEngineAssetDetailPage(
          asset: asset.id,
          registeredAsset: asset,
          accessChanges: widget.accessChanges,
          authToken: widget.authToken,
          apiClient: widget.registeredAssetApiClient ?? widget.apiClient,
          encryptForVault: widget.encryptForVault,
          isVaultKeyAvailable: widget.isVaultKeyAvailable,
          decryptForVault: widget.decryptForVault,
          verifyPin: widget.verifyPin,
          loadFromAddress: widget.loadFromAddress,
          network: asset.network,
          features: _features,
        ),
      ));
      return;
    }
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => _UnavailableAssetCategoryPage(category: category),
    ));
  }

  @override
  Widget build(BuildContext context) => Theme(
        data: walletDarkPanelTheme(context),
        child: Scaffold(
          key: const Key('assets_page'),
          backgroundColor: kWalletBgBase,
          appBar: AppBar(
            title: const Text('Assets'),
            backgroundColor: kWalletBgBase,
            foregroundColor: kWalletTextPrimary,
          ),
          body: DecoratedBox(
            decoration: walletPageBackground(),
            child: RefreshIndicator(
              onRefresh: _loadCatalog,
              child: ListView(
                padding: const EdgeInsets.all(18),
                children: [
                  const Text('Your digital vault for supported assets',
                      style: kWalletHeadingStyle),
                  const SizedBox(height: 8),
                  const Text(
                    'Hold, receive and send supported tokens with your own wallet. '
                    'A category is available only when a verified token and its '
                    'network are connected. No buying, selling or trading.',
                    style: kWalletBodyStyle,
                  ),
                  const SizedBox(height: 18),
                  for (final category in VaultAssetCategory.values)
                    _categoryCard(category),
                ],
              ),
            ),
          ),
        ),
      );

  Widget _categoryCard(VaultAssetCategory category) {
    final crypto = category == VaultAssetCategory.cryptocurrency;
    final supported = category == VaultAssetCategory.digitalGold ||
        category == VaultAssetCategory.digitalSilver;
    final asset = _catalog.assetFor(category);
    final available = crypto || _categoryAvailable(category);
    final status = supported && _loading
        ? 'Checking availability…'
        : available
            ? (asset != null
                ? '${asset.name} · ${asset.symbol} · Ethereum Mainnet'
                    '${asset.id == kKagAssetId && !asset.receiveEnabled ? ' · Transfers unavailable' : ''}'
                : 'Your existing cryptocurrency wallets')
            : 'Coming soon';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Container(
        decoration: walletAssetCard(asset?.id ?? 'ETH'),
        child: ListTile(
          key: Key('assets_category_${category.id}'),
          contentPadding: const EdgeInsets.all(16),
          leading: Icon(_categoryIcon(category), color: kWalletAccentPrimary),
          title: Text(category.label,
              style: const TextStyle(
                  color: kWalletTextPrimary, fontWeight: FontWeight.w700)),
          subtitle: Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(status, style: kWalletMutedStyle),
          ),
          trailing: const Icon(Icons.chevron_right, color: kWalletTextMuted),
          onTap: supported && _loading ? null : () => _openCategory(category),
        ),
      ),
    );
  }
}

IconData _categoryIcon(VaultAssetCategory category) => switch (category) {
      VaultAssetCategory.cryptocurrency => Icons.currency_bitcoin,
      VaultAssetCategory.digitalGold => Icons.savings_outlined,
      VaultAssetCategory.digitalSilver => Icons.layers_outlined,
      VaultAssetCategory.realEstate => Icons.home_work_outlined,
      VaultAssetCategory.gemstones => Icons.diamond_outlined,
      VaultAssetCategory.artwork => Icons.palette_outlined,
      VaultAssetCategory.collectibles => Icons.watch_outlined,
      VaultAssetCategory.equipment => Icons.directions_car_outlined,
      VaultAssetCategory.inventory => Icons.inventory_2_outlined,
      VaultAssetCategory.securities => Icons.account_balance_outlined,
    };

/// The original cryptocurrency dashboard is embedded content, so only this
/// Assets route supplies its navigation chrome. Wallet behavior stays unchanged.
class _CryptocurrencyAssetCategoryPage extends StatelessWidget {
  const _CryptocurrencyAssetCategoryPage({required this.cryptocurrency});

  final Widget cryptocurrency;

  @override
  Widget build(BuildContext context) => Theme(
        data: walletDarkPanelTheme(context),
        child: Scaffold(
          key: const Key('assets_cryptocurrency_route'),
          backgroundColor: kWalletBgBase,
          appBar: AppBar(
            leading: const BackButton(
              key: Key('assets_cryptocurrency_back'),
            ),
            title: Text(VaultAssetCategory.cryptocurrency.label),
            backgroundColor: kWalletBgBase,
            foregroundColor: kWalletTextPrimary,
          ),
          body: SafeArea(top: false, child: cryptocurrency),
        ),
      );
}

class _UnavailableAssetCategoryPage extends StatelessWidget {
  const _UnavailableAssetCategoryPage({required this.category});
  final VaultAssetCategory category;
  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: kWalletBgBase,
        appBar: AppBar(
          title: Text(category.label),
          backgroundColor: kWalletBgBase,
          foregroundColor: kWalletTextPrimary,
        ),
        body: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(_categoryIcon(category), size: 48, color: kWalletTextMuted),
              const SizedBox(height: 16),
              const Text('Coming soon', style: kWalletHeadingStyle),
              const SizedBox(height: 12),
              Text(
                  '${category.label} is not connected to a supported token '
                  'network in SVaultAI. No balance, receive address, send action '
                  'or transaction history is available for this category.',
                  style: kWalletBodyStyle),
              const SizedBox(height: 12),
              const Text(
                  'A token represents an issuer-defined asset. It does '
                  'not place a physical item in your vault or guarantee ownership '
                  'or redemption of that item.',
                  style: kWalletMutedStyle),
            ],
          ),
        ),
      );
}
