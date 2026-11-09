/// Bounded inventory and copy coordinator for released private files.
///
/// A single file is copied by [transferReleasedV2FileStreamed]. This layer
/// enumerates all visible source files before any target write, copies each
/// with its own fresh beneficiary proof, and checks the owner's inventory
/// again before reporting the batch result. It does not claim a whole vault.
library;

typedef FetchReleasedV2FilePage = Future<Map<String, dynamic>> Function(
  String afterFileId,
);
typedef CopyReleasedV2File = Future<Map<String, dynamic>> Function(
  String sourceFileId,
);
typedef ExpectedInheritedTargetFileId = Future<String> Function(
  String sourceFileId,
);

const int maxInheritedV2BatchFiles = 1000;
const int maxInheritedV2BatchPages = 11;
const int maxInheritedV2BatchBytes = 16 * 1024 * 1024 * 1024;

class ReleasedV2FileBatchResult {
  final int copiedFiles;
  final int copiedBytes;

  const ReleasedV2FileBatchResult({
    required this.copiedFiles,
    required this.copiedBytes,
  });
}

class _FileEntry {
  final String id;
  final int bytes;
  final int chunkSize;
  final int chunkCount;
  final int nameVersion;

  const _FileEntry(
      this.id, this.bytes, this.chunkSize, this.chunkCount, this.nameVersion);

  bool sameAs(_FileEntry other) =>
      id == other.id &&
      bytes == other.bytes &&
      chunkSize == other.chunkSize &&
      chunkCount == other.chunkCount &&
      nameVersion == other.nameVersion;
}

Future<List<_FileEntry>> _readInventory({
  required int linkId,
  required String ownerVaultId,
  required FetchReleasedV2FilePage fetchPage,
  required bool Function() accessIsCurrent,
}) async {
  final entries = <_FileEntry>[];
  var after = '';
  var totalBytes = 0;
  for (var page = 0; page < maxInheritedV2BatchPages; page++) {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    final raw = await fetchPage(after);
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    if (raw['owner_vault_id'] != ownerVaultId ||
        raw['beneficiary_link_id'] != linkId ||
        raw['files'] is! List) {
      throw const FormatException('Inherited file inventory scope differs');
    }
    final rows = raw['files'] as List;
    if (rows.length > 100) {
      throw const FormatException('Inherited file page too large');
    }
    for (final row in rows) {
      if (row is! Map<String, dynamic> ||
          row['file_id'] is! String ||
          row['total_bytes'] is! int ||
          row['chunk_size'] is! int ||
          row['chunk_count'] is! int ||
          row['name_version'] is! int) {
        throw const FormatException('Invalid inherited file inventory row');
      }
      final id = row['file_id'] as String;
      final bytes = row['total_bytes'] as int;
      final size = row['chunk_size'] as int;
      final count = row['chunk_count'] as int;
      final version = row['name_version'] as int;
      if (!RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(id) ||
          id.compareTo(after) <= 0 ||
          bytes < 0 ||
          bytes > 512 * 1024 * 1024 ||
          size <= 0 ||
          size > 1024 * 1024 ||
          count < 0 ||
          count > 4096 ||
          count != (bytes + size - 1) ~/ size ||
          version < 0) {
        throw const FormatException('Invalid inherited file inventory row');
      }
      entries.add(_FileEntry(id, bytes, size, count, version));
      after = id;
      totalBytes += bytes;
      if (entries.length > maxInheritedV2BatchFiles ||
          totalBytes > maxInheritedV2BatchBytes) {
        throw StateError('Inherited file batch exceeds safe limit');
      }
    }
    final next = raw['next_after_file_id'];
    if (next == null) return entries;
    if (next is! String || rows.isEmpty || next != after) {
      throw const FormatException('Invalid inherited file page cursor');
    }
  }
  throw StateError('Inherited file inventory exceeds page limit');
}

Future<ReleasedV2FileBatchResult> copyReleasedV2FileInventory({
  required int linkId,
  required String ownerVaultId,
  required FetchReleasedV2FilePage fetchPage,
  required CopyReleasedV2File copyFile,
  required ExpectedInheritedTargetFileId expectedTargetFileId,
  required bool Function() accessIsCurrent,
  void Function(int completed, int total)? onFileProgress,
}) async {
  if (linkId <= 0 || ownerVaultId.isEmpty) {
    throw ArgumentError('Invalid inheritance identity');
  }
  final initial = await _readInventory(
    linkId: linkId,
    ownerVaultId: ownerVaultId,
    fetchPage: fetchPage,
    accessIsCurrent: accessIsCurrent,
  );
  var copiedBytes = 0;
  for (var i = 0; i < initial.length; i++) {
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    final expectedId = await expectedTargetFileId(initial[i].id);
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    final result = await copyFile(initial[i].id);
    if (!accessIsCurrent()) throw StateError('Vault access changed');
    if (result['file_id'] != expectedId ||
        !const {'published', 'already_published'}.contains(result['status'])) {
      throw const FormatException('Inherited file copy unconfirmed');
    }
    copiedBytes += initial[i].bytes;
    onFileProgress?.call(i + 1, initial.length);
  }
  final finalInventory = await _readInventory(
    linkId: linkId,
    ownerVaultId: ownerVaultId,
    fetchPage: fetchPage,
    accessIsCurrent: accessIsCurrent,
  );
  if (initial.length != finalInventory.length) {
    throw StateError('Inherited file inventory changed during copy');
  }
  for (var i = 0; i < initial.length; i++) {
    if (!initial[i].sameAs(finalInventory[i])) {
      throw StateError('Inherited file inventory changed during copy');
    }
  }
  return ReleasedV2FileBatchResult(
    copiedFiles: initial.length,
    copiedBytes: copiedBytes,
  );
}
