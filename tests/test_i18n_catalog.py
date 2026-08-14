"""UI 문자열 카탈로그 정합성.

다국어가 깨지는 가장 흔한 경로는 "새 문자열을 한쪽 언어에만 추가"다.
사람의 기억에 의존하면 반드시 어긋나므로 테스트로 고정한다.
"""
import json
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parents[1] / "src" / "dashboard" / "static" / "i18n"
BASE = "en"


def _load(lang):
    return json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _languages():
    return sorted(p.stem for p in I18N_DIR.glob("*.json"))


def test_base_catalog_exists():
    assert (I18N_DIR / f"{BASE}.json").is_file(), f"기준 카탈로그 {BASE}.json 이 없다"


def test_all_catalogs_share_the_same_keys():
    base = _load(BASE)
    for lang in _languages():
        if lang == BASE:
            continue
        other = _load(lang)
        missing = sorted(set(base) - set(other))
        extra = sorted(set(other) - set(base))
        assert not missing, f"{lang}.json 에 없는 키: {missing}"
        assert not extra, f"{lang}.json 에만 있는 키: {extra}"


def test_no_empty_values():
    for lang in _languages():
        blank = sorted(k for k, v in _load(lang).items() if not str(v).strip())
        assert not blank, f"{lang}.json 값이 비어 있는 키: {blank}"


def test_placeholders_match_across_languages():
    """{name} 형태 치환자가 언어마다 달라지면 렌더링이 깨진다."""
    import re
    ph = lambda s: set(re.findall(r"\{(\w+)\}", s))
    base = _load(BASE)
    for lang in _languages():
        if lang == BASE:
            continue
        other = _load(lang)
        for k, v in base.items():
            assert ph(v) == ph(other[k]), f"{lang}.json '{k}' 치환자 불일치: {ph(v)} vs {ph(other[k])}"


def _keys_used_in_code():
    import re
    root = I18N_DIR.parents[1]          # src/dashboard
    used = set()
    js = (root / "static" / "dashboard.js").read_text(encoding="utf-8")
    used |= set(re.findall(r"(?<![\w.])t\('([\w.]+)'", js))
    for name in ("index.html", "login.html"):
        html = (root / "templates" / name).read_text(encoding="utf-8")
        used |= set(re.findall(r'data-i18n="([\w.]+)"', html))
        for spec in re.findall(r'data-i18n-attr="([^"]+)"', html):
            used |= {p.split(":", 1)[1].strip() for p in spec.split(";") if ":" in p}
    return used


def test_every_key_used_by_code_exists_in_the_catalog():
    """코드가 참조하는 키가 카탈로그에 없으면 화면에 키 문자열이 그대로 노출된다."""
    missing = sorted(_keys_used_in_code() - set(_load(BASE)))
    assert not missing, f"카탈로그에 없는 키: {missing}"


def test_no_orphan_keys():
    """어디서도 쓰지 않는 키는 번역 비용만 늘린다."""
    orphans = sorted(set(_load(BASE)) - _keys_used_in_code())
    assert not orphans, f"코드에서 참조하지 않는 키: {orphans}"
