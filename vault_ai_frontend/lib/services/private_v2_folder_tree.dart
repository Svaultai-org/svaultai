/// Opt-in local navigation requires a signed, complete file inventory.
const bool kEnablePrivateLocalFolderTree = bool.fromEnvironment(
  'VAULTAI_ENABLE_PRIVATE_LOCAL_FOLDER_TREE',
  defaultValue: false,
);

/// Build folder navigation from a complete, signed PIN-free file inventory.
/// The caller must establish that the inventory belongs to the current vault
/// session. No decrypted path is sent to `/folders`, including old paths.
Map<String, dynamic> buildPrivateLocalFolderTree({
  required String path,
  required List<Map<String, dynamic>> files,
}) {
  List<String> segments(String value) {
    if (value.isEmpty) return const <String>[];
    final parts = value.split('/');
    if (parts.any(
      (part) =>
          part.isEmpty ||
          part == '.' ||
          part == '..' ||
          part.contains('\\') ||
          part.runes.any((rune) => rune < 32),
    )) {
      throw const FormatException('Invalid private folder path');
    }
    return parts;
  }

  final current = segments(path);
  final folders = <String, ({String name, int count})>{};
  final visibleFiles = <Map<String, dynamic>>[];
  final seenIds = <String>{};
  for (final file in files) {
    final id = file['id'];
    final name = file['file_name'];
    if (id is! String ||
        id.isEmpty ||
        !seenIds.add(id) ||
        name is! String ||
        name.isEmpty) {
      throw const FormatException('Private file inventory is incomplete');
    }
    final rawPath = file['relative_path'];
    if (rawPath != null && rawPath is! String) {
      throw const FormatException('Invalid private file path');
    }
    final parts = segments(rawPath as String? ?? '');
    final parent = parts.isEmpty
        ? const <String>[]
        : parts.sublist(0, parts.length - 1);
    if (parent.length < current.length ||
        Iterable<int>.generate(current.length).any(
          (index) =>
              parent[index].toLowerCase() != current[index].toLowerCase(),
        )) {
      continue;
    }
    if (parent.length == current.length) {
      visibleFiles.add(Map<String, dynamic>.from(file));
    } else {
      final child = parent[current.length];
      final key = child.toLowerCase();
      final previous = folders[key];
      folders[key] = (
        name: previous?.name ?? child,
        count: (previous?.count ?? 0) + 1,
      );
    }
  }
  final folderRows =
      folders.values
          .map(
            (folder) => <String, dynamic>{
              'name': folder.name,
              'file_count': folder.count,
            },
          )
          .toList()
        ..sort(
          (a, b) => '${a['name']}'.toLowerCase().compareTo(
            '${b['name']}'.toLowerCase(),
          ),
        );
  return <String, dynamic>{
    'path': path,
    'breadcrumbs': current,
    'folders': folderRows,
    'files': visibleFiles,
  };
}

/// Combine the server's older folder view with locally decrypted V2 paths.
/// V2 markers have no server-visible relative path, so they must be moved
/// out of the server's root response and placed from their manifest only.
Map<String, dynamic> mergePrivateV2FolderTree({
  required String path,
  required Map<String, dynamic>? serverTree,
  required List<Map<String, dynamic>> privateFiles,
}) {
  final ready = privateFiles
      .where((file) => file['v2_ready'] == true || file['v2_retired'] == true)
      .toList();
  final readyIds = ready.map((file) => '${file['id']}').toSet();
  final files = <Map<String, dynamic>>[
    for (final raw in (serverTree?['files'] as List? ?? const []))
      if (raw is Map && !readyIds.contains('${raw['id']}'))
        Map<String, dynamic>.from(raw),
  ];
  final folders = <String, ({String name, int count})>{};
  for (final raw in (serverTree?['folders'] as List? ?? const [])) {
    if (raw is! Map) continue;
    final name = raw['name'];
    final count = raw['file_count'];
    if (name is! String || name.isEmpty || count is! num) continue;
    folders[name.toLowerCase()] = (name: name, count: count.toInt());
  }

  final prefix = path.isEmpty ? '' : '$path/';
  for (final file in ready) {
    final relativePath = file['relative_path'];
    if (relativePath is! String || relativePath.isEmpty) {
      if (path.isEmpty) files.add(file);
      continue;
    }
    // Existing migrated files may have an old server-known path. New V2
    // paths are validated while decrypting their manifest. Ignore malformed
    // old paths here rather than treating them as navigation instructions.
    final parts = relativePath.split('/');
    if (parts.any((part) => part.isEmpty || part == '.' || part == '..')) {
      continue;
    }
    final parent = parts.length == 1
        ? ''
        : parts.sublist(0, parts.length - 1).join('/');
    if (parent.toLowerCase() == path.toLowerCase()) {
      files.add(file);
      continue;
    }
    if (!parent.toLowerCase().startsWith(prefix.toLowerCase())) continue;
    final rest = parent.substring(prefix.length);
    if (rest.isEmpty) continue;
    final name = rest.split('/').first;
    final key = name.toLowerCase();
    final current = folders[key];
    folders[key] = (
      name: current?.name ?? name,
      count: (current?.count ?? 0) + 1,
    );
  }
  final folderRows =
      folders.values
          .map(
            (folder) => <String, dynamic>{
              'name': folder.name,
              'file_count': folder.count,
            },
          )
          .toList()
        ..sort(
          (a, b) => '${a['name']}'.toLowerCase().compareTo(
            '${b['name']}'.toLowerCase(),
          ),
        );
  return <String, dynamic>{
    'path': path,
    'breadcrumbs': path.isEmpty ? <String>[] : path.split('/'),
    'folders': folderRows,
    'files': files,
  };
}
