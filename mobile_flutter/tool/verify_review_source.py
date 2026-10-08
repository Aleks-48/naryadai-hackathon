"""Source-level checks for mobile v3. Does not execute Dart or Flutter.

python3 tool/verify_review_source.py [--baseline PATH] [--backend PATH/server.py]
"""
import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', type=Path)
parser.add_argument('--backend', type=Path)
args = parser.parse_args()

def catalog(path):
    source = path.read_text()
    return json.loads(re.sub(r',\s*([}\]])', r'\1', source[source.index('=') + 1:].strip().rstrip(';')))

entries = catalog(ROOT / 'lib/translations.dart')
card = (ROOT / 'lib/ai_review_card.dart').read_text()
labels = re.findall(r"'([^'\n]*[А-Яа-яЁё][^'\n]*)'", card)
for label in labels:
    if '$' not in label:
        assert label in entries, label
        assert set(entries[label]) == {'ru', 'kk', 'en'}, label
print('PASS all analysis-card literal and dynamic-branch labels have RU/KK/EN entries')

errors = [
    'Изображение распознано как точный или похожий дубль; файл не сохранён. Выберите другое фото.',
    'Можно приложить не более пяти активных фото каждой фазы. Сначала завершите доработку или замену.',
    'Предыдущие заменённые фото ещё очищаются; повторите загрузку после завершения очистки',
    'В бригаде нет активного исполнителя.',
]
for error in errors:
    assert entries[error]['ru'] == error
    assert entries[error]['kk'] != error and entries[error]['en'] != error
print('PASS four exact error mappings are present in all three languages')
if args.backend:
    backend = args.backend.read_text()
    literals = {node.value for node in ast.walk(ast.parse(backend))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for error in errors:
        assert error in literals, error
    for field in ['ai_result', 'ai_mode', 'report_score', 'score_reason',
                  'confidence', 'master_confirmation_required', 'photo_check',
                  'materials_check', 'rating', 'rating_reason']:
        assert field in literals, field
    assert 'f"llm:{model}"' in backend
    assert '"rules-only: adapter_error"' in backend
    print('PASS supplied server source has matching error strings, modes and displayed field names')
else:
    print('NOT RUN backend source comparison: supply --backend')

main = (ROOT / 'lib/main.dart').read_text()
assert main.count('AiReviewCard(order: order)') == 1
for source_file in ['ai_review.dart', 'ai_review_card.dart']:
    source = (ROOT / 'lib' / source_file).read_text()
    assert "import 'api.dart'" not in source
    assert 'EnbekApi' not in source and '.action(' not in source
    assert 'HttpClient' not in source and 'http://' not in source
    assert 'Image.network' not in source
print('PASS review projection/card contains no API client, action or network calls')

if args.baseline:
    base = args.baseline
    for folder in ['lib', 'test', 'tool']:
        for original in (base / folder).rglob('*'):
            if not original.is_file():
                continue
            relative = original.relative_to(base)
            if str(relative) in ['lib/main.dart', 'lib/translations.dart']:
                continue
            assert original.read_bytes() == (ROOT / relative).read_bytes(), str(relative)
    for name in ['pubspec.yaml', 'pubspec.dependencies.fragment.yaml']:
        assert (base / name).read_bytes() == (ROOT / name).read_bytes(), name
    original_main = (base / 'lib/main.dart').read_text()
    reverted = main.replace("import 'ai_review_card.dart';\n", '').replace(
        '                  AiReviewCard(order: order),\n                  const SizedBox(height: 12),\n', '')
    assert reverted == original_main, 'Main changes exceed import and read-only card insertion'
    original_catalog = catalog(base / 'lib/translations.dart')
    assert all(entries[k] == v for k, v in original_catalog.items())
    print('PASS baseline API/permissions/action code, dependencies and existing tests/tools unchanged')
else:
    print('NOT RUN baseline byte comparison: supply --baseline')
print('NOT RUN Dart behavior, analyzer, formatting, widget rendering, device flows or APK build')
