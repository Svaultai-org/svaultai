
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:vault_ai_frontend/l10n/app_localizations.dart';
import 'package:vault_ai_frontend/services/vault_chat_router.dart' as vcr;
import 'package:vault_ai_frontend/ui/vault_chat_cards.dart';

import '_helpers/responsive_harness.dart';




Map<String, dynamic> _detailEnv({
  String query = 'american first credit union',
  String service = 'American First Credit Union',
  String title = 'American First Credit Union',
  String username = 'ada.lovelace@example.com',
  String password = 'Correct-Horse-Battery-Staple-2026!',
  String domain = 'americanfirst.com',
  String website = 'https://americanfirst.com',
  String notes = '',
  List<Map<String, String>>? fields,
  String? pendingAction,
}) {
  return <String, dynamic>{
    'intent': 'vault_login_search',
    'card': {
      'schema':   'vault_chat_router_v1',
      'cardType': 'vault_login_card',
      'view':     'detail',
      'query':    query,
      'data': {
        'schema':    'vault_login_data_v1',
        'available': true,
        'view':      'detail',
        'query':     query,
        'login': {
          'id':       'login-1',
          'title':    title,
          'service':  service,
          'username': username,
          'password': password,
          'domain':   domain,
          'website':  website,
          'notes':    notes,
          if (fields != null) 'fields': fields,
        },
        if (pendingAction != null) 'pending_action': pendingAction,
      },
    },
  };
}


Map<String, dynamic> _chooserEnv() {
  return <String, dynamic>{
    'intent': 'vault_login_search',
    'card': {
      'schema':   'vault_chat_router_v1',
      'cardType': 'vault_login_card',
      'view':     'chooser',
      'query':    'bank',
      'data': {
        'schema':    'vault_login_data_v1',
        'available': true,
        'view':      'chooser',
        'query':     'bank',
        'logins': [
          {
            'id': 'l-1', 'title': 'American First Bank',
            'service': 'American First Bank',
            'username_masked': 'a***@example.com',
            'domain': 'americanfirst.com',
          },
          {
            'id': 'l-2', 'title': 'Bank of Nowhere',
            'service': 'Bank of Nowhere',
            'username_masked': 'b***@example.com',
            'domain': 'nowhere.example',
          },
        ],
      },
    },
  };
}


Map<String, dynamic> _notFoundEnv() {
  return <String, dynamic>{
    'intent': 'vault_login_search',
    'card': {
      'schema':   'vault_chat_router_v1',
      'cardType': 'vault_login_card',
      'view':     'not_found',
      'query':    'nonexistent bank',
      'data': {
        'schema':    'vault_login_data_v1',
        'available': true,
        'view':      'not_found',
        'query':     'nonexistent bank',
        'count':     0,
      },
    },
  };
}


Map<String, dynamic> _listEnv() {
  return <String, dynamic>{
    'intent': 'vault_login_list',
    'card': {
      'schema':   'vault_chat_router_v1',
      'cardType': 'vault_login_card',
      'view':     'list',
      'data': {
        'schema':    'vault_login_data_v1',
        'available': true,
        'view':      'list',
        'logins': [
          {
            'id':'x','title':'Netflix','service':'Netflix',
            'username_masked':'a***@example.com',
            'has_username':true,
            'domain':'netflix.com',
          },
        ],
        'count': 1,
      },
    },
  };
}


Widget _wrap(Widget child) => MaterialApp(
      theme: ThemeData.dark(useMaterial3: true),
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      locale: const Locale('en'),
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );


/// find.text does not match SelectableText / RichText inline spans. This
/// finder scans SelectableText.data + Text.data.
Finder _findVisibleText(String needle) => find.byWidgetPredicate((w) {
      if (w is Text) {
        return (w.data ?? '') == needle;
      }
      if (w is SelectableText) {
        return (w.data ?? '') == needle;
      }
      return false;
    });




void main() {

  group('LoginDetailCard rendering (product decision 2026-07-11)', () {
    testWidgets(
      '(1) shows real username + password + website + service '
      'when view=detail', (t) async {
      final env = _detailEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();


      expect(
        find.byKey(const Key(
            'vault_chat_card_login_detail_title')),
        findsOneWidget,
      );


      final selectables = find.byType(SelectableText).evaluate()
          .map((e) => e.widget as SelectableText)
          .map((s) => s.data ?? '').toList();
      expect(
        selectables.contains('ada.lovelace@example.com'), isTrue,
        reason:
            'username plaintext must be present: got=${selectables.join("|")}',
      );

      expect(
        selectables.any((s) => s.contains('Correct-Horse')),
        isTrue,
        reason:
            'password plaintext must be present: got=${selectables.join("|")}',
      );
      expect(
        selectables.any((s) => s.contains('americanfirst')),
        isTrue,
        reason: 'website must be present: got=${selectables.join("|")}',
      );
    });

    testWidgets('(2) card contains no masked dots and no '
        '"Reveal requires unlock" copy', (t) async {
      final env = _detailEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();

      expect(find.text('•••••••••'), findsNothing);
      expect(find.textContaining('Reveal requires'), findsNothing);
      expect(find.textContaining('Password hidden'), findsNothing);
    });

    testWidgets('renders arbitrary custom fields from ordered login.fields',
        (t) async {
      final env = _detailEnv(
        service: 'Tinder',
        title: 'Tinder',
        username: 'beraves',
        password: 'bunty1234567',
        domain: '',
        website: '',
        fields: const [
          {'label': 'Username', 'value': 'beraves'},
          {'label': 'Password', 'value': 'bunty1234567'},
          {'label': 'pin', 'value': '748291'},
          {'label': 'Recovery Code', 'value': 'blue-hill-42'},
        ],
      );
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();

      expect(_findVisibleText('Username'), findsOneWidget);
      expect(_findVisibleText('Password'), findsOneWidget);
      expect(_findVisibleText('pin'), findsOneWidget);
      expect(_findVisibleText('Recovery Code'), findsOneWidget);
      expect(_findVisibleText('beraves'), findsOneWidget);
      expect(_findVisibleText('bunty1234567'), findsOneWidget);
      expect(_findVisibleText('748291'), findsOneWidget);
      expect(_findVisibleText('blue-hill-42'), findsOneWidget);
    });

    testWidgets('(3) generic list view does NOT expose every '
        'password — only masked usernames', (t) async {
      final env = _listEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();


      expect(find.textContaining('a***@example.com'), findsOneWidget);


      expect(find.textContaining('Correct-Horse'), findsNothing);
    });

    testWidgets('(4) multiple matches renders chooser first '
        '(no plaintext password on any option)', (t) async {
      final env = _chooserEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();

      expect(find.byKey(const Key(
          'vault_chat_card_login_chooser_option_l-1')), findsOneWidget);
      expect(find.byKey(const Key(
          'vault_chat_card_login_chooser_option_l-2')), findsOneWidget);


      expect(find.textContaining('password'), findsNothing);
    });

    testWidgets('(5) chooser select fires onLoginChooseCandidate '
        'with the chosen title', (t) async {
      final env = _chooserEnv();
      String? chosenQuery;
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
        onLoginChooseCandidate: (q) => chosenQuery = q,
      )));
      await t.pumpAndSettle();

      await t.tap(find.byKey(const Key(
          'vault_chat_card_login_chooser_option_l-1')));
      await t.pump();
      expect(chosenQuery, 'American First Bank');
    });

    testWidgets('(6) not_found renders friendly copy with query',
        (t) async {
      final env = _notFoundEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();

      expect(find.textContaining('No login found'), findsOneWidget);
      expect(find.textContaining('nonexistent bank'), findsOneWidget);
    });
  });


  group('LoginDetailCard actions', () {
    testWidgets('(7) copy-username button copies the plaintext '
        'to clipboard', (t) async {
      String? copied;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') {
          copied = (call.arguments as Map)['text'] as String;
        }
        return null;
      });

      final env = _detailEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();

      await t.tap(find.byKey(
          const Key('vault_chat_card_login_detail_username_copy')));
      await t.pump();
      expect(copied, 'ada.lovelace@example.com');
    });

    testWidgets('(8) copy-password button copies the plaintext '
        'to clipboard', (t) async {
      String? copied;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') {
          copied = (call.arguments as Map)['text'] as String;
        }
        return null;
      });

      final env = _detailEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();

      final btn = find.byKey(
          const Key('vault_chat_card_login_detail_password_copy'));
      await t.ensureVisible(btn);
      await t.pumpAndSettle();
      await t.tap(btn);
      await t.pumpAndSettle();
      expect(copied, 'Correct-Horse-Battery-Staple-2026!');
    });

    testWidgets('(9) edit button calls onLoginEdit with service',
        (t) async {
      String? editedService;
      final env = _detailEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
        onLoginEdit: (s) => editedService = s,
      )));
      await t.pumpAndSettle();

      await t.tap(find.byKey(
          const Key('vault_chat_card_login_detail_edit')));
      await t.pump();
      expect(editedService, 'American First Credit Union');
    });

    testWidgets('(10) delete button calls onLoginDelete with service',
        (t) async {
      String? deletedService;
      final env = _detailEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
        onLoginDelete: (s) => deletedService = s,
      )));
      await t.pumpAndSettle();

      await t.tap(find.byKey(
          const Key('vault_chat_card_login_detail_delete')));
      await t.pump();
      expect(deletedService, 'American First Credit Union');
    });

    testWidgets('(11) open-website button calls onLoginOpenWebsite '
        'with service + url', (t) async {
      String? openedService;
      String? openedUrl;
      final env = _detailEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
        onLoginOpenWebsite: (s, u) {
          openedService = s;
          openedUrl = u;
        },
      )));
      await t.pumpAndSettle();

      await t.tap(find.byKey(
          const Key('vault_chat_card_login_detail_website_open')));
      await t.pump();
      expect(openedService, 'American First Credit Union');
      expect(openedUrl, 'https://americanfirst.com');
    });
  });


  group('LoginDetailCard pending_action (pronoun follow-up)', () {
    testWidgets(
        '(12) pending_action="edit" auto-dispatches onLoginEdit '
        'on mount', (t) async {
      String? edited;
      final env = _detailEnv(pendingAction: 'edit');
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
        onLoginEdit: (s) => edited = s,
      )));
      await t.pumpAndSettle();
      expect(edited, 'American First Credit Union');
    });

    testWidgets(
        '(13) pending_action="delete" auto-dispatches onLoginDelete',
        (t) async {
      String? deleted;
      final env = _detailEnv(pendingAction: 'delete');
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
        onLoginDelete: (s) => deleted = s,
      )));
      await t.pumpAndSettle();
      expect(deleted, 'American First Credit Union');
    });

    testWidgets(
        '(14) pending_action="copy_password" auto-copies to clipboard',
        (t) async {
      String? copied;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        if (call.method == 'Clipboard.setData') {
          copied = (call.arguments as Map)['text'] as String;
        }
        return null;
      });

      final env = _detailEnv(pendingAction: 'copy_password');
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));

      await t.pumpAndSettle();
      await t.pump(const Duration(milliseconds: 100));
      expect(copied, 'Correct-Horse-Battery-Staple-2026!');
    });
  });


  group('LoginDetailCard responsive layout @ 320/390/430', () {
    for (final d in const [
      DeviceProfiles.iphoneSE,
      DeviceProfiles.iphone12,
      DeviceProfiles.iphone14ProMax,
    ]) {
      testWidgets(
          'renders without overflow @ ${d.name} '
          '(${d.width.toInt()}x${d.height.toInt()})',
          (t) async {
        final env = _detailEnv(
          username: 'ada.byron.lovelace.a.really.long.username@example.com',
          password: 'A-very-long-password-with-many-special-chars-!@#\$%^&*()_+',
          notes: 'A note that spans multiple lines. '
                 'Includes several sentences. '
                 'Meant to stress-test the layout on narrow phones.',
        );
        await pumpAtDevice(
          t,
          VaultChatCardView(
            response: vcr.VaultChatResponse.fromJson(env),
          ),
          device: d,
        );
        expectNoOverflow(t, context: d.name);
      });
    }
  });


  group('LoginDetailCard hardening', () {
    testWidgets('(15) no raw JSON blob rendered anywhere', (t) async {
      final env = _detailEnv();
      await t.pumpWidget(_wrap(VaultChatCardView(
        response: vcr.VaultChatResponse.fromJson(env),
      )));
      await t.pumpAndSettle();


      final texts = find.byWidgetPredicate((w) {
        if (w is Text) {
          final s = w.data ?? '';
          return s.startsWith('{') && s.endsWith('}');
        }
        if (w is SelectableText) {
          final s = w.data ?? '';
          return s.startsWith('{') && s.endsWith('}');
        }
        return false;
      });
      expect(texts, findsNothing);
    });
  });
}
