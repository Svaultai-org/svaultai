import 'package:flutter_test/flutter_test.dart';


String resolveStatusForTest({
  String? widgetStatus,
  String? argsStatus,
}) {
  return widgetStatus ?? (argsStatus ?? 'pending');
}

String titleForStatus(String status) {
  switch (status) {
    case 'revoked':
      return 'This device was revoked';
    case 'missing_device_id':
      return 'Your app is out of date';
    case 'missing':
      return 'This device is not registered';
    case 'pending':
      return 'This device is not trusted yet';
    default:
      return 'This device is not trusted yet';
  }
}

bool shouldPoll(String status) => status == 'pending';
bool shouldOfferRegister(String status) => status == 'missing';
bool shouldOfferSelfApproval(String status) => status == 'pending';
bool isTerminal(String status) =>
    status == 'revoked' || status == 'missing_device_id';

void main() {
  group('DevicePendingPage status resolution', () {
    test('uses widget.status when provided', () {
      expect(
        resolveStatusForTest(widgetStatus: 'revoked', argsStatus: 'pending'),
        equals('revoked'),
      );
    });

    test('falls back to route args when widget.status is null', () {
      
      
      expect(
        resolveStatusForTest(widgetStatus: null, argsStatus: 'pending'),
        equals('pending'),
      );
    });

    test('defaults to "pending" when both inputs are null', () {
      expect(
        resolveStatusForTest(widgetStatus: null, argsStatus: null),
        equals('pending'),
      );
    });

    test('reads literal "missing" through unchanged', () {
      expect(
        resolveStatusForTest(widgetStatus: null, argsStatus: 'missing'),
        equals('missing'),
      );
    });
  });

  group('DevicePendingPage titleForStatus', () {
    test('"pending" -> "This device is not trusted yet"', () {
      expect(titleForStatus('pending'),
          equals('This device is not trusted yet'));
    });
    test('"missing" -> "This device is not registered"', () {
      expect(titleForStatus('missing'),
          equals('This device is not registered'));
    });
    test('"revoked" -> "This device was revoked"', () {
      expect(titleForStatus('revoked'), equals('This device was revoked'));
    });
    test('"missing_device_id" -> "Your app is out of date"', () {
      expect(titleForStatus('missing_device_id'),
          equals('Your app is out of date'));
    });
    test('unknown statuses fall back to pending title (never empty)', () {
      
      
      expect(titleForStatus('something-new'), isNotEmpty);
      expect(titleForStatus(''), isNotEmpty);
    });
  });

  group('DevicePendingPage action wiring', () {
    test('only pending shows the Check Again poll', () {
      expect(shouldPoll('pending'), isTrue);
      expect(shouldPoll('missing'), isFalse);
      expect(shouldPoll('revoked'), isFalse);
      expect(shouldPoll('missing_device_id'), isFalse);
    });

    test('only "missing" shows the Register This Device action', () {
      expect(shouldOfferRegister('missing'), isTrue);
      expect(shouldOfferRegister('pending'), isFalse);
      expect(shouldOfferRegister('revoked'), isFalse);
    });

    test('only pending shows self-approval section', () {
      expect(shouldOfferSelfApproval('pending'), isTrue);
      
      
      expect(shouldOfferSelfApproval('missing'), isFalse);
      expect(shouldOfferSelfApproval('revoked'), isFalse);
    });

    test('revoked + missing_device_id are terminal (no poll)', () {
      expect(isTerminal('revoked'), isTrue);
      expect(isTerminal('missing_device_id'), isTrue);
      expect(isTerminal('pending'), isFalse);
      expect(isTerminal('missing'), isFalse);
    });
  });
}
