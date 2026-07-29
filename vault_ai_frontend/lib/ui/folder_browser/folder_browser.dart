import 'package:flutter/material.dart';

class FolderNode {
  final String name;
  final int fileCount;

  const FolderNode({required this.name, required this.fileCount});

  factory FolderNode.fromJson(Map<String, dynamic> json) {
    return FolderNode(
      name: (json['name'] ?? '').toString(),
      fileCount: (json['file_count'] as num?)?.toInt() ?? 0,
    );
  }
}

class FolderTreeData {
  final String path;

  final List<String> breadcrumbs;

  final List<FolderNode> folders;

  final List<Map<String, dynamic>> files;

  const FolderTreeData({
    required this.path,
    required this.breadcrumbs,
    required this.folders,
    required this.files,
  });

  factory FolderTreeData.fromJson(Map<String, dynamic> json) {
    final folders = (json['folders'] as List<dynamic>? ?? const [])
        .map((e) => FolderNode.fromJson(
              e is Map<String, dynamic>
                  ? e
                  : Map<String, dynamic>.from(e as Map),
            ))
        .toList(growable: false);
    final files = (json['files'] as List<dynamic>? ?? const [])
        .map<Map<String, dynamic>>((e) =>
            e is Map<String, dynamic> ? e : Map<String, dynamic>.from(e as Map))
        .toList(growable: false);
    final breadcrumbs = (json['breadcrumbs'] as List<dynamic>? ?? const [])
        .map((e) => e.toString())
        .toList(growable: false);
    return FolderTreeData(
      path: (json['path'] ?? '').toString(),
      breadcrumbs: breadcrumbs,
      folders: folders,
      files: files,
    );
  }

  bool get isEmpty => folders.isEmpty && files.isEmpty;
}

class FolderBrowser extends StatelessWidget {
  final FolderTreeData treeData;

  final void Function(String path) onNavigateToPath;

  final Widget Function(Map<String, dynamic> file) fileItemBuilder;

  final String searchQuery;
  final ValueChanged<String>? onSearchChanged;

  final bool isMobile;

  final Widget? headerSlot;

  static const double maxHeightDesktop = 520;
  static const double maxHeightMobile = 360;

  const FolderBrowser({
    super.key,
    required this.treeData,
    required this.onNavigateToPath,
    required this.fileItemBuilder,
    this.searchQuery = '',
    this.onSearchChanged,
    this.isMobile = false,
    this.headerSlot,
  });

  @override
  Widget build(BuildContext context) {
    final maxHeight = isMobile ? maxHeightMobile : maxHeightDesktop;
    final filtered = _applySearchFilter(treeData, searchQuery);
    return Container(
      margin: EdgeInsets.fromLTRB(isMobile ? 12 : 16, 0, isMobile ? 12 : 16, 0),
      padding: EdgeInsets.symmetric(
          horizontal: isMobile ? 12 : 16, vertical: isMobile ? 10 : 14),
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A1A),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (headerSlot != null) ...[
            headerSlot!,
            const SizedBox(height: 10),
          ],
          _Breadcrumbs(
            breadcrumbs: treeData.breadcrumbs,
            onNavigateToPath: onNavigateToPath,
            isMobile: isMobile,
          ),
          if (onSearchChanged != null) ...[
            const SizedBox(height: 8),
            _SearchField(
              initialQuery: searchQuery,
              onChanged: onSearchChanged!,
              isMobile: isMobile,
            ),
          ],
          const SizedBox(height: 8),
          if (filtered.isEmpty)
            _EmptyState(isSearching: searchQuery.trim().isNotEmpty)
          else
            ConstrainedBox(
              constraints: BoxConstraints(maxHeight: maxHeight),
              child: Scrollbar(
                child: ListView.builder(
                  shrinkWrap: true,
                  padding: EdgeInsets.zero,
                  itemCount: filtered.folders.length + filtered.files.length,
                  itemBuilder: (context, index) {
                    if (index < filtered.folders.length) {
                      final folder = filtered.folders[index];
                      return _FolderRow(
                        folder: folder,
                        currentPath: treeData.path,
                        onTap: () => onNavigateToPath(
                          treeData.path.isEmpty
                              ? folder.name
                              : '${treeData.path}/${folder.name}',
                        ),
                        isMobile: isMobile,
                      );
                    }
                    final fileIndex = index - filtered.folders.length;
                    return fileItemBuilder(filtered.files[fileIndex]);
                  },
                ),
              ),
            ),
        ],
      ),
    );
  }

  static FolderTreeData _applySearchFilter(
    FolderTreeData data,
    String query,
  ) {
    final q = query.trim().toLowerCase();
    if (q.isEmpty) return data;
    final folders = data.folders
        .where((f) => f.name.toLowerCase().contains(q))
        .toList(growable: false);
    final files = data.files.where((file) {
      bool matches(Object? value) {
        if (value == null) return false;
        return value.toString().toLowerCase().contains(q);
      }

      return matches(file['file_name']) ||
          matches(file['saved_name']) ||
          matches(file['relative_path']);
    }).toList(growable: false);
    return FolderTreeData(
      path: data.path,
      breadcrumbs: data.breadcrumbs,
      folders: folders,
      files: files,
    );
  }
}

class _Breadcrumbs extends StatelessWidget {
  final List<String> breadcrumbs;
  final void Function(String path) onNavigateToPath;
  final bool isMobile;

  const _Breadcrumbs({
    required this.breadcrumbs,
    required this.onNavigateToPath,
    required this.isMobile,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _Crumb(
            label: 'Root',
            icon: Icons.home_outlined,
            onTap: () => onNavigateToPath(''),
            isCurrent: breadcrumbs.isEmpty,
            isMobile: isMobile,
          ),
          for (var i = 0; i < breadcrumbs.length; i++) ...[
            Icon(
              Icons.chevron_right,
              size: isMobile ? 16 : 18,
              color: Colors.white38,
            ),
            _Crumb(
              label: breadcrumbs[i],
              icon: null,
              onTap: () => onNavigateToPath(
                breadcrumbs.sublist(0, i + 1).join('/'),
              ),
              isCurrent: i == breadcrumbs.length - 1,
              isMobile: isMobile,
            ),
          ],
        ],
      ),
    );
  }
}

class _Crumb extends StatelessWidget {
  final String label;
  final IconData? icon;
  final VoidCallback onTap;
  final bool isCurrent;
  final bool isMobile;

  const _Crumb({
    required this.label,
    required this.icon,
    required this.onTap,
    required this.isCurrent,
    required this.isMobile,
  });

  @override
  Widget build(BuildContext context) {
    final fg = isCurrent ? Colors.white : const Color(0xFF10A37F);
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: EdgeInsets.symmetric(
            horizontal: isMobile ? 6 : 8, vertical: isMobile ? 4 : 6),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: isMobile ? 14 : 16, color: fg),
              const SizedBox(width: 4),
            ],
            Text(
              label,
              style: TextStyle(
                color: fg,
                fontSize: isMobile ? 12 : 13,
                fontWeight: isCurrent ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SearchField extends StatefulWidget {
  final String initialQuery;
  final ValueChanged<String> onChanged;
  final bool isMobile;

  const _SearchField({
    required this.initialQuery,
    required this.onChanged,
    required this.isMobile,
  });

  @override
  State<_SearchField> createState() => _SearchFieldState();
}

class _SearchFieldState extends State<_SearchField> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialQuery);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      identifier: 'files_search_field',
      textField: true,
      child: TextField(
        key: const Key('files_search_field'),
        controller: _controller,
        onChanged: widget.onChanged,
        style: const TextStyle(color: Colors.white, fontSize: 13),
        decoration: InputDecoration(
          hintText: 'Search files and folders',
          hintStyle: const TextStyle(color: Color(0xFF8E8E8E)),
          isDense: true,
          prefixIcon: Icon(
            Icons.search,
            size: widget.isMobile ? 18 : 20,
            color: const Color(0xFF8E8E8E),
          ),
          suffixIcon: _controller.text.isEmpty
              ? null
              : IconButton(
                  icon: const Icon(Icons.close, size: 16),
                  onPressed: () {
                    _controller.clear();
                    widget.onChanged('');
                    setState(() {});
                  },
                ),
          filled: true,
          fillColor: const Color(0xFF2F2F2F),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide.none,
          ),
        ),
      ),
    );
  }
}

class _FolderRow extends StatelessWidget {
  final FolderNode folder;
  final String currentPath;
  final VoidCallback onTap;
  final bool isMobile;

  const _FolderRow({
    required this.folder,
    required this.currentPath,
    required this.onTap,
    required this.isMobile,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: EdgeInsets.symmetric(
            horizontal: isMobile ? 10 : 14, vertical: isMobile ? 10 : 12),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.03),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white10),
        ),
        child: Row(
          children: [
            Container(
              width: isMobile ? 36 : 44,
              height: isMobile ? 36 : 44,
              decoration: BoxDecoration(
                color: const Color(0xFFFFC107).withValues(alpha: 0.16),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(
                Icons.folder,
                color: const Color(0xFFFFC107),
                size: isMobile ? 22 : 26,
              ),
            ),
            SizedBox(width: isMobile ? 10 : 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    folder.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: isMobile ? 14 : 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    folder.fileCount == 1
                        ? '1 file'
                        : '${folder.fileCount} files',
                    style: const TextStyle(
                      color: Color(0xFFB4B4B4),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            Icon(
              Icons.chevron_right,
              size: 20,
              color: Colors.white38,
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final bool isSearching;

  const _EmptyState({required this.isSearching});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 24),
      child: Center(
        child: Text(
          isSearching ? 'No matches.' : 'This folder is empty.',
          style: const TextStyle(
            color: Color(0xFF8E8E8E),
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}
