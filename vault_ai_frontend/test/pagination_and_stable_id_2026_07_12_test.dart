import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart' as vcr;
import 'package:vault_ai_frontend/ui/chat/chat_cards.dart';
import 'package:vault_ai_frontend/ui/chat/chat_models.dart';
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';


Widget _wrap(Widget child) => MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );


ChatMessage _fileListMsg({
  required int total,
  required List<Map<String, dynamic>> files,
  int? offset,
  int? nextOffset,
  bool? hasMore,
}) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kVaultFileList,
    payload: {
      'title':       'All $total files in your vault',
      'count':       files.length,
      'total_count': total,
      'offset':      offset ?? 0,
      'page_size':   25,
      'next_offset': nextOffset ?? files.length,
      'has_more':    hasMore ?? (files.length < total),
      'files':       files,
    },
  );
}


ChatMessage _fileMsg({
  String id = 'file-1',
  String name = 'photo.jpg',
  String mime = 'image/jpeg',
  int? sizeBytes,
}) {
  return ChatMessage(
    'assistant',
    '',
    kind: ChatMessage.kVaultFile,
    fileId: id,
    fileName: name,
    mimeType: mime,
    payload: {
      if (sizeBytes != null) 'size_bytes': sizeBytes,
    },
  );
}


void main() {

  group('Bug: Show more is a real action, not just text', () {
    testWidgets('renders a tappable Show more button when has_more=true',
        (t) async {
      var showMoreTaps = 0;
      final msg = _fileListMsg(
        total: 90,
        files: List.generate(25, (i) => {
          'file_id': 'id$i',
          'file_name': 'file$i.pdf',
          'mime_type': 'application/pdf',
        }),
      );

      await t.pumpWidget(_wrap(VaultFileListCard(
        msg: msg,
        onOpen: (_) {},
        onDownload: (_) {},
        onShowMore: () => showMoreTaps++,
        isShowMoreInFlight: false,
      )));
      await t.pumpAndSettle();

      final btn = find.byKey(
        const Key('vault_file_list_show_more_btn'),
      );
      expect(btn, findsOneWidget,
          reason: 'Show more must be a real button');
      await t.tap(btn);
      expect(showMoreTaps, 1);
    });

    testWidgets('button disabled + spinner while isShowMoreInFlight',
        (t) async {
      final msg = _fileListMsg(
        total: 90,
        files: List.generate(25, (i) => {
          'file_id': 'id$i',
          'file_name': 'file$i.pdf',
          'mime_type': 'application/pdf',
        }),
      );

      await t.pumpWidget(_wrap(VaultFileListCard(
        msg: msg,
        onOpen: (_) {},
        onDownload: (_) {},
        onShowMore: () {},
        isShowMoreInFlight: true,
      )));
      // Don't pumpAndSettle: the spinner spins forever.
      await t.pump();

      final btn = find.byKey(
        const Key('vault_file_list_show_more_btn'),
      );
      expect(t.widget<OutlinedButton>(btn).onPressed, isNull,
          reason: 'button must be disabled while a Show more '
              'request is in flight');
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Loading…'), findsOneWidget);
    });

    testWidgets('no button when has_more=false',
        (t) async {
      final msg = _fileListMsg(
        total: 10,
        files: List.generate(10, (i) => {
          'file_id': 'id$i',
          'file_name': 'file$i.pdf',
          'mime_type': 'application/pdf',
        }),
        hasMore: false,
      );
      await t.pumpWidget(_wrap(VaultFileListCard(
        msg: msg,
        onOpen: (_) {},
        onDownload: (_) {},
        onShowMore: () {},
      )));
      await t.pumpAndSettle();
      expect(
        find.byKey(const Key('vault_file_list_show_more_btn')),
        findsNothing,
      );
    });

    testWidgets('rapid Show more taps are collapsed by isShowMoreInFlight',
        (t) async {
      var taps = 0;
      bool inFlight = false;
      Future<void> pumpCard() async {
        await t.pumpWidget(_wrap(VaultFileListCard(
          msg: _fileListMsg(
            total: 100,
            files: List.generate(25, (i) => {
              'file_id': 'id$i',
              'file_name': 'file$i.pdf',
              'mime_type': 'application/pdf',
            }),
          ),
          onOpen: (_) {},
          onDownload: (_) {},
          onShowMore: () {
            if (inFlight) return;
            inFlight = true;
            taps++;
          },
          isShowMoreInFlight: inFlight,
        )));
      }
      await pumpCard();
      for (var i = 0; i < 10; i++) {
        await t.tap(
          find.byKey(const Key('vault_file_list_show_more_btn')),
          warnIfMissed: false,
        );
        await pumpCard();
      }
      expect(taps, 1,
          reason: 'rapid taps must produce exactly one request');
    });
  });


  group('Bug: spinner is visible BEFORE the fetch completes', () {
    testWidgets('spinner appears synchronously with the parent '
        'flipping isViewInFlight — not only after the fetch resolves',
        (t) async {
      // Model the exact production sequence:
      //   1. Parent widget receives onOpen (tap).
      //   2. Parent SYNCHRONOUSLY calls AppState.beginFileView which
      //      notifies listeners → the card rebuilds.
      //   3. Parent kicks off the async fetch (not modelled — we
      //      stop the sequence at step 2 to prove the spinner is
      //      visible at that point).
      // If the spinner only appeared AFTER the fetch resolved, the
      // user would tap 10 times during a multi-second decrypt.
      final host = _InFlightHost();

      await t.pumpWidget(_wrap(_TestParent(host: host)));
      await t.pump();

      // Before any tap, no spinner.
      expect(find.text('Opening…'), findsNothing);

      // Tap. The test's onTap SYNCHRONOUSLY flips isViewInFlight to
      // true — the same shape as AppState.beginFileView followed by
      // notifyListeners.
      await t.tap(find.byKey(const Key('vault_file_card_view_btn')));
      await t.pump();

      // Assertion: the spinner is present on this frame, i.e. after
      // the synchronous state flip but BEFORE any long fetch has
      // resolved. host.completeFetch has NOT been called.
      expect(find.text('Opening…'), findsOneWidget,
          reason: 'spinner must be visible from the frame after '
              'the tap — NOT only after the fetch resolves');
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(host.fetchCompleted, isFalse,
          reason: 'the mock fetch is still pending — proving the '
              'spinner appeared BEFORE completion');

      // Resolve the fetch and confirm the spinner tears down.
      host.completeFetch();
      await t.pump();
      expect(find.text('Opening…'), findsNothing);
    });
  });


  group('Bug: login row uses stable id, not title', () {
    testWidgets('two logins with the same title still get distinct '
        'row keys and pass distinct ids to onLoginSelectById',
        (t) async {
      String? tappedId;
      String? tappedTitle;

      final response = vcr.VaultChatResponse.fromJson({
        'intent': 'vault_login_list',
        'card': {
          'schema':   'vault_chat_router_v1',
          'cardType': 'vault_login_card',
          'view':     'list',
          'data': {
            'schema':    'vault_login_data_v1',
            'available': true,
            'view':      'list',
            'count':     2,
            'logins': [
              {
                'id':               'login-A',
                'title':            'Gmail',
                'username_masked':  'a***@example.com',
                'has_username':     true,
              },
              {
                'id':               'login-B',
                'title':            'Gmail',
                'username_masked':  'b***@example.com',
                'has_username':     true,
              },
            ],
          },
        },
      });

      await t.pumpWidget(_wrap(VaultChatCardView(
        response: response,
        onLoginSelectById: (id, title) {
          tappedId = id;
          tappedTitle = title;
        },
      )));
      await t.pumpAndSettle();

      // Two distinct row keys — driven by the row's stable id.
      expect(find.byKey(const Key('login_row_id_login-A')),
          findsOneWidget);
      expect(find.byKey(const Key('login_row_id_login-B')),
          findsOneWidget);

      await t.tap(find.byKey(const Key('login_row_id_login-B')));
      await t.pumpAndSettle();

      expect(tappedId, 'login-B',
          reason: 'tapping the second row must fire onSelect with '
              'the SECOND row\'s id, not the first row\'s');
      expect(tappedTitle, 'Gmail');
    });
  });


  group('Bug: file rows carry stable file_id for follow-ups', () {
    testWidgets('two files with the same filename produce two rows '
        'with distinct row keys and distinct fileMsgs',
        (t) async {
      String? viewedId;
      String? downloadedId;

      final msg = ChatMessage(
        'assistant',
        '',
        kind: ChatMessage.kVaultFileList,
        payload: {
          'title': 'All 2 files',
          'files': [
            {
              'file_id': 'file-A',
              'file_name': 'videos',
              'mime_type': 'video/mp4',
              'size_bytes': 100,
            },
            {
              'file_id': 'file-B',
              'file_name': 'videos',
              'mime_type': 'video/mp4',
              'size_bytes': 200,
            },
          ],
        },
      );

      await t.pumpWidget(_wrap(VaultFileListCard(
        msg: msg,
        onOpen: (fm) => viewedId = fm.fileId,
        onDownload: (fm) => downloadedId = fm.fileId,
      )));
      await t.pumpAndSettle();

      expect(find.byKey(const Key('vault_file_list_row_file-A')),
          findsOneWidget);
      expect(find.byKey(const Key('vault_file_list_row_file-B')),
          findsOneWidget);

      await t.tap(
        find.byKey(const Key('vault_file_list_row_view_file-B')),
      );
      expect(viewedId, 'file-B',
          reason: 'View on row 2 must dispatch fileId=file-B '
              'regardless of filename collision');

      await t.tap(
        find.byKey(const Key('vault_file_list_row_download_file-A')),
      );
      expect(downloadedId, 'file-A',
          reason: 'Download on row 1 must target file-A, not fall '
              'through to a first-match by filename');
    });
  });
}


/// Test parent that mirrors the shape of the production wiring:
/// AppState.beginFileView() flips a bool + calls notifyListeners();
/// the card watches the parent and rebuilds with isViewInFlight=true.
/// After completeFetch(), the parent flips it back.
class _InFlightHost extends ChangeNotifier {
  bool _inFlight = false;
  bool _completed = false;

  bool get inFlight => _inFlight;
  bool get fetchCompleted => _completed;

  void beginFetch() {
    if (_inFlight) return;
    _inFlight = true;
    notifyListeners();
  }

  void completeFetch() {
    _completed = true;
    _inFlight = false;
    notifyListeners();
  }
}

class _TestParent extends StatefulWidget {
  final _InFlightHost host;
  const _TestParent({required this.host});
  @override
  State<_TestParent> createState() => _TestParentState();
}

class _TestParentState extends State<_TestParent> {
  @override
  void initState() {
    super.initState();
    widget.host.addListener(_onChanged);
  }

  @override
  void dispose() {
    widget.host.removeListener(_onChanged);
    super.dispose();
  }

  void _onChanged() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    return VaultFileCard(
      msg: _fileMsg(),
      onOpen: widget.host.beginFetch,
      onDownload: () {},
      isViewInFlight: widget.host.inFlight,
    );
  }
}
