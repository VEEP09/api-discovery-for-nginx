/* i18n 런타임.
 *
 * 언어 결정 순서: localStorage('lang') → navigator.language → 'en'.
 * 로그인 페이지는 인증 이전이라 계정 설정을 쓸 수 없으므로 localStorage 를 단일
 * 기준으로 삼는다.
 *
 * HTML 에는 기본 언어(영어) 문장을 그대로 두고 data-i18n 키를 함께 붙인다.
 * 영어 사용자는 치환이 일어나지 않아 깜빡임이 없고, 카탈로그 로드에 실패해도
 * 화면이 비지 않는다.
 *
 * 마크업 사용법:
 *   <span data-i18n="agents.empty.title">No agent connected.</span>
 *   <button data-i18n-attr="title:topbar.theme" title="Toggle theme">
 *   <input data-i18n-attr="placeholder:inventory.search" placeholder="Search URI…">
 */
(function (global) {
  'use strict';

  var SUPPORTED = ['en', 'ko'];
  var DEFAULT = 'en';
  var STORAGE_KEY = 'lang';

  var catalog = {};
  var current = DEFAULT;

  function detect() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved && SUPPORTED.indexOf(saved) !== -1) return saved;
    } catch (e) { /* localStorage 차단 환경 */ }
    var nav = (navigator.language || navigator.userLanguage || '').toLowerCase();
    for (var i = 0; i < SUPPORTED.length; i++) {
      if (nav.indexOf(SUPPORTED[i]) === 0) return SUPPORTED[i];
    }
    return DEFAULT;
  }

  /* t('a.b', {n: 3}) — 키가 없으면 fallback(있으면) 또는 키 자체를 돌려준다.
     번역 누락이 화면을 비우지 않도록 항상 문자열을 반환한다. */
  function t(key, params, fallback) {
    var s = catalog[key];
    if (s == null) s = (fallback != null ? fallback : key);
    if (params) {
      s = s.replace(/\{(\w+)\}/g, function (m, k) {
        return params[k] != null ? params[k] : m;
      });
    }
    return s;
  }

  function apply(root) {
    var scope = root || document;

    scope.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      var s = catalog[key];
      if (s == null) return;
      /* textContent 로 덮으면 자식 엘리먼트가 지워진다. 제목·라벨 다수가
         도움말 아이콘(<span class="help-tip">?</span>)을 자식으로 갖고 있어
         한 번 적용하는 것만으로 아이콘이 사라진다. 첫 텍스트 노드만 바꾼다. */
      var node = el.firstChild;
      while (node && node.nodeType !== 3) node = node.nextSibling;
      if (node) node.nodeValue = s;
      else el.insertBefore(document.createTextNode(s), el.firstChild);
    });

    /* data-i18n-attr="title:key" 또는 "title:key;placeholder:key2" */
    scope.querySelectorAll('[data-i18n-attr]').forEach(function (el) {
      el.getAttribute('data-i18n-attr').split(';').forEach(function (pair) {
        var idx = pair.indexOf(':');
        if (idx < 0) return;
        var attr = pair.slice(0, idx).trim();
        var key = pair.slice(idx + 1).trim();
        var s = catalog[key];
        if (s != null) el.setAttribute(attr, s);
      });
    });
  }

  function load(lang) {
    return fetch('/static/i18n/' + lang + '.json', { cache: 'no-cache' })
      .then(function (r) {
        if (!r.ok) throw new Error('catalog ' + lang + ': HTTP ' + r.status);
        return r.json();
      });
  }

  /* 언어 전환. 영어는 HTML 원문이 곧 정답이므로 카탈로그 없이도 동작해야 하지만,
     ko → en 전환 시 되돌릴 문장이 필요하므로 en.json 도 동일하게 로드한다. */
  function setLang(lang) {
    if (SUPPORTED.indexOf(lang) === -1) lang = DEFAULT;
    return load(lang).then(function (c) {
      catalog = c;
      current = lang;
      try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) {}
      document.documentElement.setAttribute('lang', lang);
      apply();
      global.dispatchEvent(new CustomEvent('languagechange', { detail: { lang: lang } }));
      return lang;
    }).catch(function (err) {
      console.error('[i18n]', err);   // 화면은 기본 언어 원문으로 유지된다
      return current;
    });
  }

  function init() {
    var sel = document.getElementById('lang-select');
    if (sel) {
      sel.addEventListener('change', function () { setLang(sel.value); });
    }
    return setLang(detect()).then(function (lang) {
      if (sel) sel.value = lang;
      return lang;
    });
  }

  global.I18n = {
    t: t,
    apply: apply,
    setLang: setLang,
    init: init,
    get lang() { return current; },
    supported: SUPPORTED.slice()
  };
  global.t = t;   // 호출부 간결하게
})(window);
