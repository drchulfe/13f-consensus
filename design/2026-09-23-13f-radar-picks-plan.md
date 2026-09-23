# 추천 종목·회사 설명 추가 — 구현 계획

> **For agentic workers:** 이 계획은 기존 13F 레이더(main 브랜치, 테스트 57 pytest + 9 node 통과 상태)에 두 가지를 더한다. 태스크별로 구현 → 테스트 → 커밋한다.

**Goal:** (1) 지금 조건에서 사기 좋은 순서를 공개된 계산식으로 매겨 Top 5로 보여주고, (2) 각 종목이 무슨 회사인지 한국어로 설명한다.

**Spec 추가:** design/2026-09-23-13f-radar-live-design.md — 아래 내용을 반영해 5절(스키마)·8절(화면)에 추가한다(컨트롤러가 수행).

## Global Constraints (기존과 동일)

- ROOT = `/mnt/c/사업/투자_/13f-consensus/13f-consensus`, 브랜치 `main`에서 작업. 파이썬 `~/.venvs/13f/bin/python`.
- 의존성 추가 금지(requests·pandas·numpy·yfinance·pytest). Python 3.12 호환.
- 화면은 단일 HTML, 한국어, 기존 디자인 토큰. `node --test tests/js/core.test.mjs` (디렉터리 인자는 Node 24에서 실패).
- `build.py`는 실행 금지(실데이터 수집은 컨트롤러가 돌린다). `data/`·`docs/`는 건드리지 않는다.
- 커밋은 `-m "제목" -m "Co-Authored-By: <자기 하네스가 지정한 트레일러>"`.
- 콘텐츠 파일 2개는 컨트롤러가 이미 작성해 두었다: `content/company_ko.json`(종목별 한국어 한 줄 설명 165개), `content/industry_ko.json`(섹터·산업 한국어 표기).

---

### Task P1: 종목 정보 수집 확장과 설명 조립 (Python)

**Files:**
- Modify: `radar/config.py`, `radar/prices.py`, `build.py`, `tests/test_prices.py`
- Create: `radar/company.py`, `tests/test_company.py`
- Delete: `data/analyst.json` (info.json이 대체. `git rm data/analyst.json`)

**Interfaces:**
- Produces: `prices.yahoo_info(tickers, cache_path, today, max_age=7, limit=250, ticker_cls=None, sleep, log) -> dict` (캐시 전체를 반환; 항목 = `{mean, median, n, rec, sector, industry, summary, d}`); `company.load_ko(path)->dict`, `company.load_industry(path)->(sector_map, industry_map)`, `company.describe(tk, info, ko, sec_ko, ind_ko)->{ko, sec, ind, en}|None`.
- Consumes: `config.INFO_FILE`, `config.COMPANY_KO`, `config.INDUSTRY_KO`.

- [ ] **Step 1: 설정 상수** — `radar/config.py`에서 `ANALYST_FILE` 줄을 지우고 아래 3줄로 바꾼다.

```python
INFO_FILE = DATA / "info.json"                   # 야후 종목 정보(목표가·섹터·산업·사업요약)
COMPANY_KO = ROOT / "content" / "company_ko.json"
INDUSTRY_KO = ROOT / "content" / "industry_ko.json"
```

- [ ] **Step 2: 테스트 먼저** — `tests/test_prices.py`의 `test_analyst_targets_uses_7day_cache`를 아래로 교체(import도 `analyst_targets` → `yahoo_info`).

```python
def test_yahoo_info_caches_profile_and_targets(tmp_path):
    class T:
        n = 0

        def __init__(self, t):
            T.n += 1
            self.info = {"targetMeanPrice": 80.0, "targetMedianPrice": 75.0, "numberOfAnalystOpinions": 13,
                         "recommendationKey": "hold", "sector": "Technology", "industry": "Semiconductors",
                         "longBusinessSummary": "Acme designs chips. It also sells software."}

    cp, today = tmp_path / "info.json", dt.date(2026, 9, 22)
    got = yahoo_info(["ACME"], cp, today, ticker_cls=T, sleep=lambda s: None)
    assert got["ACME"]["mean"] == 80.0 and got["ACME"]["sector"] == "Technology"
    assert got["ACME"]["industry"] == "Semiconductors" and got["ACME"]["summary"].startswith("Acme designs chips.")
    assert T.n == 1
    yahoo_info(["ACME"], cp, today + dt.timedelta(days=3), ticker_cls=T, sleep=lambda s: None)
    assert T.n == 1                                      # 7일 이내는 캐시 사용
    yahoo_info(["ACME"], cp, today + dt.timedelta(days=9), ticker_cls=T, sleep=lambda s: None)
    assert T.n == 2                                      # 만료되면 다시 받는다
    assert yahoo_info(["ACME"], cp, today + dt.timedelta(days=9), max_age=180, ticker_cls=T, sleep=lambda s: None)["ACME"]["d"]
```

`tests/test_company.py` (새 파일):

```python
import json

from radar.company import describe, load_industry, load_ko


def test_load_ko_drops_note_keys(tmp_path):
    p = tmp_path / "ko.json"
    p.write_text(json.dumps({"_note": "설명", "AAPL": "아이폰 회사"}), encoding="utf-8")
    assert load_ko(p) == {"AAPL": "아이폰 회사"}


def test_load_industry_returns_both_maps(tmp_path):
    p = tmp_path / "ind.json"
    p.write_text(json.dumps({"sector": {"Technology": "기술"}, "industry": {"Semiconductors": "반도체"}}), encoding="utf-8")
    sec, ind = load_industry(p)
    assert sec["Technology"] == "기술" and ind["Semiconductors"] == "반도체"


def test_describe_prefers_korean_line_and_falls_back_to_sector():
    info = {"sector": "Technology", "industry": "Semiconductors",
            "summary": "Acme Inc. designs chips. It also sells software for fabs."}
    sec_ko, ind_ko = {"Technology": "기술"}, {"Semiconductors": "반도체"}
    a = describe("ACME", info, {"ACME": "칩 설계 회사"}, sec_ko, ind_ko)
    assert a == {"ko": "칩 설계 회사", "sec": "기술", "ind": "반도체", "en": "Acme Inc. designs chips."}
    b = describe("OTHER", info, {}, sec_ko, ind_ko)
    assert b["ko"] is None and b["sec"] == "기술" and b["ind"] == "반도체"
    assert describe("X", {"sector": "Unmapped", "industry": None, "summary": ""}, {}, sec_ko, ind_ko) == {
        "ko": None, "sec": "Unmapped", "ind": None, "en": None}
    assert describe("X", None, {}, sec_ko, ind_ko) is None
```

- [ ] **Step 3: 실패 확인** — `~/.venvs/13f/bin/python -m pytest -q tests/test_company.py tests/test_prices.py` → 실제 실패 출력을 보고서에 붙인다.

- [ ] **Step 4: 구현**

`radar/prices.py` — `analyst_targets`를 아래 `yahoo_info`로 교체(같은 위치, 이름만 바뀌는 게 아니라 필드가 늘어난다).

```python
def yahoo_info(tickers, cache_path, today, max_age=7, limit=250, ticker_cls=None, sleep=time.sleep, log=print):
    """야후 종목 정보(목표가·섹터·산업·사업요약)를 캐시에 채우고 캐시 전체를 반환.
    max_age일보다 오래된 항목만 다시 받는다(실행당 limit개, 연속 5회 실패 시 중단)."""
    ticker_cls = ticker_cls or _yf().Ticker
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    def fresh(e):
        return bool(e) and (today - dt.date.fromisoformat(e["d"])).days < max_age

    todo = [t for t in sorted(set(tickers)) if not fresh(cache.get(t))][:limit]
    fails = 0
    for t in todo:
        try:
            info = ticker_cls(t).info or {}
            cache[t] = {"mean": info.get("targetMeanPrice"), "median": info.get("targetMedianPrice"),
                        "n": info.get("numberOfAnalystOpinions"), "rec": info.get("recommendationKey"),
                        "sector": info.get("sector"), "industry": info.get("industry"),
                        "summary": (info.get("longBusinessSummary") or "").strip()[:400],
                        "d": today.isoformat()}
            fails = 0
        except Exception as e:
            fails += 1
            log(f"종목 정보 실패 {t}: {e}")
            if fails >= 5:
                log("종목 정보: 연속 실패로 중단")
                break
        sleep(0.4)
    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return cache
```

`radar/company.py` (새 파일):

```python
"""종목 설명: 한국어 한 줄 설명(content/company_ko.json)과 야후 섹터·산업의 한국어 표기."""
import json

from .config import COMPANY_KO, INDUSTRY_KO


def load_ko(path=COMPANY_KO):
    d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {k: v for k, v in d.items() if not k.startswith("_")}


def load_industry(path=INDUSTRY_KO):
    d = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return d.get("sector", {}), d.get("industry", {})


def describe(tk, info, ko, sec_ko, ind_ko):
    """{ko: 한국어 한 줄|None, sec: 섹터, ind: 산업, en: 영문 요약 첫 문장}. 아무 정보도 없으면 None."""
    if info is None and tk not in ko:
        return None
    info = info or {}
    en = (info.get("summary") or "").strip()
    if en:
        cut = en.find(". ")
        en = (en[:cut + 1] if 0 < cut < 200 else en[:200]).strip()
    sec, ind = info.get("sector"), info.get("industry")
    out = {"ko": ko.get(tk), "sec": sec_ko.get(sec, sec), "ind": ind_ko.get(ind, ind), "en": en or None}
    return out if any(out.values()) else None
```

`build.py` — import에 `from radar import company` 를 더하고(알파벳 순서상 `from radar import config as C` 앞), 애널리스트 블록을 통째로 교체한다.

```python
    cand, rest = set(), set()
    for P in show.values():
        for s in P["stocks"]:
            if s.get("tk"):
                (cand if is_candidate(s, tier) else rest).add(yf_sym(s["tk"]))
    prices.yahoo_info(sorted(cand), C.INFO_FILE, today, max_age=7, limit=250, log=log)        # 목표가 최신화
    info = prices.yahoo_info(sorted(rest - cand), C.INFO_FILE, today, max_age=180, limit=400, log=log)  # 설명 채우기
    ko, (sec_ko, ind_ko) = company.load_ko(), company.load_industry()
    for P in show.values():
        for s in P["stocks"]:
            t = yf_sym(s["tk"]) if s.get("tk") else None
            i = info.get(t) if t else None
            s["an"] = {k: i[k] for k in ("mean", "median", "n", "rec", "d")} if i and i.get("mean") else None
            s["biz"] = company.describe(t, i, ko, sec_ko, ind_ko) if t else None
```

- [ ] **Step 5: 통과 확인** — `~/.venvs/13f/bin/python -m pytest -q` (전체) → 실제 출력 붙이기. `node --test tests/js/core.test.mjs` 도 그대로 9 pass 인지 확인.

- [ ] **Step 6: 커밋**
```bash
git rm -q data/analyst.json
git add radar/config.py radar/prices.py radar/company.py build.py tests/test_prices.py tests/test_company.py
git commit -m "Collect sector, industry and business summary; describe companies in Korean" -m "Co-Authored-By: ..."
```

---

### Task P2: 추천 점수와 Top 5, 회사 설명 표시 (template.html)

**Files:**
- Modify: `template.html`, `tests/js/core.test.mjs`

**Interfaces:**
- Consumes: 종목의 `px{last,prem,hi52,el,krw}`, `an{mean}`, `biz{ko,sec,ind,en}`, 그리고 `r.n`/`r.ancN`(같은 분기 매수자 수·그중 앵커 수), 최근 90일 수시 매수 여부.
- Produces: `CORE.recScore(r, recentBuy) -> {score, cons, price, fresh, parts}`.

- [ ] **Step 1: Node 테스트 먼저** — `tests/js/core.test.mjs` 끝에 추가.

```js
test('recScore: 합의 40 + 가격 40 + 신선도 20, 없는 항목은 평균에서 제외', () => {
  const mk = (n, ancN, px, an) => ({n, ancN, s: {px, an}});
  const full = CORE.recScore(mk(5, 2, {last: 80, prem: -0.20, hi52: 133.33, el: 0, krw: 1}, {mean: 112}), true);
  assert.equal(full.cons, 40);                 // min(30, 6*5)=30 + min(10, 5*2)=10
  assert.equal(full.price, 40);                // 세 항목 모두 만점
  assert.equal(full.fresh, 20);                // 수시 매수 10 + 경과 0일 10
  assert.equal(full.score, 100);
  const none = CORE.recScore(mk(2, 0, null, null), false);
  assert.deepEqual([none.cons, none.price, none.fresh, none.parts], [12, 0, 0, 0]);
  const half = CORE.recScore(mk(2, 0, {last: 100, prem: 0.0, hi52: 100, el: 126, krw: 1}, null), false);
  assert.equal(half.parts, 2);                 // 목표가 없음 → 두 항목 평균
  assert.equal(half.price, 10);                // (0.5 + 0) / 2 * 40
  assert.equal(half.fresh, 0);
});
```

- [ ] **Step 2: 실패 확인** — `node --test tests/js/core.test.mjs` → `CORE.recScore is not a function` 류 실패 출력을 붙인다.

- [ ] **Step 3: CORE에 recScore 추가** — `/*CORE-BEGIN*/` 블록 안, `band` 정의 바로 뒤에 넣고 return 객체에도 `recScore`를 추가한다.

```js
  const clamp01 = x => Math.max(0, Math.min(1, x));
  // 추천 점수: 합의 강도 40 + 가격 매력도 40 + 신선도 20 (계산식은 화면에 공개한다)
  function recScore(r, recentBuy){
    const px = r.s.px, an = r.s.an;
    const cons = Math.min(30, 6 * r.n) + Math.min(10, 5 * r.ancN);
    const parts = [];
    if(px && px.prem != null) parts.push(clamp01((0.20 - px.prem) / 0.40));              // 추정 매입가 대비 할인
    if(px && px.hi52 && px.last) parts.push(clamp01((px.hi52 / px.last - 1) / 0.40));     // 52주 고점 대비 낙폭
    if(an && an.mean && px && px.last) parts.push(clamp01((an.mean / px.last - 1) / 0.40)); // 애널리스트 상승여력
    const price = parts.length ? 40 * parts.reduce((t, x) => t + x, 0) / parts.length : 0;
    const fresh = (recentBuy ? 10 : 0) + (px ? 10 * clamp01((126 - px.el) / 105) : 0);
    return {score: Math.round(cons + price + fresh), cons: Math.round(cons), price: Math.round(price),
            fresh: Math.round(fresh), parts: parts.length};
  }
```

- [ ] **Step 4: UI 반영** — `template.html`의 UI 코드(CORE 바깥)에 아래를 적용한다.

1. 기본 정렬을 추천 점수로: `let S = {...}` 의 `sort:'n'` → `sort:'rec'`.
2. 정렬 드롭다운에 첫 항목 추가: `<select id="sort">` 안 맨 앞에 `<option value="rec">추천 점수</option>`.
3. `compute()` 안에서 `r.X=stockExp(r);` 다음 줄에 추가:
   `r.rec = CORE.recScore(r, (recentByTk[normTk(s.tk)]||[]).some(isBuyFiling));`
4. 정렬 목록에 추가: `sorters` 객체에 `rec:(a,b)=>b.rec.score-a.rec.score||base(a,b),` 를 맨 앞에 넣는다.
5. 시그널 행의 점수 칸(`<div class="score">`)에 추천 점수 한 줄 추가 — 기존 두 `<small>` 다음에:
   `<small>추천 ${r.rec.score}점</small>`
6. 회사 설명 줄: `rowHTML`의 `<div class="nm">…</div>` 바로 다음에
   `${bizLine(s)}`
   그리고 헬퍼를 추가한다(파일 내 `const premTxt = …` 근처):
```js
const bizText = s => { const b = s.biz; if(!b) return ''; return b.ko || [b.sec, b.ind].filter(Boolean).join(' · '); };
const bizLine = s => { const t = bizText(s); return t ? `<div class="biz">${esc(t)}</div>` : ''; };
```
7. 상세 패널(`detailHTML`)의 맨 앞(`let h = s.tk ? …` 줄 앞)에 영문 요약을 넣는다:
```js
  const b = s.biz;
  let h = b && (b.ko || b.en) ? `<p class="cap">${esc(b.ko || '')}${b.ko && b.en ? '<br>' : ''}${esc(b.en || '')}</p>` : '';
  h += s.tk ? `<div class="links">…기존 내용 그대로…` : '';
```
   (기존 `let h = s.tk ? … : '';` 를 위 두 줄로 바꾸되 링크 문자열은 그대로 유지한다.)
8. Top 5 카드: `<p class="rule" id="rule"></p>` 바로 다음에 아래 마크업을 넣는다.
```html
  <section class="card" id="pickcard">
    <h2>지금 사기 좋은 순서 — Top 5 <span id="pickmeta"></span></h2>
    <div id="picks"></div>
    <div class="note" id="picknote"></div>
  </section>
```
9. 렌더 함수 추가(`renderList` 바로 앞에 두고, `renderList` 안에서 `const rows = compute();` 다음 줄에 `renderPicks(rows);` 호출):
```js
function renderPicks(rows){
  const el = document.getElementById('picks'), top = rows.slice(0, 5);
  document.getElementById('pickmeta').textContent = rows.length ? `${S.period} · 조건 충족 ${rows.length}개 중` : '';
  el.innerHTML = top.length ? top.map((r, i) => {
    const s = r.s, px = s.px, why = [];
    why.push(`동시 매수 ${r.n}명${r.ancN ? `(레전드 ${r.ancN}명)` : ''}`);
    if(px && px.prem != null) why.push(px.prem <= 0 ? `추정 매입가보다 ${(-px.prem * 100).toFixed(1)}% 싸게` : `추정 매입가보다 ${(px.prem * 100).toFixed(1)}% 비싸게`);
    if(px && px.hi52) why.push(`52주 고점 대비 ${fp(px.last / px.hi52 - 1)}`);
    if(s.an && s.an.mean && px) why.push(`목표가 ${fp(s.an.mean / px.last - 1)}`);
    if((recentByTk[normTk(s.tk)] || []).some(isBuyFiling)) why.push('최근 수시 매수');
    return `<div class="pick"><div class="rank">${i + 1}</div>
      <div class="pmain"><div class="nm">${esc(s.tk || '—')} <span class="mut">${esc(s.name)}</span></div>
        ${bizLine(s)}<div class="why">${why.map(w => `<span>${esc(w)}</span>`).join('')}</div></div>
      <div class="pscore"><b>${r.rec.score}</b><small>합의 ${r.rec.cons} · 가격 ${r.rec.price} · 신선 ${r.rec.fresh}</small>
        <div class="sbar"><i class="c1" style="width:${r.rec.cons}%"></i><i class="c2" style="width:${r.rec.price}%"></i><i class="c3" style="width:${r.rec.fresh}%"></i></div></div>
      <div class="ppx">${px ? fmtPx(px.last) : '–'}${px && px.krw ? `<small>${fmtKRW(px.krw)}</small>` : ''}</div></div>`;
  }).join('') : '<div class="empty">조건에 맞는 종목이 없습니다.</div>';
  document.getElementById('picknote').innerHTML = '<p><b>추천 점수 100점</b> = 합의 강도 40(같은 분기 매수 인원 6점씩·최대 30, 레전드군 매수자 5점씩·최대 10) + 가격 매력도 40(추정 매입가 대비 할인, 52주 고점 대비 낙폭, 애널리스트 목표가 상승여력 — 자료가 있는 항목만 평균) + 신선도 20(최근 90일 수시 매수 10, 공시 후 경과일 0일 10점→126일 0점). 위 조건(앵커·인원수·기간)을 바꾸면 순서도 바뀝니다. <b>기계적 계산이며 투자 권유가 아닙니다.</b></p>';
}
```
10. CSS 추가(기존 `.tiles` 규칙 근처):
```css
.pick{display:grid;grid-template-columns:28px minmax(0,1fr) 190px 110px;gap:10px 14px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line-2)}
.pick:last-child{border-bottom:0}
.pick .rank{font:600 15px var(--mono);color:var(--ink-3);text-align:center}
.pick .nm{font-weight:600;overflow-wrap:anywhere}
.pick .biz{font-size:12.5px;color:var(--ink-2);margin-top:2px}
.pick .why{display:flex;flex-wrap:wrap;gap:4px 8px;margin-top:5px;font:11.5px var(--mono);color:var(--ink-3)}
.pick .why span{background:var(--line-2);border-radius:4px;padding:1px 6px}
.pick .pscore{text-align:right}
.pick .pscore b{font:600 20px var(--sans)}
.pick .pscore small{display:block;font:400 11px var(--mono);color:var(--ink-3)}
.pick .sbar{display:flex;gap:2px;height:4px;margin-top:4px;border-radius:2px;overflow:hidden;background:var(--line-2)}
.pick .sbar i{display:block;height:100%}
.pick .sbar .c1{background:var(--accent)} .pick .sbar .c2{background:var(--series-a)} .pick .sbar .c3{background:var(--series-b)}
.pick .ppx{text-align:right;font:600 14px var(--mono)}
.pick .ppx small{display:block;font:400 11px var(--mono);color:var(--ink-3)}
.biz{font-size:12.5px;color:var(--ink-2);margin-top:2px}
@media (max-width:560px){.pick{grid-template-columns:24px minmax(0,1fr);}.pick .pscore,.pick .ppx{grid-column:2;text-align:left}.pick .sbar{max-width:200px}}
```
11. "읽는 법" 카드에 한 줄 추가(기존 `<p><b>수시 매수 배지</b>…` 앞):
```html
          <p><b>추천 점수</b>는 합의 강도·가격 매력도·신선도를 공개된 식으로 더한 기계적 점수입니다(카드 아래 계산식 참고). 좋은 회사를 고르는 안목이 아니라, 지금 조건에서 눈여겨볼 순서를 정리한 것입니다.</p>
```

- [ ] **Step 5: 통과 확인** — `node --test tests/js/core.test.mjs` → 10 pass. `~/.venvs/13f/bin/python -m pytest -q` → 변화 없음.

- [ ] **Step 6: 커밋**
```bash
git add template.html tests/js/core.test.mjs
git commit -m "Rank signals with a disclosed score and show what each company does" -m "Co-Authored-By: ..."
```
