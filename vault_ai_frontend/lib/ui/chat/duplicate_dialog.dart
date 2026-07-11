

import 'package:flutter/material.dart';

import '../../services/content_hash.dart';
import '../../l10n/app_localizations.dart';
import '../primitives.dart';
import '../tokens.dart';


enum DuplicateDialogChoice { skip, keepBoth, cancel }


class DuplicateUploadDialog extends StatelessWidget {
  final DuplicateFoundDetail detail;

  const DuplicateUploadDialog({
    super.key,
    required this.detail,
  });

  
  static Future<DuplicateDialogChoice> show(
    BuildContext context, {
    required DuplicateFoundDetail detail,
  }) async {
    final picked = await showDialog<DuplicateDialogChoice>(
      context: context,
      barrierDismissible: true,
      builder: (_) => DuplicateUploadDialog(detail: detail),
    );
    return picked ?? DuplicateDialogChoice.cancel;
  }

  @override
  Widget build(BuildContext context) {
    final existingName =
        (detail.existingSavedName != null &&
                detail.existingSavedName!.isNotEmpty)
            ? detail.existingSavedName!
            : (detail.existingFileName ?? 'this file');
    final existingPath = (detail.existingRelativePath ?? '').trim();

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
        child: SingleChildScrollView(
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
                      icon: Icons.content_copy_outlined,
                      color: VaultColors.severityWarn,
                      size: 40,
                    ),
                    const SizedBox(width: VaultSpacing.md),
                    Expanded(
                      child: Text(
                        'This file already exists in your vault.',
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: VaultText.subtitle,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: VaultSpacing.lg),
                _ExistingFileRow(
                  name: existingName,
                  relativePath: existingPath,
                ),
                const SizedBox(height: VaultSpacing.md),
                Text(
                  'Skip this upload to save space, or keep both copies?',
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
                          DuplicateDialogChoice.skip,
                        ),
                        child: const Text('Skip'),
                      ),
                      FilledButton(
                        onPressed: () => Navigator.of(context).pop(
                          DuplicateDialogChoice.keepBoth,
                        ),
                        child: Text(
                            AppLocalizations.of(context).chatCardKeepBoth),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ExistingFileRow extends StatelessWidget {
  final String name;
  final String relativePath;

  const _ExistingFileRow({
    required this.name,
    required this.relativePath,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(VaultSpacing.md),
      decoration: BoxDecoration(
        color: VaultColors.surfaceMuted,
        borderRadius: BorderRadius.circular(VaultRadius.md),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          const Icon(
            Icons.insert_drive_file_outlined,
            size: 18,
            color: VaultColors.accentBright,
          ),
          const SizedBox(width: VaultSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: VaultText.subtitle.copyWith(fontSize: 14),
                ),
                if (relativePath.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      const Icon(
                        Icons.folder_outlined,
                        size: 12,
                        color: VaultColors.textTertiary,
                      ),
                      const SizedBox(width: 4),
                      Expanded(
                        child: Text(
                          relativePath,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: VaultText.caption,
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}


String formatImportSummary({
  required int savedCount,
  required int skippedDuplicateCount,
  required int failedCount,
  int renamedCount = 0,
}) {
  final parts = <String>[];

  if (savedCount == 0 &&
      skippedDuplicateCount == 0 &&
      failedCount == 0 &&
      renamedCount == 0) {
    return 'Nothing to import.';
  }

  if (savedCount > 0) {
    parts.add(
      savedCount == 1
          ? 'Saved 1 file.'
          : 'Saved $savedCount files.',
    );
  }
  if (renamedCount > 0) {
    parts.add(
      renamedCount == 1
          ? 'Renamed 1 file to avoid name conflicts.'
          : 'Renamed $renamedCount files to avoid name conflicts.',
    );
  }
  if (skippedDuplicateCount > 0) {
    parts.add(
      skippedDuplicateCount == 1
          ? 'Skipped 1 duplicate already in your vault.'
          : 'Skipped $skippedDuplicateCount duplicates already in your vault.',
    );
  }
  if (failedCount > 0) {
    parts.add(
      failedCount == 1
          ? '1 upload failed.'
          : '$failedCount uploads failed.',
    );
  }
  return parts.join(' ');
}


enum NameConflictDialogChoice { keepBoth, cancel, replace }

class NameConflictDialog extends StatelessWidget {
  final NameConflictDetail detail;

  const NameConflictDialog({super.key, required this.detail});

  
  static Future<NameConflictDialogChoice> show(
    BuildContext context, {
    required NameConflictDetail detail,
  }) async {
    final picked = await showDialog<NameConflictDialogChoice>(
      context: context,
      barrierDismissible: true,
      builder: (_) => NameConflictDialog(detail: detail),
    );
    return picked ?? NameConflictDialogChoice.cancel;
  }

  @override
  Widget build(BuildContext context) {
    final existingName =
        (detail.existingSavedName != null &&
                detail.existingSavedName!.isNotEmpty)
            ? detail.existingSavedName!
            : (detail.existingFileName ?? 'this file');
    final existingPath = (detail.existingRelativePath ?? '').trim();
    final proposed = (detail.proposedVersionedName ?? '').trim();

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
        child: SingleChildScrollView(
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
                      icon: Icons.edit_document,
                      color: VaultColors.severityInfo,
                      size: 40,
                    ),
                    const SizedBox(width: VaultSpacing.md),
                    Expanded(
                      child: Text(
                        'A file with this name already exists in this '
                        'folder, but the content is different.',
                        maxLines: 4,
                        overflow: TextOverflow.ellipsis,
                        style: VaultText.subtitle,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: VaultSpacing.lg),
                _ExistingFileRow(
                  name: existingName,
                  relativePath: existingPath,
                ),
                if (proposed.isNotEmpty) ...[
                  const SizedBox(height: VaultSpacing.md),
                  Text(
                    'Keep both will save the new file as "$proposed".',
                    style: VaultText.caption,
                  ),
                ],
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
                          NameConflictDialogChoice.cancel,
                        ),
                        child: Text(
                            AppLocalizations.of(context).commonCancel),
                      ),
                      FilledButton(
                        onPressed: () => Navigator.of(context).pop(
                          NameConflictDialogChoice.keepBoth,
                        ),
                        child: Text(
                            AppLocalizations.of(context).chatCardKeepBoth),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
