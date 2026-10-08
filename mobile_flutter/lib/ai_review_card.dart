import 'package:flutter/material.dart';

import 'ai_review.dart';
import 'app_settings.dart';

/// Stored advisory information only. No role, acceptance or API logic lives here.
class AiReviewCard extends StatelessWidget {
  const AiReviewCard({required this.order, super.key});
  final Map<String, dynamic> order;

  @override
  Widget build(BuildContext context) {
    final review = AiReview.fromOrder(order);
    final masterRating = MasterRating.fromOrder(order);
    final colors = Theme.of(context).colorScheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(context.tr(review.previousResult ? 'Предыдущий результат анализа' : 'Результат анализа'),
              style: TextStyle(color: colors.onSurface, fontSize: 16,
                fontWeight: FontWeight.w800)),
            const SizedBox(height: 12),
            if (!review.available)
              Text(context.tr(review.unreadable
                ? 'Не удалось прочитать сохранённый анализ. Обновите наряд или обратитесь к мастеру.'
                : 'Сохранённого результата анализа пока нет.'))
            else ...[
              if (review.previousResult) ...[
                Text(context.tr('Это сохранённый анализ до доработки или повторной сдачи. Он не подтверждает новый отчёт; после доработки нужен новый анализ.'),
                  style: TextStyle(color: colors.onSurfaceVariant, fontWeight: FontWeight.w600)),
                const SizedBox(height: 12),
              ],
              _ReviewFact(context.tr('Режим анализа'), context.tr(switch (review.mode) {
                ReviewMode.rulesOnly => 'Только правила (rules-only)',
                ReviewMode.modelReported => 'Модель (по данным сервера)',
                ReviewMode.unknown => 'Режим не подтверждён',
              })),
              Text(context.tr(switch (review.mode) {
                ReviewMode.rulesOnly => 'Проверены правила заполнения. Смысловое соответствие отчёта наряду моделью не подтверждено.',
                ReviewMode.modelReported => 'В сохранённом результате сервер указал модель. Это не проверка её текущей доступности.',
                ReviewMode.unknown => 'Данных недостаточно, чтобы подтвердить использование модели.',
              }), style: TextStyle(color: colors.onSurfaceVariant)),
              const SizedBox(height: 12),
              _ReviewFact(context.tr('Вывод анализа'), context.tr(switch (review.verdict) {
                ReviewVerdict.accepted => 'Без замечаний по анализу',
                ReviewVerdict.comments => 'Есть замечания',
                ReviewVerdict.rework => 'Рекомендована доработка',
                ReviewVerdict.unknown => 'Вывод не указан или неизвестен',
              })),
              _ReviewFact(context.tr('Проверка мастером'), context.tr(switch (review.masterRequirement) {
                MasterReviewRequirement.required => 'Решение мастера обязательно',
                MasterReviewRequirement.notRequested => 'Дополнительная проверка сервером не запрошена',
                MasterReviewRequirement.unspecified => 'Требование дополнительной проверки не указано',
              })),
              if (review.incomplete)
                Text(context.tr('Часть полей анализа отсутствует или не распознана. Не делайте вывод по неполным данным.'),
                  style: TextStyle(color: colors.onSurfaceVariant)),
              const SizedBox(height: 12),
              _ReviewFact(context.tr('Краткий итог'),
                review.summary == null ? context.tr('Нет данных') : context.tr(review.summary!)),
              _ReviewFact(context.tr(review.previousResult
                  ? 'Оценка прошлого отчёта моделью' : 'Оценка содержания отчёта моделью'),
                review.reportScore == null ? context.tr('Оценка модели отсутствует')
                  : context.tr('{score} из 5', {'score': review.reportScore})),
              if (review.scoreReason != null)
                _ReviewFact(context.tr('Обоснование оценки отчёта'), context.tr(review.scoreReason!)),
              if (review.confidence != null)
                _ReviewFact(context.tr('Уверенность модели (по данным сервера)'),
                  '${(review.confidence! * 100).round()}%'),
              Text(context.tr('Балл отчёта и уверенность модели не являются итоговой оценкой мастера или подтверждением качества ремонта.'),
                style: TextStyle(color: colors.onSurfaceVariant)),
              const SizedBox(height: 12),
              Text(context.tr('Замечания анализа'),
                style: const TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              if (review.issues.isEmpty)
                Text(context.tr(review.incomplete
                  ? 'Нет доступных замечаний для отображения.'
                  : 'Список замечаний пуст.'))
              else
                for (final issue in review.issues)
                  Padding(padding: const EdgeInsets.only(bottom: 8),
                    child: Text('• ${context.tr(issue)}')),
              const SizedBox(height: 8),
              Text(context.tr('Свободный текст сервера показан на исходном языке.'),
                style: TextStyle(color: colors.onSurfaceVariant, fontSize: 12)),
              if (review.photoCheck != null) ...[
                const Divider(height: 28),
                _photoChecks(context, review.photoCheck!),
              ],
              if (review.materialsCheck != null) ...[
                const Divider(height: 28),
                _materialsChecks(context, review.materialsCheck!),
              ],
            ],
            if (masterRating != null) ...[
              const Divider(height: 28),
              Text(context.tr('Итоговая оценка мастера'),
                style: const TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              _ReviewFact(context.tr('Оценка принятого наряда'), masterRating.score == null
                ? context.tr('Нет данных') : context.tr('{score} из 5', {'score': masterRating.score})),
              _ReviewFact(context.tr('Обоснование мастера'), masterRating.reason ?? context.tr('Нет данных')),
              Text(context.tr('Источник: сохранённое решение мастера при приёмке или последующей корректировке.'),
                style: TextStyle(color: colors.onSurfaceVariant)),
            ],
            const SizedBox(height: 12),
            Text(context.tr('Анализ носит рекомендательный характер. Окончательная приёмка и решение по наряду остаются за мастером.'),
              style: TextStyle(color: colors.onSurfaceVariant, height: 1.4)),
          ],
        ),
      ),
    );
  }

  Widget _photoChecks(BuildContext context, PhotoReview photo) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text(context.tr('Проверка фото'), style: const TextStyle(fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      _ReviewFact(context.tr('Загружено фото'), _value(context, photo.uploaded)),
      _ReviewFact(context.tr('Уникальных фото'), _value(context, photo.unique)),
      _ReviewFact(context.tr('Точных дублей'), _value(context, photo.exactDuplicates)),
      _ReviewFact(context.tr('Похожих дублей'), _value(context, photo.similarDuplicates)),
      _ReviewFact(context.tr('Обнаружены дубли'), _boolean(context, photo.duplicateDetected)),
      _ReviewFact(context.tr('Проверяемость файла'), photo.verifiabilityScore == null
        ? context.tr('Нет данных') : context.tr('{score} из 5', {'score': photo.verifiabilityScore})),
      _ReviewFact(context.tr('Фото требуют проверки мастером'), _boolean(context, photo.lowConfidenceRequiresMaster)),
      if (photo.captureWindowMinutes != null)
        _ReviewFact(context.tr('Допустимое расхождение времени съёмки'),
          context.tr('{count} мин.', {'count': photo.captureWindowMinutes})),
      if (photo.uploadGapMinutes != null)
        _ReviewFact(context.tr('Разница между загрузкой и выполнением'),
          context.tr('{count} мин.', {'count': photo.uploadGapMinutes})),
      Text(context.tr('Проверяемость файла не оценивает качество ремонта. EXIF может отсутствовать или быть изменён; фото не подтверждает исправность.'),
        style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
    ],
  );

  Widget _materialsChecks(BuildContext context, MaterialsReview materials) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text(context.tr('Проверка материалов'), style: const TextStyle(fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      _ReviewFact(context.tr('Строк материалов'), _value(context, materials.lines)),
      _ReviewFact(context.tr('Все количества положительные'), _boolean(context, materials.positiveQuantities)),
      _ReviewFact(context.tr('Сведения о расходе'), context.tr(switch (materials.evidence) {
        MaterialEvidence.reported => 'Расход указан в отчёте',
        MaterialEvidence.notUsed => 'Подтверждено отсутствие расхода',
        MaterialEvidence.conflict => 'Противоречивые сведения о расходе',
        MaterialEvidence.unknown => 'Нет данных',
      })),
      _ReviewFact(context.tr('Сравнение материалов'), context.tr(materials.syntheticReference
        ? 'Учебный пример'
        : 'Применимое сравнение не подтверждено')),
      _ReviewFact(context.tr('Сравнение с утверждённой нормой'), _boolean(context, materials.comparedToApprovedNorm)),
      Text(context.tr('Учебное сравнение не является нормой расхода или основанием для штрафа.'),
        style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
    ],
  );

  String _value(BuildContext context, num? value) => value == null
      ? context.tr('Нет данных') : '$value';
  String _boolean(BuildContext context, bool? value) => value == null
      ? context.tr('Нет данных') : context.tr(value ? 'Да' : 'Нет');
}

// Stacked labels wrap at narrow widths and under accessibility text scaling.
// No fixed height, horizontal chips, or truncation hides the decision warning.
class _ReviewFact extends StatelessWidget {
  const _ReviewFact(this.label, this.value);
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(label, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
      const SizedBox(height: 3),
      Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
    ]),
  );
}
