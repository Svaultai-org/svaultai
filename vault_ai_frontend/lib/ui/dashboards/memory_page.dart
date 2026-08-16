import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../api_client.dart';
import '../../services/memory_v2_repository.dart';
import '../../services/release_feature_contract.dart';
import '../../l10n/app_localizations.dart';
import '../motion.dart';
import '../primitives.dart';
import '../tokens.dart';
import 'dashboard_shell.dart';

const List<String> _memoryTypeOrder = [
  'identity',
  'relationship',
  'family',
  'company',
  'travel',
  'project',
  'goal',
  'location',
  'date',
  'life_event',
  'preference',
  'note',
];

String _normalizeMemoryType(String type) {
  switch (type) {
    case 'people':
      return 'relationship';
    case 'business':
      return 'company';
    case 'projects':
      return 'project';
    case 'goals':
      return 'goal';
    case 'places':
      return 'location';
    case 'dates':
      return 'date';
    case 'preferences':
      return 'preference';
    default:
      return type;
  }
}

String _memoryTypeLabel(AppLocalizations l, String type) {
  switch (type) {
    case 'identity':
      return l.memoryTypeIdentity;
    case 'people':
      return l.memoryTypePeople;
    case 'relationship':
      return l.memoryTypePeople;
    case 'family':
      return l.memoryTypeFamily;
    case 'business':
      return l.memoryTypeBusiness;
    case 'company':
      return l.memoryTypeBusiness;
    case 'travel':
      return l.memoryTypeTravel;
    case 'projects':
      return l.memoryTypeProjects;
    case 'project':
      return l.memoryTypeProjects;
    case 'goals':
      return l.memoryTypeGoals;
    case 'goal':
      return l.memoryTypeGoals;
    case 'places':
      return l.memoryTypePlaces;
    case 'location':
      return l.memoryTypePlaces;
    case 'dates':
      return l.memoryTypeDates;
    case 'date':
      return l.memoryTypeDates;
    case 'life_event':
      return l.memoryTypeLifeEvent;
    case 'preferences':
      return l.memoryTypePreferences;
    case 'preference':
      return l.memoryTypePreferences;
    case 'note':
      return l.memoryTypeNote;
    default:
      return type;
  }
}

const Map<String, IconData> _memoryTypeIcons = {
  'identity': Icons.badge_outlined,
  'people': Icons.people_outline,
  'relationship': Icons.people_outline,
  'family': Icons.family_restroom_outlined,
  'business': Icons.business_center_outlined,
  'company': Icons.business_center_outlined,
  'travel': Icons.flight_takeoff,
  'projects': Icons.task_alt_outlined,
  'project': Icons.task_alt_outlined,
  'goals': Icons.flag_outlined,
  'goal': Icons.flag_outlined,
  'places': Icons.place_outlined,
  'location': Icons.place_outlined,
  'dates': Icons.event_outlined,
  'date': Icons.event_outlined,
  'life_event': Icons.celebration_outlined,
  'preferences': Icons.tune_outlined,
  'preference': Icons.tune_outlined,
  'note': Icons.note_outlined,
};

const Map<String, Color> _memoryTypeAccents = {
  'identity': VaultColors.severityInfo,
  'people': VaultColors.accentBright,
  'relationship': VaultColors.accentBright,
  'family': VaultColors.severityCrit,
  'business': VaultColors.severityWarn,
  'company': VaultColors.severityWarn,
  'travel': VaultColors.severityInfo,
  'projects': VaultColors.accentBright,
  'project': VaultColors.accentBright,
  'goals': VaultColors.severityOk,
  'goal': VaultColors.severityOk,
  'places': VaultColors.severityInfo,
  'location': VaultColors.severityInfo,
  'dates': VaultColors.severityWarn,
  'date': VaultColors.severityWarn,
  'life_event': VaultColors.accentBright,
  'preferences': VaultColors.textSecondary,
  'preference': VaultColors.textSecondary,
  'note': VaultColors.textSecondary,
};

String _memoryRowRevealId(Map<String, dynamic> row) {
  final id = '${row['id'] ?? ''}'.trim();
  if (id.isNotEmpty) return id;
  return '${row['title'] ?? row['memory_key'] ?? row.hashCode}';
}

List<Map<String, String>> _memoryCustomFields(Map<String, dynamic>? row) {
  final raw = row?['custom_fields'];
  final fields = <Map<String, String>>[];
  if (raw is List) {
    for (final item in raw) {
      if (item is! Map) continue;
      final label = '${item['label'] ?? ''}'.trim();
      final value = '${item['value'] ?? ''}'.trim();
      if (label.isNotEmpty || value.isNotEmpty) {
        fields.add({'label': label, 'value': value});
      }
    }
  } else if (raw is Map) {
    for (final entry in raw.entries) {
      final label = '${entry.key}'.trim();
      final value = '${entry.value}'.trim();
      if (label.isNotEmpty || value.isNotEmpty) {
        fields.add({'label': label, 'value': value});
      }
    }
  }
  return fields;
}

String _memoryVisibleValue(Map<String, dynamic> row) {
  final value = ((row['value'] ?? row['memory_value']) as String?) ?? '';
  final body = (row['body'] as String?) ?? '';
  final lines = <String>[];
  if (value.trim().isNotEmpty) lines.add(value.trim());
  if (body.trim().isNotEmpty && body.trim() != value.trim()) {
    lines.add(body.trim());
  }
  for (final field in _memoryCustomFields(row)) {
    final label = field['label'] ?? '';
    final fieldValue = field['value'] ?? '';
    if (label.isEmpty && fieldValue.isEmpty) continue;
    if (label.isEmpty) {
      lines.add(fieldValue);
    } else if (fieldValue.isEmpty) {
      lines.add(label);
    } else {
      lines.add('$label: $fieldValue');
    }
  }
  return lines.join('\n');
}

class _MemoryCustomFieldCtrls {
  final TextEditingController label;
  final TextEditingController value;

  _MemoryCustomFieldCtrls({
    required this.label,
    required this.value,
  });

  void dispose() {
    label.dispose();
    value.dispose();
  }
}

Future<Map<String, dynamic>?> showMemoryEditorDialog(
  BuildContext context, {
  Map<String, dynamic>? row,
}) async {
  final titleCtrl = TextEditingController(
    text: ((row?['title'] ?? row?['memory_key']) as String?) ?? '',
  );
  final valueCtrl = TextEditingController(
    text: ((row?['value'] ?? row?['memory_value']) as String?) ?? '',
  );
  final dateCtrl = TextEditingController(
    text: (row?['event_date'] as String?) ?? '',
  );
  final tagsRaw = row?['tags'];
  final tagsCtrl = TextEditingController(
    text: tagsRaw is List
        ? tagsRaw.whereType<String>().join(', ')
        : '${tagsRaw ?? ''}'.trim(),
  );
  final customCtrls = [
    for (final field in _memoryCustomFields(row))
      _MemoryCustomFieldCtrls(
        label: TextEditingController(text: field['label'] ?? ''),
        value: TextEditingController(text: field['value'] ?? ''),
      ),
  ];
  var selectedType = (row?['memory_type'] as String?) ?? 'note';
  selectedType = _normalizeMemoryType(selectedType);
  String? localError;

  Map<String, dynamic>? result;
  try {
    result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) {
          void addField() {
            setLocal(() {
              customCtrls.add(_MemoryCustomFieldCtrls(
                label: TextEditingController(),
                value: TextEditingController(),
              ));
            });
          }

          void removeField(int index) {
            final removed = customCtrls.removeAt(index);
            removed.dispose();
            setLocal(() {});
          }

          return AlertDialog(
            title: Text(row == null ? 'New memory' : 'Edit memory'),
            content: SizedBox(
              width: 460,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      key: const Key('memory_dialog_title'),
                      controller: titleCtrl,
                      decoration: const InputDecoration(labelText: 'Title'),
                    ),
                    const SizedBox(height: VaultSpacing.md),
                    TextField(
                      key: const Key('memory_dialog_value'),
                      controller: valueCtrl,
                      minLines: 2,
                      maxLines: 5,
                      decoration: const InputDecoration(labelText: 'Memory'),
                    ),
                    const SizedBox(height: VaultSpacing.md),
                    DropdownButtonFormField<String>(
                      initialValue: selectedType,
                      decoration:
                          const InputDecoration(labelText: 'Type or category'),
                      items: _memoryTypeOrder
                          .map((type) => DropdownMenuItem(
                                value: _normalizeMemoryType(type),
                                child: Text(
                                  _memoryTypeLabel(
                                    AppLocalizations.of(context),
                                    _normalizeMemoryType(type),
                                  ),
                                ),
                              ))
                          .toList(),
                      onChanged: (v) {
                        if (v != null) setLocal(() => selectedType = v);
                      },
                    ),
                    const SizedBox(height: VaultSpacing.md),
                    TextField(
                      key: const Key('memory_dialog_tags'),
                      controller: tagsCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Tags',
                        hintText: 'travel, family, project',
                      ),
                    ),
                    const SizedBox(height: VaultSpacing.md),
                    TextField(
                      key: const Key('memory_dialog_event_date'),
                      controller: dateCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Date',
                        hintText: 'YYYY-MM-DD',
                      ),
                    ),
                    const SizedBox(height: VaultSpacing.md),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'Custom fields',
                        style: Theme.of(context).textTheme.labelLarge,
                      ),
                    ),
                    for (var i = 0; i < customCtrls.length; i++)
                      Padding(
                        padding: const EdgeInsets.only(top: VaultSpacing.sm),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: TextField(
                                key: Key('memory_dialog_custom_label_$i'),
                                controller: customCtrls[i].label,
                                decoration: const InputDecoration(
                                  labelText: 'Field label',
                                ),
                              ),
                            ),
                            const SizedBox(width: VaultSpacing.sm),
                            Expanded(
                              child: TextField(
                                key: Key('memory_dialog_custom_value_$i'),
                                controller: customCtrls[i].value,
                                obscureText: true,
                                decoration: const InputDecoration(
                                  labelText: 'Value',
                                ),
                              ),
                            ),
                            IconButton(
                              key: Key('memory_dialog_custom_remove_$i'),
                              tooltip: 'Remove field',
                              onPressed: () => removeField(i),
                              icon: const Icon(Icons.close, size: 18),
                            ),
                          ],
                        ),
                      ),
                    const SizedBox(height: VaultSpacing.sm),
                    OutlinedButton.icon(
                      key: const Key('memory_dialog_add_field'),
                      onPressed: addField,
                      icon: const Icon(Icons.add, size: 18),
                      label: const Text('Add field'),
                    ),
                    if (localError != null) ...[
                      const SizedBox(height: VaultSpacing.md),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Text(
                          localError!,
                          style:
                              const TextStyle(color: VaultColors.severityCrit),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel'),
              ),
              FilledButton.icon(
                key: const Key('memory_dialog_save'),
                onPressed: () {
                  final customFields = <Map<String, String>>[];
                  for (final field in customCtrls) {
                    final label = field.label.text.trim();
                    final value = field.value.text.trim();
                    if (label.isEmpty && value.isEmpty) continue;
                    customFields.add({'label': label, 'value': value});
                  }
                  final valueText = valueCtrl.text.trim();
                  if (valueText.isEmpty && customFields.isEmpty) {
                    setLocal(() {
                      localError = 'Add memory text or a custom field first';
                    });
                    return;
                  }
                  final title = titleCtrl.text.trim().isEmpty
                      ? 'Memory'
                      : titleCtrl.text.trim();
                  final eventDate = dateCtrl.text.trim();
                  final tags = tagsCtrl.text
                      .split(RegExp(r'[,#]'))
                      .map((t) => t.trim())
                      .where((t) => t.isNotEmpty)
                      .toList();
                  final effectiveValue =
                      valueText.isEmpty ? 'Structured memory' : valueText;
                  Navigator.pop(ctx, <String, dynamic>{
                    'title': title,
                    'value': effectiveValue,
                    'body': valueText,
                    'memory_type': selectedType,
                    'category': row?['category'] ?? selectedType,
                    'subject': row?['subject'] ?? 'self',
                    'subject_display': row?['subject_display'] ?? 'your',
                    'relationship': row?['relationship'] ?? 'self',
                    'attribute': row?['attribute'] ?? 'note',
                    if (eventDate.isNotEmpty) 'event_date': eventDate,
                    if (row?['place'] != null) 'place': row?['place'],
                    if (tags.isNotEmpty) 'tags': tags,
                    if (customFields.isNotEmpty) 'custom_fields': customFields,
                  });
                },
                icon: const Icon(Icons.check_rounded, size: 18),
                label: const Text('Save'),
              ),
            ],
          );
        },
      ),
    );
  } finally {
    // showDialog completes as the route begins closing; defer disposal so
    // TextField animations do not read controllers during the final frame.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        titleCtrl.dispose();
        valueCtrl.dispose();
        dateCtrl.dispose();
        tagsCtrl.dispose();
        for (final row in customCtrls) {
          row.dispose();
        }
      });
    });
  }
  return result;
}

class MemoryPage extends StatefulWidget {
  final VaultAIClient client;
  final String authToken;
  final String vaultName;
  final bool isMobile;
  final void Function(String prompt)? onAskVaultAI;
  final Future<String> Function()? pinProvider;

  const MemoryPage({
    super.key,
    required this.client,
    required this.authToken,
    required this.vaultName,
    required this.isMobile,
    this.onAskVaultAI,
    this.pinProvider,
  });

  @override
  State<MemoryPage> createState() => _MemoryPageState();
}

class _MemoryPageState extends State<MemoryPage> {
  static const _memoryV2Enabled = memoryV2ReadEnabled;
  static const _qaDiagnostics =
      bool.fromEnvironment('QA_CHAT_PRIVACY_DIAGNOSTICS', defaultValue: false);

  void _qaMemoryCreateStage(String stage) {
    if (_qaDiagnostics) print('MEMORY_CREATE_STAGE=$stage');
  }

  List<Map<String, dynamic>>? _items;
  Map<String, dynamic> _counts = const {};
  bool _loading = true;
  String? _error;
  String? _typeFilter;
  final TextEditingController _searchCtrl = TextEditingController();
  String _searchQuery = '';
  final Set<String> _revealedMemoryIds = <String>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _revealedMemoryIds.clear();
    _searchCtrl.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant MemoryPage old) {
    super.didUpdateWidget(old);
    if (old.vaultName != widget.vaultName ||
        old.authToken != widget.authToken) {
      _revealedMemoryIds.clear();
      _load();
    }
  }

  Future<void> _load() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
      _revealedMemoryIds.clear();
    });
    try {
      if (_memoryV2Enabled) {
        final rows = await MemoryV2Repository(
                baseUrl: widget.client.baseUrl, authToken: widget.authToken)
            .listDecrypted();
        if (!mounted) return;
        setState(() {
          _items = rows;
          _counts = {'total': rows.length};
          _loading = false;
        });
        return;
      }
      final pinProvider = widget.pinProvider;
      final res = pinProvider == null
          ? await widget.client.getMemoryTimeline(
              authToken: widget.authToken,
              vaultName: widget.vaultName,
            )
          : await widget.client.listMemories(
              authToken: widget.authToken,
              vaultName: widget.vaultName,
              pin: await pinProvider(),
            );
      if (!mounted) return;
      final raw = (res['items'] as List?) ?? const [];
      final counts = (res['counts'] is Map)
          ? (res['counts'] as Map).cast<String, dynamic>()
          : const <String, dynamic>{};
      setState(() {
        _items =
            raw.whereType<Map>().map((m) => m.cast<String, dynamic>()).toList();
        _counts = counts;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = '$e';
        _loading = false;
      });
    }
  }

  List<Map<String, dynamic>> get _filteredItems {
    final all = _items ?? const <Map<String, dynamic>>[];
    final query = _searchQuery.trim().toLowerCase();
    return all.where((m) {
      if (_typeFilter != null && m['memory_type'] != _typeFilter) {
        return false;
      }
      if (query.isEmpty) return true;
      final key =
          ((m['title'] ?? m['memory_key']) as String? ?? '').toLowerCase();
      final val =
          ((m['value'] ?? m['memory_value']) as String? ?? '').toLowerCase();
      final body = (m['body'] as String? ?? '').toLowerCase();
      final category = (m['category'] as String? ?? '').toLowerCase();
      final type = (m['memory_type'] as String? ?? '').toLowerCase();
      final tags = (m['tags'] is List)
          ? (m['tags'] as List).whereType<String>().join(' ').toLowerCase()
          : '';
      final custom = _memoryCustomFields(m)
          .map((f) => '${f['label'] ?? ''} ${f['value'] ?? ''}')
          .join(' ')
          .toLowerCase();
      return key.contains(query) ||
          val.contains(query) ||
          body.contains(query) ||
          category.contains(query) ||
          type.contains(query) ||
          tags.contains(query) ||
          custom.contains(query);
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return DashboardScaffold(
      isMobile: widget.isMobile,
      title: l.memoryTitle,
      subtitle: l.memorySubtitle,
      icon: Icons.auto_stories_outlined,
      iconColor: VaultColors.accentBright,
      actions: [
        ElevatedButton.icon(
          onPressed: _loading ? null : () => _showMemoryDialog(),
          icon: const Icon(Icons.add, size: 18),
          label: const Text('New memory'),
        ),
        OutlinedButton.icon(
          onPressed: _loading ? null : _load,
          icon: const Icon(Icons.refresh, size: 18),
          label: Text(l.commonRefresh),
        ),
      ],
      body: _buildBody(l),
    );
  }

  Widget _buildBody(AppLocalizations l) {
    if (_loading && _items == null) {
      return DashboardLoading(message: l.memoryLoading);
    }
    if (_error != null && _items == null) {
      return DashboardError(
        message: '${l.memoryErrorPrefix} $_error',
        onRetry: _load,
      );
    }
    final raw = _items ?? const <Map<String, dynamic>>[];
    if (raw.isEmpty) {
      return DashboardEmpty(
        title: l.memoryEmptyTitle,
        subtitle: l.memoryEmptySub,
        icon: Icons.auto_stories_outlined,
      );
    }

    final filtered = _filteredItems;
    final groups = _groupByYear(filtered);
    final isMobile = widget.isMobile;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _FilterControls(
          counts: _counts,
          totalCount: raw.length,
          activeType: _typeFilter,
          searchCtrl: _searchCtrl,
          onTypeChanged: (t) => setState(() => _typeFilter = t),
          onSearchChanged: (q) => setState(() => _searchQuery = q),
        ),
        if (filtered.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: VaultSpacing.lg),
            child: DashboardEmpty(
              title: l.memoryNoMatchTitle,
              subtitle: l.memoryNoMatchSub,
              icon: Icons.search_off,
            ),
          )
        else
          for (final group in groups)
            _YearGroup(
              year: group.year,
              items: group.items,
              isMobile: isMobile,
              onAskVaultAI: widget.onAskVaultAI,
              onEdit: (row) => _showMemoryDialog(row: row),
              onDelete: _deleteMemory,
              isRevealed: (row) =>
                  _revealedMemoryIds.contains(_memoryRowRevealId(row)),
              onReveal: (row) => setState(() {
                _revealedMemoryIds.add(_memoryRowRevealId(row));
              }),
              onHide: (row) => setState(() {
                _revealedMemoryIds.remove(_memoryRowRevealId(row));
              }),
              onCopy: _copyMemoryValue,
            ),
      ],
    );
  }

  Future<void> _showMemoryDialog({Map<String, dynamic>? row}) async {
    _qaMemoryCreateStage('ui_handler_entered');
    final data = await showMemoryEditorDialog(context, row: row);
    if (data == null) return;
    _qaMemoryCreateStage('validation_passed');
    await _persistMemoryDialog(row: row, data: data);
  }

  Future<void> _persistMemoryDialog({
    required Map<String, dynamic>? row,
    required Map<String, dynamic> data,
  }) async {
    final pinProvider = widget.pinProvider;
    if (pinProvider == null) {
      _showSnack('Unlock your vault to save memories');
      return;
    }
    try {
      if (_memoryV2Enabled) {
        _qaMemoryCreateStage('repository_available');
        final id = row?['memory_record_id']?.toString() ??
            'memory-${DateTime.now().microsecondsSinceEpoch}';
        final repository = MemoryV2Repository(
            baseUrl: widget.client.baseUrl, authToken: widget.authToken);
        _qaMemoryCreateStage('repository_create_entered');
        await repository.create(
            memoryId: id,
            memoryType: (data['memory_type'] ?? 'note').toString(),
            plaintext: MemoryV2Plaintext(
                value: (data['value'] ?? data['body'] ?? '').toString(),
                normalized: (data['title'] ?? '').toString(),
                tags: (data['tags'] as List? ?? const [])
                    .whereType<String>()
                    .toList()));
        if (!mounted) return;
        _showSnack(row == null ? 'Memory saved' : 'Memory updated');
        await _load();
        return;
      }
      final pin = await pinProvider();
      if (row == null) {
        await widget.client.createMemory(
          authToken: widget.authToken,
          vaultName: widget.vaultName,
          pin: pin,
          data: data,
        );
      } else {
        final id = int.tryParse('${row['id']}');
        if (id == null) throw Exception('Missing memory id');
        await widget.client.updateMemory(
          authToken: widget.authToken,
          vaultName: widget.vaultName,
          pin: pin,
          id: id,
          data: data,
        );
      }
      if (!mounted) return;
      _showSnack(row == null ? 'Memory saved' : 'Memory updated');
      await _load();
    } catch (e) {
      if (_qaDiagnostics) {
        print('MEMORY_CREATE_EXCEPTION_TYPE=${e.runtimeType}');
        print('MEMORY_CREATE_EXCEPTION_ORIGIN=memory_page_persist');
      }
      if (!mounted) return;
      _showSnack('Could not save memory');
    }
  }

  Future<void> _deleteMemory(Map<String, dynamic> row) async {
    final pinProvider = widget.pinProvider;
    if (pinProvider == null) {
      _showSnack('Unlock your vault to delete memories');
      return;
    }
    final title = ((row['title'] ?? row['memory_key']) as String?) ?? 'memory';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete memory?'),
        content: Text(title),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(ctx, true),
            icon: const Icon(Icons.delete_outline, size: 18),
            label: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      if (_memoryV2Enabled) {
        final id = row['memory_record_id']?.toString() ?? row['id']?.toString();
        if (id == null || id.isEmpty) throw Exception('Missing memory id');
        await MemoryV2Repository(
                baseUrl: widget.client.baseUrl, authToken: widget.authToken)
            .delete(id);
        if (!mounted) return;
        _showSnack('Memory deleted');
        await _load();
        return;
      }
      final id = int.tryParse('${row['id']}');
      if (id == null) throw Exception('Missing memory id');
      final pin = await pinProvider();
      await widget.client.deleteMemory(
        authToken: widget.authToken,
        vaultName: widget.vaultName,
        pin: pin,
        id: id,
      );
      if (!mounted) return;
      _showSnack('Memory deleted');
      await _load();
    } catch (e) {
      if (!mounted) return;
      _showSnack('Could not delete memory');
    }
  }

  Future<void> _copyMemoryValue(Map<String, dynamic> row) async {
    final id = _memoryRowRevealId(row);
    if (!_revealedMemoryIds.contains(id)) {
      _showSnack('Reveal this memory before copying it.');
      return;
    }
    final value = _memoryVisibleValue(row);
    if (value.trim().isEmpty) {
      _showSnack('Nothing to copy.');
      return;
    }
    await Clipboard.setData(ClipboardData(text: value));
    if (!mounted) return;
    _showSnack('Copied memory');
  }

  void _showSnack(String text) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  List<_YearBucket> _groupByYear(List<Map<String, dynamic>> items) {
    final buckets = <String, List<Map<String, dynamic>>>{};
    for (final m in items) {
      final y = _yearFor(m);
      buckets.putIfAbsent(y, () => []).add(m);
    }

    for (final list in buckets.values) {
      list.sort((a, b) {
        final ad = a['event_date'] as String? ?? '';
        final bd = b['event_date'] as String? ?? '';
        if (ad != bd) return bd.compareTo(ad);
        final au = a['updated_at'] as String? ?? '';
        final bu = b['updated_at'] as String? ?? '';
        return bu.compareTo(au);
      });
    }

    final keys = buckets.keys.toList()
      ..sort((a, b) {
        if (a == '~') return 1;
        if (b == '~') return -1;
        return b.compareTo(a);
      });
    return keys.map((k) => _YearBucket(year: k, items: buckets[k]!)).toList();
  }

  String _yearFor(Map<String, dynamic> m) {
    final ed = m['event_date'] as String?;
    if (ed != null && ed.length >= 4) {
      final y = ed.substring(0, 4);
      if (RegExp(r'^\d{4}$').hasMatch(y)) return y;
    }
    final ua = m['updated_at'] as String?;
    if (ua != null && ua.length >= 4) {
      final y = ua.substring(0, 4);
      if (RegExp(r'^\d{4}$').hasMatch(y)) return y;
    }
    return '~';
  }
}

class _YearBucket {
  final String year;
  final List<Map<String, dynamic>> items;
  _YearBucket({required this.year, required this.items});
}

class _FilterControls extends StatelessWidget {
  final Map<String, dynamic> counts;
  final int totalCount;
  final String? activeType;
  final TextEditingController searchCtrl;
  final ValueChanged<String?> onTypeChanged;
  final ValueChanged<String> onSearchChanged;

  const _FilterControls({
    required this.counts,
    required this.totalCount,
    required this.activeType,
    required this.searchCtrl,
    required this.onTypeChanged,
    required this.onSearchChanged,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    return VaultCard(
      padding: const EdgeInsets.all(VaultSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: searchCtrl,
            onChanged: onSearchChanged,
            style: VaultText.body,
            decoration: InputDecoration(
              hintText: AppLocalizations.of(context).memorySearchHint,
              prefixIcon: const Icon(Icons.search, size: 18),
              suffixIcon: searchCtrl.text.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.close, size: 16),
                      onPressed: () {
                        searchCtrl.clear();
                        onSearchChanged('');
                      },
                    ),
              isDense: true,
            ),
          ),
          const SizedBox(height: VaultSpacing.md),
          Wrap(
            spacing: VaultSpacing.sm,
            runSpacing: VaultSpacing.sm,
            children: [
              _FilterChip(
                label: l.commonAll,
                count: totalCount,
                icon: Icons.all_inclusive,
                accent: VaultColors.textPrimary,
                selected: activeType == null,
                onTap: () => onTypeChanged(null),
              ),
              for (final type in _memoryTypeOrder)
                if ((counts[type] as int? ?? 0) > 0)
                  _FilterChip(
                    label: _memoryTypeLabel(l, type),
                    count: counts[type] as int? ?? 0,
                    icon: _memoryTypeIcons[type] ?? Icons.circle_outlined,
                    accent: _memoryTypeAccents[type] ?? VaultColors.accent,
                    selected: activeType == type,
                    onTap: () => onTypeChanged(
                      activeType == type ? null : type,
                    ),
                  ),
            ],
          ),
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  final String label;
  final int count;
  final IconData icon;
  final Color accent;
  final bool selected;
  final VoidCallback onTap;

  const _FilterChip({
    required this.label,
    required this.count,
    required this.icon,
    required this.accent,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(VaultRadius.pill),
      child: AnimatedContainer(
        duration: VaultMotion.standard,
        curve: VaultMotion.curveStandard,
        padding: const EdgeInsets.symmetric(
          horizontal: VaultSpacing.md,
          vertical: VaultSpacing.sm,
        ),
        decoration: BoxDecoration(
          color: selected
              ? accent.withValues(alpha: 0.14)
              : VaultColors.surfaceMuted,
          borderRadius: BorderRadius.circular(VaultRadius.pill),
          border: Border.all(
            color: selected
                ? accent.withValues(alpha: 0.5)
                : VaultColors.borderSubtle,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon,
                size: 14, color: selected ? accent : VaultColors.textSecondary),
            const SizedBox(width: VaultSpacing.sm),
            Text(
              label,
              style: VaultText.caption.copyWith(
                color: selected
                    ? VaultColors.textPrimary
                    : VaultColors.textSecondary,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
            const SizedBox(width: VaultSpacing.sm),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(
                color: selected
                    ? accent.withValues(alpha: 0.20)
                    : VaultColors.surface,
                borderRadius: BorderRadius.circular(VaultRadius.sm),
              ),
              child: Text(
                '$count',
                style: VaultText.caption.copyWith(
                  color: selected ? accent : VaultColors.textTertiary,
                  fontWeight: FontWeight.w700,
                  fontSize: 11,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _YearGroup extends StatelessWidget {
  final String year;
  final List<Map<String, dynamic>> items;
  final bool isMobile;
  final void Function(String prompt)? onAskVaultAI;
  final void Function(Map<String, dynamic> row)? onEdit;
  final void Function(Map<String, dynamic> row)? onDelete;
  final bool Function(Map<String, dynamic> row) isRevealed;
  final void Function(Map<String, dynamic> row) onReveal;
  final void Function(Map<String, dynamic> row) onHide;
  final void Function(Map<String, dynamic> row) onCopy;

  const _YearGroup({
    required this.year,
    required this.items,
    required this.isMobile,
    required this.isRevealed,
    required this.onReveal,
    required this.onHide,
    required this.onCopy,
    this.onAskVaultAI,
    this.onEdit,
    this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return DashboardSection(
      title: year == '~' ? AppLocalizations.of(context).memoryUndated : year,
      icon: Icons.history,
      trailing: MetaPill(label: '${items.length}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < items.length; i++)
            Padding(
              padding: EdgeInsets.only(
                bottom: i == items.length - 1 ? 0 : VaultSpacing.sm,
              ),
              child: FadeSlideIn(
                delay: Duration(milliseconds: 25 * i),
                child: _MemoryRowCard(
                  row: items[i],
                  revealed: isRevealed(items[i]),
                  onAskVaultAI: onAskVaultAI,
                  onEdit: onEdit == null ? null : () => onEdit!(items[i]),
                  onDelete: onDelete == null ? null : () => onDelete!(items[i]),
                  onReveal: () => onReveal(items[i]),
                  onHide: () => onHide(items[i]),
                  onCopy: () => onCopy(items[i]),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _MemoryRowCard extends StatelessWidget {
  final Map<String, dynamic> row;
  final bool revealed;
  final void Function(String prompt)? onAskVaultAI;
  final VoidCallback? onEdit;
  final VoidCallback? onDelete;
  final VoidCallback onReveal;
  final VoidCallback onHide;
  final VoidCallback onCopy;

  const _MemoryRowCard({
    required this.row,
    required this.revealed,
    required this.onReveal,
    required this.onHide,
    required this.onCopy,
    this.onAskVaultAI,
    this.onEdit,
    this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    final l = AppLocalizations.of(context);
    final type =
        _normalizeMemoryType((row['memory_type'] as String?) ?? 'note');
    final key = ((row['title'] ?? row['memory_key']) as String?) ?? '';
    final visibleValue = _memoryVisibleValue(row);
    final eventDate = (row['event_date'] as String?) ?? '';
    final updatedAt = (row['updated_at'] as String?) ?? '';
    final tags = (row['tags'] is List)
        ? (row['tags'] as List).whereType<String>().toList()
        : const <String>[];
    final confidence = (row['confidence'] is num)
        ? (row['confidence'] as num).toDouble()
        : 1.0;
    final accent = _memoryTypeAccents[type] ?? VaultColors.accent;
    final typeLabel = _memoryTypeLabel(l, type);
    final icon = _memoryTypeIcons[type] ?? Icons.bookmark_border;

    return VaultCard(
      color: VaultColors.surfaceElevated,
      accentSide: BorderSide(color: accent, width: 3),
      padding: const EdgeInsets.all(VaultSpacing.lg),
      onTap: (onAskVaultAI == null || key.isEmpty)
          ? null
          : () => onAskVaultAI!(l.memoryAskAbout(key)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              IconBadge(icon: icon, color: accent, size: 40),
              const SizedBox(width: VaultSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      key.isNotEmpty ? key : l.memoryUnnamed,
                      style: VaultText.subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      revealed
                          ? (visibleValue.isEmpty
                              ? 'No saved value'
                              : 'Memory value revealed below')
                          : 'Memory value hidden',
                      style: VaultText.bodySm.copyWith(
                        color: VaultColors.textSecondary,
                      ),
                      maxLines: revealed ? 6 : 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: VaultSpacing.md),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  MetaPill(label: typeLabel, icon: icon, tint: accent),
                  const SizedBox(width: VaultSpacing.xs),
                  OutlinedButton.icon(
                    key: Key(
                      revealed
                          ? 'memory_row_hide_${_memoryRowRevealId(row)}'
                          : 'memory_row_reveal_${_memoryRowRevealId(row)}',
                    ),
                    onPressed: revealed ? onHide : onReveal,
                    icon: Icon(
                      revealed
                          ? Icons.visibility_off_outlined
                          : Icons.visibility_outlined,
                      size: 16,
                    ),
                    label: Text(revealed ? 'Hide' : 'Reveal'),
                  ),
                  if (revealed) ...[
                    const SizedBox(width: VaultSpacing.xs),
                    IconButton(
                      key: Key('memory_row_copy_${_memoryRowRevealId(row)}'),
                      tooltip: 'Copy',
                      onPressed: onCopy,
                      icon: const Icon(Icons.copy_outlined, size: 18),
                    ),
                  ],
                  if (onEdit != null) ...[
                    const SizedBox(width: VaultSpacing.xs),
                    IconButton(
                      tooltip: 'Edit',
                      onPressed: onEdit,
                      icon: const Icon(Icons.edit_outlined, size: 18),
                    ),
                  ],
                  if (onDelete != null)
                    Semantics(
                      identifier:
                          'qa_memory_v2_delete_${_memoryRowRevealId(row)}',
                      button: true,
                      child: IconButton(
                        tooltip: 'Delete',
                        onPressed: onDelete,
                        icon: const Icon(Icons.delete_outline, size: 18),
                      ),
                    ),
                ],
              ),
            ],
          ),
          if (revealed && visibleValue.isNotEmpty) ...[
            const SizedBox(height: VaultSpacing.sm),
            SelectableText(
              visibleValue,
              style: VaultText.bodySm.copyWith(
                color: VaultColors.textSecondary,
              ),
            ),
          ],
          const SizedBox(height: VaultSpacing.md),
          Wrap(
            spacing: VaultSpacing.sm,
            runSpacing: VaultSpacing.xs + 2,
            children: [
              if (eventDate.isNotEmpty)
                MetaPill(label: eventDate, icon: Icons.event_outlined),
              if (eventDate.isEmpty && updatedAt.length >= 10)
                MetaPill(
                  label: 'saved ${updatedAt.substring(0, 10)}',
                  icon: Icons.update,
                ),
              if (confidence < 0.95)
                MetaPill(
                  label: 'conf ${(confidence * 100).round()}%',
                  icon: Icons.percent,
                  dim: true,
                ),
              for (final tag in tags.take(4))
                MetaPill(label: tag, icon: Icons.sell_outlined, dim: true),
            ],
          ),
        ],
      ),
    );
  }
}
