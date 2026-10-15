"""Suh & Sohn (2015, IMDS 115(4):718-739) 4.2절 텍스트 군집분석을 사업보고서에 적용.

  1) 텍스트 파싱: 명사·명사구만 추출 (Kiwi 형태소 분석)
  2) 가중치: 지역가중 log2(tf+1) x 전역가중 entropy  -> 가중 문서-용어 행렬 (n x p)
  3) SVD: 최대 25차원
  4) EM 군집(가우시안 혼합): 최대 20개, 군집 수는 BIC로 선택
  5) 군집 설명어: 군집 내 빈도 상위 2m개 용어를 이항확률로 재정렬해 상위 m개
  6) 기간별 군집 비중(%) = 해당 기간 문서 중 그 군집 문서 비율 -> 시계열 추세

  python cluster.py --raw raw --out out [--mode pooled|per-period] [--bin 2]

mode
  pooled      전 기간 문서를 한 번에 군집화(군집 정의가 기간 간 동일). 기본값.
  per-period  논문처럼 기간별로 따로 군집화한 뒤, 유사한 군집을 합친다. 논문은 수작업으로
              합쳤지만 여기서는 군집 중심(용어공간) 코사인 유사도 기반 계층적 병합으로 자동화.
"""
import argparse, json, os, re
from collections import Counter

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import binom
from sklearn.cluster import AgglomerativeClustering
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import normalize

NOUN = {"NNG", "NNP", "SL"}            # 일반·고유명사, 영문(IFRS, GA 등)
GLUE = {"XSN"}                        # 율·료·성 등 명사파생 접미사는 앞 명사에 붙인다
# 사업보고서 서식어·범용어. 엔트로피 가중으로도 줄지만 명시적으로 뺀다.
STOP = set("""당사 회사 경우 기준 해당 사항 관련 내용 기간 연도 사업연도 전기 당기 전년 단위 백만원 억원 천원 원 년 월 일
기재 참조 주 이하 이상 현재 등 및 바 수 것 때 중 위 외 각 별 개 건 명 말 기말 기초 구분 합계 소계 비율 비중 증감 대비
보고서 공시 작성 표 다음 아래 상기 주석 부분 영업 사업""".split())


class Tokenizer:
    """명사와 명사구(연속 명사 결합)를 용어로 쓴다: '자동차 보험 손해 율' -> 자동차, 보험, 손해, 자동차보험손해율."""

    def __init__(self, stop=STOP, user_words=()):
        from kiwipiepy import Kiwi
        self.kiwi = Kiwi()
        for w in user_words:
            self.kiwi.add_user_word(w, "NNP")
        self.stop = stop

    def __call__(self, text):
        terms, run = [], []

        def flush():
            if len(run) > 1:
                g = "".join(run)
                if g not in self.stop:
                    terms.append(g)
            terms.extend(p for p in run if len(p) >= 2 and p not in self.stop and not re.search(r"\d", p))
            run.clear()

        for t in self.kiwi.tokenize(text):
            if t.tag in NOUN and t.form in self.stop:   # 서식어는 명사구를 끊는다
                if run:
                    flush()
            elif t.tag in NOUN:
                run.append(t.form.upper() if t.tag == "SL" else t.form)
            elif t.tag in GLUE and run:
                run[-1] += t.form
            else:
                if run:
                    flush()
        if run:
            flush()
        return terms


def log_entropy(counts):
    """counts: 문서x용어 희소행렬. SAS Text Miner의 log local x entropy global."""
    X = sparse.csr_matrix(counts, dtype=float)
    n = X.shape[0]
    gf = np.asarray(X.sum(axis=0)).ravel()
    C = X.tocoo()
    p = C.data / gf[C.col]
    ent = np.zeros(X.shape[1])
    np.add.at(ent, C.col, p * np.log2(p))
    g = 1 + ent / np.log2(n) if n > 1 else np.ones(X.shape[1])
    L = X.copy()
    L.data = np.log2(L.data + 1)
    return sparse.csr_matrix(L.multiply(g)), g


def em_cluster(W, max_dim=25, max_k=20, seed=0):
    n, p = W.shape
    d = max(2, min(max_dim, n - 1, p - 1))
    Z = TruncatedSVD(d, random_state=seed).fit_transform(W)
    Z = normalize(Z)
    best = None
    for k in range(2, min(max_k, n // 5) + 1):
        gm = GaussianMixture(k, covariance_type="diag", n_init=3, random_state=seed, reg_covar=1e-4).fit(Z)
        b = gm.bic(Z)
        if best is None or b < best[0]:
            best = (b, k, gm)
    _, k, gm = best
    return gm.predict(Z), k, d


def descriptive_terms(counts, mask, vocab, m=8, base_mask=None):
    """군집(mask) 내 문서빈도 상위 2m 용어를 이항 꼬리확률 P(X>=k | n_c, p_base) 오름차순으로 m개."""
    B = (counts > 0).astype(int)
    base = B if base_mask is None else B[base_mask]
    p0 = np.asarray(base.sum(axis=0)).ravel() / max(base.shape[0], 1)
    sub = B[mask]
    nc = sub.shape[0]
    k = np.asarray(sub.sum(axis=0)).ravel()
    cand = np.argsort(-k)[: 2 * m]
    cand = cand[(k[cand] > 0) & (k[cand] / max(nc, 1) > p0[cand])]   # 기준보다 더 자주 나오는 용어만
    pv = binom.sf(k[cand] - 1, nc, np.clip(p0[cand], 1e-9, 1))
    order = cand[np.argsort(pv, kind="stable")][:m]
    return [vocab[i] for i in order]


def period_of(year, start, width):
    lo = start + (year - start) // width * width
    return str(lo) if width == 1 else f"{lo}-{lo + width - 1}"


def run(docs, mode="pooled", width=2, m=8, min_df=3, max_k=20, seed=0, tokenizer=None, merge_sim=0.5):
    tok = tokenizer or Tokenizer()
    years = np.array([y for y, _ in docs])
    texts = [t for _, t in docs]
    start = years.min()
    periods = np.array([period_of(int(y), int(start), width) for y in years], dtype=object)
    cv = CountVectorizer(analyzer=tok, min_df=min_df)
    counts = cv.fit_transform(texts)
    vocab = cv.get_feature_names_out()
    keep = np.asarray(counts.sum(axis=1)).ravel() > 0
    counts, years, periods, texts = counts[keep], years[keep], periods[keep], [t for t, k in zip(texts, keep) if k]
    plist = sorted(set(periods.tolist()))
    info = {"n_docs": int(counts.shape[0]), "n_terms": int(counts.shape[1]), "periods": plist}

    if mode == "pooled":
        W, _ = log_entropy(counts)
        labels, k, d = em_cluster(W, max_k=max_k, seed=seed)
        info.update(k=k, svd_dim=d)
    else:
        # 기간 간 군집 비교는 전 기간 엔트로피 가중 공간에서 한다 — 서식어가 유사도를 부풀리지 않게
        Wg, _ = log_entropy(counts)
        local = np.empty(len(texts), dtype=object)
        cents, keys = [], []
        info["per_period"] = {}
        for p in plist:
            idx = np.where(periods == p)[0]
            W, _ = log_entropy(counts[idx])
            lab, k, d = em_cluster(W, max_k=max_k, seed=seed)
            info["per_period"][p] = {"k": k, "svd_dim": d, "n_docs": len(idx)}
            for c in range(k):
                sel = idx[lab == c]
                if len(sel) == 0:
                    continue
                local[sel] = f"{p}#{c}"
                cents.append(np.asarray(Wg[sel].mean(axis=0)).ravel()); keys.append(f"{p}#{c}")
        C = normalize(np.vstack(cents))
        field = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                        distance_threshold=1 - merge_sim).fit_predict(C)
        fmap = dict(zip(keys, field))
        labels = np.array([fmap[x] for x in local])
        info.update(k=int(len(set(field))), merge_sim=merge_sim)

    # 군집 번호를 전체 규모 순으로 재부여
    order = [c for c, _ in Counter(labels).most_common()]
    remap = {c: i for i, c in enumerate(order)}
    labels = np.array([remap[c] for c in labels])

    clusters = []
    for c in range(len(order)):
        mask = labels == c
        clusters.append({"cluster": c, "n_docs": int(mask.sum()), "share_total_%": round(100 * mask.mean(), 2),
                         "terms": ", ".join(descriptive_terms(counts, mask, vocab, m))})
    clusters = pd.DataFrame(clusters)

    tab = pd.crosstab(labels, periods, normalize="columns").reindex(columns=plist) * 100
    tab.index.name, tab.columns.name = "cluster", "period"

    notes = {}   # 논문 Table II의 Notes: 해당 기간에 그 군집을 특징짓는 용어(군집 전체 대비)
    for c in range(len(order)):
        cm = labels == c
        for p in plist:
            mask = cm & (periods == p)
            if mask.sum() >= 3:
                notes[(c, p)] = ", ".join(descriptive_terms(counts, mask, vocab, max(3, m // 2), base_mask=cm))
    assign = pd.DataFrame({"year": years, "period": periods, "cluster": labels, "text": texts})
    return info, clusters, tab.round(2), notes, assign


def write_report(out, info, clusters, tab, notes, mode):
    os.makedirs(out, exist_ok=True)
    clusters.to_csv(f"{out}/clusters_{mode}.csv", index=False, encoding="utf-8-sig")
    tab.to_csv(f"{out}/share_by_period_{mode}.csv", encoding="utf-8-sig")
    with open(f"{out}/info_{mode}.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1, default=int)
    lines = [f"# 텍스트 군집분석 결과 ({mode})", "",
             f"문서(문단) {info['n_docs']}개, 용어 {info['n_terms']}개, 군집 {info['k']}개", "",
             "## 군집 설명어", "", "| 군집 | 문서수 | 비중(%) | 설명어 |", "|---|---|---|---|"]
    lines += [f"| C{r.cluster} | {r.n_docs} | {r['share_total_%']} | {r.terms} |" for _, r in clusters.iterrows()]
    lines += ["", "## 기간별 비중(%)과 특징어 (Suh & Sohn 2015, Table II 형식)", "",
              "| 군집 | " + " | ".join(tab.columns) + " |", "|---" * (len(tab.columns) + 1) + "|"]
    for c, row in tab.iterrows():
        cells = [f"{v:.2f}<br>{notes.get((c, p), '')}" for p, v in row.items()]
        lines.append(f"| C{c} | " + " | ".join(cells) + " |")
    with open(f"{out}/report_{mode}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        have = {f.name for f in font_manager.fontManager.ttflist}
        kr = [f for f in ("NanumGothic", "Noto Sans CJK KR", "Malgun Gothic", "AppleGothic") if f in have]
        if kr:
            plt.rcParams["font.family"] = kr[0]
        else:
            print("한글 폰트가 없어 히트맵 라벨이 깨질 수 있다 (NanumGothic 설치 권장)")
        fig, ax = plt.subplots(figsize=(1.2 * len(tab.columns) + 3, 0.45 * len(tab) + 1.5))
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning)
        im = ax.imshow(tab.values, cmap="Blues", aspect="auto")
        ax.set_xticks(range(len(tab.columns)), tab.columns)
        ax.set_yticks(range(len(tab)), [f"C{c}: {t[:30]}" for c, t in zip(clusters.cluster, clusters.terms)])
        for i in range(tab.shape[0]):
            for j in range(tab.shape[1]):
                ax.text(j, i, f"{tab.values[i, j]:.1f}", ha="center", va="center", fontsize=8)
        fig.colorbar(im, label="share (%)"); fig.tight_layout()
        fig.savefig(f"{out}/share_heatmap_{mode}.png", dpi=150)
    except Exception as e:  # 그림은 부가 산출물
        print("heatmap skipped:", e)


def main():
    from extract import load_corpus
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="out")
    ap.add_argument("--mode", choices=["pooled", "per-period"], default="pooled")
    ap.add_argument("--bin", type=int, default=2, help="기간 폭(년). 논문은 2년")
    ap.add_argument("--m", type=int, default=8, help="군집별 설명어 수")
    ap.add_argument("--min-df", type=int, default=3)
    ap.add_argument("--max-k", type=int, default=20)
    ap.add_argument("--merge-sim", type=float, default=0.5)
    ap.add_argument("--keep-tables", action="store_true")
    ap.add_argument("--whole", action="store_true", help="'사업의 내용'만이 아니라 보고서 전체 사용")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    docs = load_corpus(a.raw, a.keep_tables, a.whole)
    print("문단 수(연도별):", dict(sorted(Counter(y for y, _ in docs).items())))
    info, clusters, tab, notes, assign = run(docs, a.mode, a.bin, a.m, a.min_df, a.max_k, a.seed, merge_sim=a.merge_sim)
    write_report(a.out, info, clusters, tab, notes, a.mode)
    assign.to_csv(f"{a.out}/assignments_{a.mode}.csv", index=False, encoding="utf-8-sig")
    print(clusters.to_string(index=False)); print(tab.to_string())


if __name__ == "__main__":
    main()
