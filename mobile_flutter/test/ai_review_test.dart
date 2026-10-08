import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import '../lib/ai_review.dart';
import 'ai_review_fixtures.dart';

void main() {
  group('Safe stored-analysis projection', () {
    for (final mode in ['rules-only', 'rules-only: disabled',
      'rules-only: configuration_missing', 'rules-only: incomplete_configuration',
      'rules-only: adapter_error', 'rules-only: seeded-demo']) {
      test('$mode is rules-only, never a model score', () {
        final result = AiReview.fromOrder(reviewFixture(mode: mode,
          fields: {'report_score': 5, 'confidence': 0.99,
            'master_confirmation_required': false, 'needs_master_attention': false}));
        expect(result.available, isTrue);
        expect(result.mode, ReviewMode.rulesOnly);
        expect(result.verdict, ReviewVerdict.comments);
        expect(result.reportScore, isNull);
        expect(result.confidence, isNull);
        expect(result.masterRequirement, MasterReviewRequirement.required);
      });
    }

    test('matching server model fields expose independent report data', () {
      final result = AiReview.fromOrder(modelFixture());
      expect(result.mode, ReviewMode.modelReported);
      expect(result.verdict, ReviewVerdict.accepted);
      expect(result.reportScore, 2);
      expect(result.confidence, 0.85);
      expect(result.scoreReason, 'Synthetic model reason for report content only.');
      expect(result.issues, isEmpty);
      expect(result.masterRequirement, MasterReviewRequirement.notRequested);
    });

    test('nullable score and confidence do not fabricate a score', () {
      final result = AiReview.fromOrder(modelFixture(fields: {
        'report_score': null, 'score_reason': null, 'confidence': null,
        'master_confirmation_required': null,
      }));
      expect(result.mode, ReviewMode.modelReported);
      expect(result.reportScore, isNull);
      expect(result.scoreReason, isNull);
      expect(result.confidence, isNull);
      expect(result.masterRequirement, MasterReviewRequirement.unspecified);
    });

    for (final outer in [null, 'rules-only', 'llm:different-model', 'future-mode']) {
      test('missing/conflicting outer mode $outer never confirms model', () {
        final result = AiReview.fromOrder(modelFixture(orderFields: {'ai_mode': outer}));
        expect(result.mode, ReviewMode.unknown);
        expect(result.reportScore, isNull);
        expect(result.masterRequirement, MasterReviewRequirement.required);
      });
    }

    test('rules-only seeded general outer label is compatible', () {
      expect(AiReview.fromOrder(reviewFixture(mode: 'rules-only: seeded-demo',
        orderFields: {'ai_mode': 'rules-only'})).mode, ReviewMode.rulesOnly);
    });

    test('outer mode alone does not claim a stored model analysis', () {
      final result = AiReview.fromOrder({'ai_mode': 'llm:example', 'ai_result': null});
      expect(result.available, isFalse);
      expect(result.mode, ReviewMode.unknown);
    });

    for (final value in [null, '', '  ']) {
      test('absent result $value stays absent', () {
        final result = AiReview.fromOrder({'ai_result': value});
        expect(result.available, isFalse);
        expect(result.unreadable, isFalse);
      });
    }
    for (final value in ['{broken', 'null', '[]', '42', 'true', 17, {'mode': 'llm:x'}]) {
      test('malformed/wrong top-level $value is unreadable', () {
        final result = AiReview.fromOrder({'ai_result': value, 'ai_mode': 'llm:x'});
        expect(result.available, isFalse);
        expect(result.unreadable, isTrue);
        expect(result.mode, ReviewMode.unknown);
      });
    }

    test('oversized JSON is rejected before decoding', () {
      final result = AiReview.fromOrder({'ai_result': ' ' * 128001 + '{}'});
      expect(result.unreadable, isTrue);
    });

    test('unknown and malformed fields are not stringified', () {
      final result = AiReview.fromOrder(reviewFixture(mode: 'future-mode', fields: {
        'summary': {'password': 'hidden-secret'},
        'verdict': 'future-verdict',
        'issues': ['Readable concern', {'api_key': 'hidden-secret'}, null, 4],
        'master_confirmation_required': 'false',
        'needs_master_attention': 0,
        'photo_check': ['hidden-secret'],
        'materials_check': 'hidden-secret',
      }));
      expect(result.available, isTrue);
      expect(result.incomplete, isTrue);
      expect(result.mode, ReviewMode.unknown);
      expect(result.verdict, ReviewVerdict.unknown);
      expect(result.summary, isNull);
      expect(result.issues, ['Readable concern']);
      expect(result.photoCheck, isNull);
      expect(result.materialsCheck, isNull);
      expect(result.masterRequirement, MasterReviewRequirement.required);
    });

    test('model label alone cannot rescue malformed result content', () {
      final result = AiReview.fromOrder(modelFixture(fields: {'issues': 'not-a-list'}));
      expect(result.mode, ReviewMode.unknown);
      expect(result.incomplete, isTrue);
      expect(result.reportScore, isNull);
    });

    test('JSON-shaped text is hidden and common credentials are masked', () {
      final result = AiReview.fromOrder(reviewFixture(fields: {
        'summary': '{"secret":"hidden-secret"}',
        'issues': [
          'Readable issue with token=private-test-value',
          'Header Bearer sample-private-token',
          'Key sk-synthetic0123456789',
          '["hidden-json"]',
          'Diagnostic: {"api_key":"hidden-test-secret"}',
          'Password="two word secret"',
        ],
      }));
      expect(result.summary, isNull);
      expect(result.issues.length, 4);
      expect(result.issues.join(' '), isNot(contains('private-test-value')));
      expect(result.issues.join(' '), isNot(contains('sample-private-token')));
      expect(result.issues.join(' '), isNot(contains('synthetic0123456789')));
      expect(result.issues.join(' '), isNot(contains('hidden-json')));
      expect(result.issues.join(' '), isNot(contains('hidden-test-secret')));
      expect(result.issues.join(' '), isNot(contains('two word secret')));
    });

    test('text and issue counts are bounded', () {
      final result = AiReview.fromOrder(reviewFixture(fields: {
        'summary': 's' * 5000,
        'issues': List.filled(66, 'i' * 1000),
      }));
      expect(result.summary!.length, 4001);
      expect(result.issues.length, 64);
      expect(result.issues.first.length, 1000);
      expect(result.incomplete, isTrue);
    });

    test('known photo/material fields retain their strict types', () {
      final result = AiReview.fromOrder(reviewFixture());
      expect(result.photoCheck!.uploaded, 3);
      expect(result.photoCheck!.unique, 2);
      expect(result.photoCheck!.exactDuplicates, 1);
      expect(result.photoCheck!.similarDuplicates, 0);
      expect(result.photoCheck!.verifiabilityScore, 3);
      expect(result.photoCheck!.duplicateDetected, isTrue);
      expect(result.photoCheck!.captureWindowMinutes, 60);
      expect(result.photoCheck!.uploadGapMinutes, 5);
      expect(result.materialsCheck!.lines, 2);
      expect(result.materialsCheck!.positiveQuantities, isTrue);
      expect(result.materialsCheck!.comparedToApprovedNorm, isFalse);
      expect(result.materialsCheck!.syntheticReference, isTrue);
      expect(result.materialsCheck!.evidence, MaterialEvidence.reported);
    });

    test('unknown nested values remain unknown, never zero/false', () {
      final result = AiReview.fromOrder(reviewFixture(fields: {
        'photo_check': {'uploaded': -1, 'unique': '2', 'exact_duplicates': true,
          'duplicate_detected': 0, 'verifiability_score': 99,
          'capture_window_minutes': '60', 'upload_gap_minutes': -1},
        'materials_check': {'lines': '2', 'positive_quantities': 1,
          'compared_to_approved_norm': 'false', 'norm_comparison': 'new-mode',
          'evidence_status': 'unknown-new'},
      }));
      expect(result.photoCheck!.uploaded, isNull);
      expect(result.photoCheck!.unique, isNull);
      expect(result.photoCheck!.exactDuplicates, isNull);
      expect(result.photoCheck!.duplicateDetected, isNull);
      expect(result.photoCheck!.verifiabilityScore, isNull);
      expect(result.photoCheck!.captureWindowMinutes, isNull);
      expect(result.photoCheck!.uploadGapMinutes, isNull);
      expect(result.materialsCheck!.lines, isNull);
      expect(result.materialsCheck!.positiveQuantities, isNull);
      expect(result.materialsCheck!.comparedToApprovedNorm, isNull);
      expect(result.materialsCheck!.syntheticReference, isFalse);
      expect(result.materialsCheck!.evidence, MaterialEvidence.unknown);
    });

    for (final fields in <Map<String, dynamic>>[
      {'master_confirmation_required': true},
      {'needs_master_attention': true},
      {'confidence': 0.3},
      {'photo_check': {'low_confidence_requires_master': true}},
      {'verdict': 'rework'},
    ]) {
      test('attention marker $fields requires master decision', () {
        expect(AiReview.fromOrder(modelFixture(fields: fields)).masterRequirement,
          MasterReviewRequirement.required);
      });
    }

    test('backend-added warnings after 20 model concerns are retained', () {
      final result = AiReview.fromOrder(modelFixture(fields: {
        'issues': [...List.filled(20, 'Synthetic model concern'), 'Final backend warning'],
      }));
      expect(result.mode, ReviewMode.modelReported);
      expect(result.issues.length, 21);
      expect(result.issues.last, 'Final backend warning');
    });

    for (final status in ['issued', 'queued', 'accepted', 'in_progress', 'paused', 'executed']) {
      test('retained analysis during $status is explicitly previous', () {
        expect(AiReview.fromOrder(modelFixture(orderFields: {'status': status})).previousResult, isTrue);
      });
    }
    test('analysis predating completion is previous even in ai_review', () {
      final result = AiReview.fromOrder(modelFixture(orderFields: {
        'ai_checked_at': '2026-10-07T12:00:00Z', 'completed_at': '2026-10-07T13:00:00Z',
      }));
      expect(result.previousResult, isTrue);
    });
    test('fresh review recommending rework is not a previous analysis', () {
      final result = AiReview.fromOrder(modelFixture(fields: {'verdict': 'rework'}, orderFields: {
        'status': 'rework', 'ai_checked_at': '2026-10-07T13:01:00Z',
        'completed_at': '2026-10-07T13:00:00Z',
      }));
      expect(result.previousResult, isFalse);
      expect(result.verdict, ReviewVerdict.rework);
    });
    test('latest saved result is not mislabeled previous', () {
      final result = AiReview.fromOrder(modelFixture(orderFields: {
        'ai_checked_at': '2026-10-07T13:01:00Z', 'completed_at': '2026-10-07T13:00:00Z',
      }));
      expect(result.previousResult, isFalse);
    });

    test('unknown JSON keys do not become visible fields', () {
      final result = AiReview.fromOrder({'ai_result': jsonEncode({
        'api_key': 'hidden-test-secret', 'debug': {'password': 'hidden'},
      })});
      expect(result.summary, isNull);
      expect(result.issues, isEmpty);
      expect(result.mode, ReviewMode.unknown);
      expect(result.incomplete, isTrue);
    });
  });

  group('Master rating is separate and closed-only', () {
    test('closed result uses rating/rating_reason, not report score/confidence', () {
      final order = modelFixture(orderFields: {'status': 'closed', 'rating': 5,
        'rating_reason': 'Foreman accepted the demonstrated result.', 'rated_by': 11});
      final rating = MasterRating.fromOrder(order)!;
      expect(rating.score, 5);
      expect(rating.reason, 'Foreman accepted the demonstrated result.');
      expect(AiReview.fromOrder(order).reportScore, 2);
      expect(AiReview.fromOrder(order).confidence, 0.85);
    });
    test('ordinary bracketed equipment references in a reason are preserved', () {
      final rating = MasterRating.fromOrder({'status': 'closed', 'rating': 4,
        'rating_reason': 'Проверен узел [A-12], замечаний нет.'})!;
      expect(rating.reason, 'Проверен узел [A-12], замечаний нет.');
    });
    test('non-closed order does not expose a final rating', () {
      expect(MasterRating.fromOrder({'status': 'rework', 'rating': 4}), isNull);
    });
    for (final invalid in [null, 0, 6, '5', 4.0, true]) {
      test('invalid final rating $invalid does not fabricate a value', () {
        final result = MasterRating.fromOrder({'status': 'closed',
          'rating': invalid, 'rating_reason': {'secret': 'hidden'}})!;
        expect(result.score, isNull);
        expect(result.reason, isNull);
      });
    }
  });
}
