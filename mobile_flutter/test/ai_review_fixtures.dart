import 'dart:convert';

// Synthetic data only. These fixtures never connect to an actual model/server.
Map<String, dynamic> reviewFixture({
  String mode = 'rules-only: disabled',
  String verdict = 'comments',
  Map<String, dynamic> fields = const {},
  Map<String, dynamic> orderFields = const {},
}) => {
  'id': 7,
  'code': 'TEST-000007',
  'title': 'Synthetic maintenance report',
  'status': 'ai_review',
  'photos': <Map<String, dynamic>>[],
  'ai_mode': mode,
  'ai_result': jsonEncode({
    'mode': mode,
    'verdict': verdict,
    'summary': 'Проверены доступные данные синтетического отчёта.',
    'issues': ['Проверьте результат работы с мастером.'],
    'master_confirmation_required': true,
    'needs_master_attention': true,
    'report_score': null,
    'score_reason': 'LLM-оценка отсутствует: выполнена только локальная проверка правил.',
    'photo_check': {
      'uploaded': 3,
      'unique': 2,
      'exact_duplicates': 1,
      'similar_duplicates': 0,
      'duplicate_detected': true,
      'verifiability_score': 3,
      'low_confidence_requires_master': true,
      'capture_window_minutes': 60,
      'upload_gap_minutes': 5,
      'capture_checks': [{'capture_datetime': '2026-10-07T12:00:00Z'}],
      'unknown_debug': 'hidden-photo-field',
    },
    'materials_check': {
      'lines': 2,
      'positive_quantities': true,
      'norm_comparison': 'synthetic_reference',
      'compared_to_approved_norm': false,
      'evidence_status': 'reported_usage',
      'unknown_debug': 'hidden-material-field',
    },
    'unknown_debug': 'hidden-top-level-field',
    ...fields,
  }),
  ...orderFields,
};

Map<String, dynamic> modelFixture({Map<String, dynamic> fields = const {},
  Map<String, dynamic> orderFields = const {}}) => reviewFixture(
  mode: 'llm:synthetic-test-model', verdict: 'accepted',
  fields: {
    'summary': 'The reported repair addresses the stated synthetic problem.',
    'issues': <String>[],
    'master_confirmation_required': false,
    'needs_master_attention': false,
    'report_score': 2,
    'score_reason': 'Synthetic model reason for report content only.',
    'confidence': 0.85,
    'photo_check': null,
    ...fields,
  }, orderFields: orderFields,
);
