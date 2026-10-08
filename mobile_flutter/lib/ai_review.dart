import 'dart:convert';

enum ReviewMode { rulesOnly, modelReported, unknown }
enum ReviewVerdict { accepted, comments, rework, unknown }
enum MasterReviewRequirement { required, notRequested, unspecified }

/// A read-only, bounded projection of the server's stored analysis.
/// Unknown fields (including debug details, prompts and credentials) are never
/// retained for rendering. This does not authorize acceptance or any API action.
class AiReview {
  const AiReview._({
    this.available = false,
    this.unreadable = false,
    this.incomplete = false,
    this.previousResult = false,
    this.mode = ReviewMode.unknown,
    this.verdict = ReviewVerdict.unknown,
    this.summary,
    this.reportScore,
    this.scoreReason,
    this.confidence,
    this.issues = const [],
    this.masterRequirement = MasterReviewRequirement.unspecified,
    this.photoCheck,
    this.materialsCheck,
  });

  final bool available;
  final bool unreadable;
  final bool incomplete;
  final bool previousResult;
  final ReviewMode mode;
  final ReviewVerdict verdict;
  final String? summary;
  final int? reportScore;
  final String? scoreReason;
  final num? confidence;
  final List<String> issues;
  final MasterReviewRequirement masterRequirement;
  final PhotoReview? photoCheck;
  final MaterialsReview? materialsCheck;

  factory AiReview.fromOrder(Map<String, dynamic> order) {
    final raw = order['ai_result'];
    if (raw == null || (raw is String && raw.trim().isEmpty)) {
      return const AiReview._();
    }
    // The backend contract is a JSON string, not a printable arbitrary object.
    if (raw is! String || raw.length > 128000) {
      return const AiReview._(unreadable: true);
    }
    dynamic decoded;
    try {
      decoded = jsonDecode(raw);
    } on FormatException {
      return const AiReview._(unreadable: true);
    }
    if (decoded is! Map<String, dynamic>) {
      return const AiReview._(unreadable: true);
    }
    final result = decoded;
    final summary = _safeText(result['summary'], 4000);
    final verdict = switch (result['verdict']) {
      'accepted' => ReviewVerdict.accepted,
      'comments' => ReviewVerdict.comments,
      'rework' => ReviewVerdict.rework,
      _ => ReviewVerdict.unknown,
    };
    final rawIssues = result['issues'];
    final issues = <String>[];
    var incomplete = summary == null || verdict == ReviewVerdict.unknown ||
        rawIssues is! List;
    if (rawIssues is List) {
      if (rawIssues.length > 64) incomplete = true;
      for (final value in rawIssues.take(64)) {
        final text = _safeText(value, 1000);
        if (text == null) {
          incomplete = true;
        } else {
          issues.add(text);
        }
      }
    }
    final innerMode = result['mode'];
    final outerMode = order['ai_mode'];
    ReviewMode mode = ReviewMode.unknown;
    if (_isRulesMode(innerMode) &&
        (outerMode == null || _isRulesMode(outerMode))) {
      mode = ReviewMode.rulesOnly;
    } else if (!incomplete && innerMode is String &&
        _modelMode.hasMatch(innerMode) && outerMode == innerMode) {
      // Only matching stored fields and usable content support this label.
      // Even then, the UI says "reported by server", never "live/verified AI".
      mode = ReviewMode.modelReported;
    }
    final required = _bool(result['master_confirmation_required']);
    final attention = _bool(result['needs_master_attention']);
    final photo = PhotoReview.parse(result['photo_check']);
    final confidence = mode == ReviewMode.modelReported
        ? _number(result['confidence'], 1) : null;
    final masterRequirement = mode != ReviewMode.modelReported ||
            incomplete || issues.isNotEmpty || required == true || attention == true ||
            photo?.lowConfidenceRequiresMaster == true ||
            (confidence != null && confidence < 0.60) ||
            verdict != ReviewVerdict.accepted
        ? MasterReviewRequirement.required
        : required == false
            ? MasterReviewRequirement.notRequested
            : MasterReviewRequirement.unspecified;
    return AiReview._(
      available: true,
      incomplete: incomplete,
      previousResult: _isPreviousResult(order),
      mode: mode,
      verdict: verdict,
      summary: summary,
      reportScore: mode == ReviewMode.modelReported ? _score(result['report_score']) : null,
      scoreReason: _safeText(result['score_reason'], 2000),
      confidence: confidence,
      issues: List.unmodifiable(issues),
      masterRequirement: masterRequirement,
      photoCheck: photo,
      materialsCheck: MaterialsReview.parse(result['materials_check']),
    );
  }
}

/// Final persisted rating belongs to the master, independent of the analysis.
class MasterRating {
  const MasterRating({this.score, this.reason});
  final int? score;
  final String? reason;
  static MasterRating? fromOrder(Map<String, dynamic> order) {
    if (order['status'] != 'closed') return null;
    return MasterRating(score: _score(order['rating']),
      reason: _safeText(order['rating_reason'], 2000));
  }
}

bool _isPreviousResult(Map<String, dynamic> order) {
  // The backend retains old ai_result during rework/reissue and resubmission.
  if (const {'issued', 'queued', 'accepted', 'in_progress', 'paused',
      'executed'}.contains(order['status'])) return true;
  final checked = order['ai_checked_at'];
  final completed = order['completed_at'];
  final checkedAt = checked is String ? DateTime.tryParse(checked) : null;
  final completedAt = completed is String ? DateTime.tryParse(completed) : null;
  return checkedAt != null && completedAt != null && checkedAt.isBefore(completedAt);
}

int? _score(dynamic value) => value is int && value >= 1 && value <= 5
    ? value : null;

final _modelMode = RegExp(r'^llm:[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$');
bool _isRulesMode(dynamic value) => value is String &&
    (value == 'rules-only' || value.startsWith('rules-only:'));
bool? _bool(dynamic value) => value is bool ? value : null;
int? _count(dynamic value) => value is int && value >= 0 && value <= 1000000
    ? value : null;
num? _number(dynamic value, num maximum) =>
    value is num && value.isFinite && value >= 0 && value <= maximum
        ? value : null;

String? _safeText(dynamic value, int limit) {
  if (value is! String) return null;
  var text = value.trim();
  if (text.isEmpty || RegExp(
      r'''(?:\{\s*(?:["'}]|\w+\s*:)|\[\s*(?:["'{\[\]\d-]|true\b|false\b|null\b))''',
      ).hasMatch(text) || text.contains('```') ||
      RegExp(r'-----BEGIN .*PRIVATE KEY-----').hasMatch(text)) return null;
  // Defense in depth for credential-shaped strings inside human-facing fields.
  // Never render arbitrary maps/lists, adapter exceptions or unknown fields.
  text = text.replaceAll(RegExp(r'\b(?:sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{12,})'), '•••');
  text = text.replaceAll(RegExp(r'Bearer\s+[^\s,;]+', caseSensitive: false), 'Bearer •••');
  text = text.replaceAll(RegExp(
    r'''(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|password|secret|пароль)["']?\s*[=:]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)''',
    caseSensitive: false,
  ), '•••');
  text = text.replaceAll(RegExp(r'https?://[^\s/@]+:[^\s/@]+@[^\s]+', caseSensitive: false), '•••');
  text = text.replaceAll(RegExp(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]'), '');
  if (text.length > limit) text = '${text.substring(0, limit)}…';
  return text.isEmpty ? null : text;
}

class PhotoReview {
  const PhotoReview({this.uploaded, this.unique, this.exactDuplicates,
    this.similarDuplicates, this.duplicateDetected, this.verifiabilityScore,
    this.lowConfidenceRequiresMaster, this.captureWindowMinutes,
    this.uploadGapMinutes});
  final int? uploaded;
  final int? unique;
  final int? exactDuplicates;
  final int? similarDuplicates;
  final bool? duplicateDetected;
  final num? verifiabilityScore;
  final bool? lowConfidenceRequiresMaster;
  final int? captureWindowMinutes;
  final num? uploadGapMinutes;

  static PhotoReview? parse(dynamic raw) {
    if (raw is! Map<String, dynamic>) return null;
    final score = _number(raw['verifiability_score'], 5);
    return PhotoReview(
      uploaded: _count(raw['uploaded']),
      unique: _count(raw['unique']),
      exactDuplicates: _count(raw['exact_duplicates']),
      similarDuplicates: _count(raw['similar_duplicates']),
      duplicateDetected: _bool(raw['duplicate_detected']),
      verifiabilityScore: score != null && score >= 1 ? score : null,
      lowConfidenceRequiresMaster: _bool(raw['low_confidence_requires_master']),
      captureWindowMinutes: _count(raw['capture_window_minutes']),
      uploadGapMinutes: _number(raw['upload_gap_minutes'], 1000000),
    );
  }
}

enum MaterialEvidence { reported, notUsed, conflict, unknown }

class MaterialsReview {
  const MaterialsReview({this.lines, this.positiveQuantities,
    this.comparedToApprovedNorm, this.syntheticReference = false,
    this.evidence = MaterialEvidence.unknown});
  final int? lines;
  final bool? positiveQuantities;
  final bool? comparedToApprovedNorm;
  final bool syntheticReference;
  final MaterialEvidence evidence;

  static MaterialsReview? parse(dynamic raw) {
    if (raw is! Map<String, dynamic>) return null;
    return MaterialsReview(
      lines: _count(raw['lines']),
      positiveQuantities: _bool(raw['positive_quantities']),
      comparedToApprovedNorm: _bool(raw['compared_to_approved_norm']),
      syntheticReference: raw['norm_comparison'] == 'synthetic_reference',
      evidence: switch (raw['evidence_status']) {
        'reported_usage' => MaterialEvidence.reported,
        'confirmed_not_used' => MaterialEvidence.notUsed,
        'conflict' => MaterialEvidence.conflict,
        _ => MaterialEvidence.unknown,
      },
    );
  }
}
