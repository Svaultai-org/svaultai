
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/crypto_wallet_features.dart';
import '../services/monero_scanner.dart';
import '../services/monero_scanner_status.dart';
import 'crypto_wallet_engine_design.dart';


const String kMoneroScannerCardKey = 'monero_scanner_card';
const String kMoneroScannerHeadingKey =
    'monero_scanner_card_heading';
const String kMoneroScannerStateKey =
    'monero_scanner_card_state';
const String kMoneroScannerStartBtnKey =
    'monero_scanner_card_start_btn';
const String kMoneroScannerStopBtnKey =
    'monero_scanner_card_stop_btn';
const String kMoneroScannerCurrentHeightKey =
    'monero_scanner_card_current_height';
const String kMoneroScannerTargetHeightKey =
    'monero_scanner_card_target_height';
const String kMoneroScannerRestoreHeightKey =
    'monero_scanner_card_restore_height';
const String kMoneroScannerPercentKey =
    'monero_scanner_card_percent';
const String kMoneroScannerLastUpdatedKey =
    'monero_scanner_card_last_updated';
const String kMoneroScannerErrorReasonKey =
    'monero_scanner_card_error_reason';
const String kMoneroScannerUnavailableCopyKey =
    'monero_scanner_card_unavailable_copy';
const String kMoneroScannerPrivacyNoteKey =
    'monero_scanner_card_privacy_note';
const String kMoneroScannerRestoreHeightSectionKey =
    'monero_scanner_card_restore_height_section';
const String kMoneroScannerRestoreHeightFieldKey =
    'monero_scanner_card_restore_height_field';


const String kMoneroScannerRestoreHeightLabel =
    'Restore height';
const String kMoneroScannerRestoreHeightExplainer =
    'For older wallets set a restore height for faster scanning.';


const String kMoneroScannerHeading = 'Monero scanner';
const String kMoneroScannerStartLabel = 'Start scan';
const String kMoneroScannerStopLabel = 'Stop scan';
const String kMoneroScannerRequiresWalletCopy =
    'Monero balance and activity require wallet scanning.';
const String kMoneroScannerRunsOnDeviceCopy =
    'Scanning happens on this device.';
const String kMoneroScannerDoNotCloseAppCopy =
    'Do not close the app while scanning.';
const String kMoneroScannerSyncTimeCopy =
    'Sync can take time depending on restore height.';
const String kMoneroScannerUnavailableCopy =
    'Scanner not enabled';
const String kMoneroScannerNotStartedCopy =
    'Scanner not enabled';
const String kMoneroScannerSyncingCopy =
    'Scanner syncing';
const String kMoneroScannerSyncedCopy =
    'Your Monero wallet is synced.';
const String kMoneroScannerFailedCopy =
    'Scanner temporarily unavailable';
const String kMoneroScannerStoppedCopy =
    'Scanner not enabled';
const String kMoneroScannerDaemonPrivacyNote =
    'VaultAI does not send your seed, spend key, or view key to a '
    'scanner.';


class CryptoWalletEngineMoneroScannerCard extends StatelessWidget {
  final MoneroScannerAdapter scannerAdapter;
  final CryptoWalletFeatures? features;
  final MoneroSyncStatus? status;
  final VoidCallback? onStart;
  final VoidCallback? onStop;

  final int? initialRestoreHeight;
  final void Function(int)? onRestoreHeightChanged;


  final MoneroScannerStatus? backendStatus;

  const CryptoWalletEngineMoneroScannerCard({
    super.key,
    required this.scannerAdapter,
    this.features,
    this.status,
    this.onStart,
    this.onStop,
    this.initialRestoreHeight,
    this.onRestoreHeightChanged,
    this.backendStatus,
  });

  bool get _isAvailable => scannerAdapter.isAvailable;

  MoneroSyncStatus get _effectiveStatus {
    final s = status;
    if (s != null) return s;
    if (!_isAvailable) return MoneroSyncStatus.scannerUnavailable();
    return MoneroSyncStatus.notStarted(restoreHeight: 0);
  }

  @override
  Widget build(BuildContext context) {
    final s = _effectiveStatus;
    return Container(
      key: const Key(kMoneroScannerCardKey),
      padding: const EdgeInsets.all(16),
      decoration: walletDarkCard(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHeader(),
          const SizedBox(height: 8),
          _buildStateLine(s),
          const SizedBox(height: 6),
          if (s.isSyncing || s.isSynced || s.isStopped || s.isFailed)
            _buildProgressBlock(s),
          if (s.errorReason != null && s.errorReason!.isNotEmpty)
            _buildErrorLine(s.errorReason!),

          if (_shouldShowRestoreHeightSection(s)) ...[
            const SizedBox(height: 10),
            _MoneroScannerRestoreHeightInput(
              initialValue: initialRestoreHeight ?? s.restoreHeight,
              onChanged: onRestoreHeightChanged,
            ),
          ],
          const SizedBox(height: 10),
          _buildControls(s),
          const SizedBox(height: 12),
          _buildInstructions(s),
          const SizedBox(height: 8),
          _buildPrivacyNote(),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return const Row(
      key: Key(kMoneroScannerHeadingKey),
      children: [
        Icon(Icons.radar_rounded, size: 18,
            color: kWalletTextSecondary),
        SizedBox(width: 8),
        Text(
          kMoneroScannerHeading,
          style: kWalletSectionHeadingStyle,
        ),
      ],
    );
  }

  Widget _buildStateLine(MoneroSyncStatus s) {


    final backend = backendStatus;
    final backendReason = backend?.reason;
    final backendOverride = backendReason != null && const <String>{
      kMoneroScannerReasonRequiresDesktop,
      kMoneroScannerReasonLocalAvailable,
      kMoneroScannerReasonNotConfigured,
      kMoneroScannerReasonViewKeyMissing,
      kMoneroScannerReasonUnreachable,
      kMoneroScannerReasonSyncing,
      kMoneroScannerReasonReady,
      kMoneroScannerReasonError,
    }.contains(backendReason);
    final label = backendOverride
        ? moneroScannerBalanceCopyForReason(backendReason)
        : _labelFor(s.state);
    return Text(
      label,
      key: const Key(kMoneroScannerStateKey),
      style: kWalletBodyStyle,
    );
  }

  Widget _buildProgressBlock(MoneroSyncStatus s) {
    final rh = s.restoreHeight;
    final ch = s.currentHeight;
    final th = s.targetHeight;
    final pct = s.percent;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Wrap(
        spacing: 12,
        runSpacing: 6,
        children: [
          if (rh > 0)
            _pill(
              const Key(kMoneroScannerRestoreHeightKey),
              'Restore height: $rh',
            ),
          if (ch != null)
            _pill(
              const Key(kMoneroScannerCurrentHeightKey),
              'Current height: $ch',
            ),
          if (th != null)
            _pill(
              const Key(kMoneroScannerTargetHeightKey),
              'Target height: $th',
            ),
          if (pct != null)
            _pill(
              const Key(kMoneroScannerPercentKey),
              '${(pct * 100).clamp(0.0, 100.0).toStringAsFixed(1)}%',
            ),
          if (s.lastUpdatedAt != null)
            _pill(
              const Key(kMoneroScannerLastUpdatedKey),
              'Updated ${s.lastUpdatedAt!.toIso8601String()}',
            ),
        ],
      ),
    );
  }

  Widget _pill(Key key, String text) {
    return Container(
      key: key,
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: kWalletBgBase,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: kWalletBorder),
      ),
      child: Text(text, style: kWalletMutedStyle),
    );
  }

  Widget _buildErrorLine(String reason) {
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Text(
        reason,
        key: const Key(kMoneroScannerErrorReasonKey),
        style: const TextStyle(
          color: kWalletAccentDanger, fontSize: 13,
        ),
      ),
    );
  }

  Widget _buildControls(MoneroSyncStatus s) {
    if (!_isAvailable) {

      return const SizedBox(
        key: Key(kMoneroScannerUnavailableCopyKey),
        height: 0,
      );
    }
    if (s.isSyncing) {
      return ElevatedButton.icon(
        key: const Key(kMoneroScannerStopBtnKey),
        onPressed: onStop,
        icon: const Icon(Icons.stop_rounded, size: 16),
        label: const Text(kMoneroScannerStopLabel),
        style: walletSecondaryButtonStyle(),
      );
    }
    return ElevatedButton.icon(
      key: const Key(kMoneroScannerStartBtnKey),
      onPressed: onStart,
      icon: const Icon(Icons.play_arrow_rounded, size: 16),
      label: const Text(kMoneroScannerStartLabel),
      style: walletPrimaryButtonStyle(),
    );
  }

  Widget _buildInstructions(MoneroSyncStatus s) {

    if (!s.isSyncing) {
      return const Text(
        kMoneroScannerRequiresWalletCopy,
        style: kWalletBodyStyle,
      );
    }


    return const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(kMoneroScannerRequiresWalletCopy, style: kWalletBodyStyle),
        SizedBox(height: 4),
        Text(kMoneroScannerRunsOnDeviceCopy, style: kWalletBodyStyle),
        SizedBox(height: 4),
        Text(kMoneroScannerDoNotCloseAppCopy, style: kWalletBodyStyle),
        SizedBox(height: 4),
        Text(kMoneroScannerSyncTimeCopy, style: kWalletBodyStyle),
      ],
    );
  }

  Widget _buildPrivacyNote() {
    return Container(
      key: const Key(kMoneroScannerPrivacyNoteKey),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: kWalletBgBase,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: kWalletBorder),
      ),
      child: const Row(
        children: [
          Icon(Icons.privacy_tip_outlined, size: 14,
              color: kWalletTextSecondary),
          SizedBox(width: 8),
          Expanded(
            child: Text(
              kMoneroScannerDaemonPrivacyNote,
              style: kWalletMutedStyle,
            ),
          ),
        ],
      ),
    );
  }

  bool _shouldShowRestoreHeightSection(MoneroSyncStatus s) {


    if (!_isAvailable) return false;
    return s.state == MoneroScannerState.notStarted;
  }

  String _labelFor(MoneroScannerState state) {
    switch (state) {
      case MoneroScannerState.scannerUnavailable:
        return kMoneroScannerUnavailableCopy;
      case MoneroScannerState.notStarted:
        return kMoneroScannerNotStartedCopy;
      case MoneroScannerState.syncing:
        return kMoneroScannerSyncingCopy;
      case MoneroScannerState.synced:
        return kMoneroScannerSyncedCopy;
      case MoneroScannerState.failed:
        return kMoneroScannerFailedCopy;
      case MoneroScannerState.stopped:
        return kMoneroScannerStoppedCopy;
    }
  }
}


class _MoneroScannerRestoreHeightInput extends StatefulWidget {
  final int initialValue;
  final void Function(int)? onChanged;

  const _MoneroScannerRestoreHeightInput({
    required this.initialValue,
    this.onChanged,
  });

  @override
  State<_MoneroScannerRestoreHeightInput> createState() =>
      _MoneroScannerRestoreHeightInputState();
}


class _MoneroScannerRestoreHeightInputState
    extends State<_MoneroScannerRestoreHeightInput> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(
      text: widget.initialValue > 0
          ? widget.initialValue.toString()
          : '',
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _handleChanged(String raw) {
    if (widget.onChanged == null) return;
    final v = int.tryParse(raw.trim());
    if (v == null || v < 0) return;
    widget.onChanged!(v);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key(kMoneroScannerRestoreHeightSectionKey),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: kWalletBgBase,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: kWalletBorder),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            kMoneroScannerRestoreHeightLabel,
            style: TextStyle(
              color: kWalletTextSecondary,
              fontSize: 12,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.3,
            ),
          ),
          const SizedBox(height: 4),
          const Text(
            kMoneroScannerRestoreHeightExplainer,
            style: kWalletMutedStyle,
          ),
          const SizedBox(height: 8),
          TextField(
            key: const Key(kMoneroScannerRestoreHeightFieldKey),
            controller: _controller,
            keyboardType: const TextInputType.numberWithOptions(
              signed: false, decimal: false,
            ),
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            style: const TextStyle(
              color: kWalletTextPrimary,
              fontSize: 14,
              fontFamily: 'monospace',
            ),
            decoration: const InputDecoration(
              isDense: true,
              hintText: 'Block height',
              hintStyle: TextStyle(color: kWalletTextMuted),
              filled: true,
              fillColor: kWalletSurfaceElevated,
              contentPadding: EdgeInsets.symmetric(
                horizontal: 10, vertical: 8,
              ),
              border: OutlineInputBorder(),
            ),
            onChanged: _handleChanged,
          ),
        ],
      ),
    );
  }
}
