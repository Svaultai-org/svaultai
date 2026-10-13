import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/saved_file_rename.dart';

class SavedFileRenameDialog extends StatefulWidget {
  final String initialName;
  final SavedFileRenameController controller;
  final Future<SavedFileRenameOutcome> Function(String name) onSave;

  const SavedFileRenameDialog({
    super.key,
    required this.initialName,
    required this.controller,
    required this.onSave,
  });

  @override
  State<SavedFileRenameDialog> createState() => _SavedFileRenameDialogState();
}

class _SavedFileRenameDialogState extends State<SavedFileRenameDialog> {
  late final TextEditingController _name;
  bool _saving = false;
  bool _finished = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.initialName);
  }

  @override
  void dispose() {
    widget.controller.cancel();
    _name.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving) return;
    final error = savedFileNameValidationError(_name.text);
    if (error != null) {
      setState(() => _error = error);
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final outcome = await widget.onSave(_name.text);
      if (!mounted) return;
      if (outcome == SavedFileRenameOutcome.saved) {
        _finished = true;
        Navigator.of(context).pop(true);
      } else {
        setState(() => _error = outcome == SavedFileRenameOutcome.stale
            ? 'Your vault session changed. Nothing was applied to this screen.'
            : 'This file is already being renamed. Please try again.');
      }
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Could not rename the file. Your entered name '
            'is still here; please try again.');
      }
    } finally {
      if (mounted && !_finished) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
        canPop: !_saving,
        child: AlertDialog(
          title: const Text('Rename file'),
          content: TextField(
            key: const Key('saved_file_rename_name'),
            controller: _name,
            enabled: !_saving,
            autofocus: true,
            autocorrect: false,
            maxLength: 120,
            maxLengthEnforcement: MaxLengthEnforcement.none,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _save(),
            decoration: InputDecoration(
              labelText: 'File name',
              errorText: _error,
              helperText: 'Only the name changes. File contents stay the same.',
            ),
          ),
          actions: [
            TextButton(
              key: const Key('saved_file_rename_cancel'),
              onPressed: _saving
                  ? null
                  : () {
                      widget.controller.cancel();
                      Navigator.of(context).pop(false);
                    },
              child: const Text('Cancel'),
            ),
            FilledButton(
              key: const Key('saved_file_rename_save'),
              onPressed: _saving ? null : _save,
              child: Text(_saving ? 'Saving…' : 'Save'),
            ),
          ],
        ),
      );
}
