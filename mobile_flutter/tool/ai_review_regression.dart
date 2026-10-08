// Pure Dart smoke checks; no Flutter packages, network or model calls.
// Run: dart tool/ai_review_regression.dart
import 'dart:io';

import '../lib/ai_review.dart';
import '../test/ai_review_fixtures.dart';

void check(bool condition, String name) {
  if (!condition) throw StateError('FAIL: $name');
  stdout.writeln('PASS: $name');
}

void main() {
  final rules = AiReview.fromOrder(reviewFixture());
  check(rules.mode == ReviewMode.rulesOnly && rules.reportScore == null &&
    rules.masterRequirement == MasterReviewRequirement.required, 'rules-only is advisory');
  final model = AiReview.fromOrder(modelFixture());
  check(model.mode == ReviewMode.modelReported && model.reportScore == 2 &&
    model.confidence == 0.85, 'matching server model and separate report score/confidence');
  check(AiReview.fromOrder({'ai_result': '{broken'}).unreadable, 'malformed JSON is contained');
  check(!AiReview.fromOrder({'ai_result': null}).available, 'null has no result');
  check(AiReview.fromOrder(modelFixture(orderFields: {'ai_mode': null})).mode ==
    ReviewMode.unknown, 'missing mode does not confirm model');
  final secret = AiReview.fromOrder(reviewFixture(fields: {
    'summary': 'Diagnostic: {"api_key":"hidden-test-secret"}',
    'issues': ['password="two word secret"'],
  }));
  check(secret.summary == null && !secret.issues.join().contains('two word secret'),
    'embedded JSON and quoted credentials are suppressed');
  check(AiReview.fromOrder(modelFixture(orderFields: {'status': 'executed'})).previousResult,
    'old analysis after resubmission is identified');
  final finalRating = MasterRating.fromOrder({'status': 'closed', 'rating': 5,
    'rating_reason': 'Synthetic foreman reason.'});
  check(finalRating?.score == 5 && finalRating?.reason == 'Synthetic foreman reason.',
    'final master rating is independent');
  final extended = AiReview.fromOrder(modelFixture(fields: {
    'issues': [...List.filled(20, 'Synthetic issue'), 'Final backend warning'],
  }));
  check(extended.issues.length == 21 && extended.mode == ReviewMode.modelReported,
    'post-model backend warnings survive');
}
