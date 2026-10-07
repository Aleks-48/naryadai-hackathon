"""Static checks only; not a substitute for dart analyze or flutter test."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'lib/translations.dart').read_text()
body = source[source.index('=') + 1:].strip().rstrip(';')
catalog = json.loads(re.sub(r',\s*([}\]])', r'\1', body))
for key, values in catalog.items():
    assert set(values) == {'ru', 'kk', 'en'} and values['ru'] == key
    tokens = sorted(re.findall(r'\{[a-zA-Z][a-zA-Z0-9_]*\}', key))
    for translated in values.values():
        assert translated.strip()
        assert sorted(re.findall(r'\{[a-zA-Z][a-zA-Z0-9_]*\}', translated)) == tokens
for file in (ROOT / 'lib').glob('*.dart'):
    text = file.read_text()
    assert '<<<<<<<' not in text and '>>>>>>>' not in text
    if file.name == 'translations.dart':
        continue
    for match in re.finditer(r"\b(?:tr|translate)\(\s*'((?:\\.|[^'\\])*)'", text):
        key = match.group(1)
        if '$' not in key:
            assert key in catalog, (file.name, key)
api = (ROOT / 'lib/api.dart').read_text()
assert 'request.contentLength = encodedBody.length;' in api
assert 'request.followRedirects = false;' in api
assert "baseUri.resolve('/api/photos/$photoId')" in api
assert 'photo[\'url\']' not in (ROOT / 'lib/order_photos.dart').read_text()
assert 'Image.network' not in (ROOT / 'lib/order_photos.dart').read_text()
print(f'PASS {len(catalog)} complete RU/KK/EN entries, placeholders and direct UI keys')
print('PASS Content-Length fix and protected-media source guards retained')

def luminance(rgb):
    channels = [int(rgb[i:i+2], 16) / 255 for i in (0, 2, 4)]
    channels = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
    return sum(w*v for w, v in zip((.2126, .7152, .0722), channels))

pairs = {
    'light': [('1d2d36','ffffff'), ('50636d','ffffff'), ('ffffff','245d52'), ('74231f','fceae8'), ('4d3d1e','f5ecd5')],
    'dark': [('e1ecf0','15232b'), ('adc0ca','15232b'), ('07382d','8ad3bd'), ('ffc9c3','492d2d'), ('ebd8aa','3e331d')],
}
for theme, colors in pairs.items():
    for foreground, background in colors:
        low, high = sorted((luminance(foreground), luminance(background)))
        ratio = (high+.05)/(low+.05)
        assert ratio >= 4.5, (theme, foreground, background, ratio)
        print(f'PASS {theme} palette {foreground}/{background}: {ratio:.2f}:1')
print('NOT RUN: Dart/Flutter analyzer, formatter, widget tests, Android build or device flows')
