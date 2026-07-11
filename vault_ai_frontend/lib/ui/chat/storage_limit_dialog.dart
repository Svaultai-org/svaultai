

import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import '../primitives.dart';
import '../tokens.dart';


enum StorageLimitDialogChoice { upgrade, cancel }

class NotEnoughStorageDialog extends StatelessWidget {
  
  
  final int plannedBytes;

  
  final int availableBytes;

  
  final String? folderName;

  const NotEnoughStorageDialog({
    super.key,
    required this.plannedBytes,
    required this.availableBytes,
    this.folderName,
  });

  
  static Future<StorageLimitDialogChoice> show(
    BuildContext context, {
    required int plannedBytes,
    required int availableBytes,
    String? folderName,
  }) async {
    final picked = await showDialog<StorageLimitDialogChoice>(
      context: context,
      barrierDismissible: true,
      builder: (_) => NotEnoughStorageDialog(
        plannedBytes: plannedBytes,
        availableBytes: availableBytes,
        folderName: folderName,
      ),
    );
    return picked ?? StorageLimitDialogChoice.cancel;
  }

  @override
  Widget build(BuildContext context) {
    final headline = (folderName != null && folderName!.isNotEmpty)
        ? 'Not enough storage for $folderName'
        : 'Not enough storage for this folder.';

    final screenW = MediaQuery.of(context).size.width;
    final dialogMax = screenW < 480 + 32 ? screenW - 32 : 480.0;
    return Dialog(
      backgroundColor: VaultColors.surface,
      insetPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 24),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(VaultRadius.lg),
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: dialogMax),
        child: Padding(
          padding: EdgeInsets.all(
              screenW < 400 ? VaultSpacing.md : VaultSpacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const IconBadge(
                    icon: Icons.cloud_off_outlined,
                    color: VaultColors.severityWarn,
                    size: 40,
                  ),
                  const SizedBox(width: VaultSpacing.md),
                  Expanded(
                    child: Text(
                      headline,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: VaultText.subtitle,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: VaultSpacing.lg),
              Text(
                'This import needs ${formatStorageBytes(plannedBytes)}, '
                'but you only have ${formatStorageBytes(availableBytes)} '
                'available.',
                style: VaultText.body,
              ),
              const SizedBox(height: VaultSpacing.lg),
              Align(
                alignment: Alignment.centerRight,
                child: Wrap(
                  alignment: WrapAlignment.end,
                  spacing: VaultSpacing.sm,
                  runSpacing: VaultSpacing.sm,
                  children: [
                    TextButton(
                      onPressed: () => Navigator.of(context).pop(
                        StorageLimitDialogChoice.cancel,
                      ),
                      child: Text(AppLocalizations.of(context).commonCancel),
                    ),
                    FilledButton(
                      onPressed: () => Navigator.of(context).pop(
                        StorageLimitDialogChoice.upgrade,
                      ),
                      child: Text(
                        AppLocalizations.of(context).chatCardUpgradeStorage,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}


String formatStorageBytes(int bytes) {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var size = bytes.toDouble();
  var i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  final s = (size >= 10 || i == 0)
      ? size.toStringAsFixed(0)
      : size.toStringAsFixed(1);
  return '$s ${units[i]}';
}
