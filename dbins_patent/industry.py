"""A안: 국내 보험산업 특허에 Suh & Sohn(2015) 프레임워크를 적용하고 DB손해보험의 위치를 분석한다.

사용법:
    python industry.py <KIPRIS_추출파일(보험사 전체).xlsx|csv> --asof 2026-10-14 [--out out_industry] [--k 0]

원 논문 절차와의 대응:
  4.1 데이터 선정   → 출원일 기준, 상태 무관(거절·취하 포함) 전 출원
  4.2 텍스트 군집   → 명사 추출 → log(tf)×entropy 가중 → SVD(≤25차원) → EM(가우시안 혼합, k≤20)
                      → 군집별 대표어는 이항확률(binomial) 순으로 선정
  4.3 연관규칙      → 관심 군집별 상위 10개 IPC(메인그룹)로 한정한 2-항목 규칙, support/confidence/lift 기준
  (추가) 포지셔닝  → 기업×군집 RTA(현시기술우위), 진입 시점, 융합 지표
"""
import argparse
import itertools
import re
from collections import Counter
from pathlib import Path

import koreanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import numpy as np
import pandas as pd
from scipy.stats import binom
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics import adjusted_rand_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import normalize

from analyze import DISCLOSURE_LAG_MONTHS, IPC_RE, PERIODS, fig_heat, load, match
from taxonomy import TECHNOLOGY, VALUE_CHAIN

# 출원인 표기 → 표준 기업명. 사명 변경 이력은 기억에 근거한 것이므로 KIPRIS 출원인 목록으로 대조할 것.
FIRMS = {
    "DB손보": ["DB손해보험", "디비손해보험", "동부화재"],
    "삼성화재": ["삼성화재"],
    "현대해상": ["현대해상"],
    "KB손보": ["KB손해보험", "케이비손해보험", "LIG손해보험", "엘아이지손해보험"],
    "메리츠화재": ["메리츠화재"],
    "한화손보": ["한화손해보험"],
    "롯데손보": ["롯데손해보험"],
    "흥국화재": ["흥국화재"],
    "삼성생명": ["삼성생명"],
    "한화생명": ["한화생명", "대한생명"],
    "교보생명": ["교보생명"],
    "신한라이프": ["신한라이프", "신한생명", "오렌지라이프"],
    "NH농협": ["농협생명", "농협손해보험"],
}
FOCAL = "DB손보"
SVD_DIM, MAX_K = 25, 20                      # 원 논문 설정값
MIN_SUPPORT, MIN_CONF, MIN_LIFT = 0.02, 0.2, 1.0  # 연관규칙 기준 — 실제 데이터 분포를 보고 조정
C_FOCAL, C_PEER = "#eb6834", "#b4b2a9"
STOP = {"시스템", "방법", "장치", "서버", "단말", "정보", "제공", "이용", "기반", "관련", "처리", "단계", "수행", "포함",
        "사용자", "데이터", "프로그램", "기록", "매체", "보험", "컴퓨터", "발명", "상기", "통해", "위해", "구성", "생성",
        "결정", "판단", "수신", "전송", "저장", "출력", "입력", "산출", "복수", "적어도", "하나"}


def firm_of(applicant):
    """출원인 문자열에서 대상 기업을 찾는다. 공동출원으로 2개사 이상이면 모두 반환."""
    s = str(applicant)
    return [f for f, names in FIRMS.items() if any(n in s for n in names)]


def tokenize(texts):
    from kiwipiepy import Kiwi
    kiwi = Kiwi()
    for w in ["인공지능", "블랙박스", "손해사정", "보험금", "언더라이팅", "텔레매틱스", "빅데이터", "챗봇", "과실비율",
              "블록체인", "웨어러블", "보험사기", "인수심사"]:
        kiwi.add_user_word(w, "NNG")
    return [[t.form for t in kiwi.tokenize(x) if t.tag in ("NNG", "NNP", "SL") and len(t.form) > 1
             and t.form not in STOP] for x in texts]


def log_entropy(tokens, min_df=3):
    """원 논문 4.2: 국소가중 log(1+tf), 전역가중 entropy(1 + Σ p log p / log n)."""
    vocab = sorted(w for w, c in Counter(w for d in tokens for w in set(d)).items() if c >= min_df)
    idx = {w: i for i, w in enumerate(vocab)}
    tf = np.zeros((len(tokens), len(vocab)))
    for i, d in enumerate(tokens):
        for w, c in Counter(d).items():
            if w in idx:
                tf[i, idx[w]] = c
    n = len(tokens)
    gf = tf.sum(axis=0)
    p = np.divide(tf, gf, out=np.zeros_like(tf), where=gf > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        plogp = np.where(p > 0, p * np.log(p), 0.0)
    g = 1 + plogp.sum(axis=0) / np.log(n)
    return np.log1p(tf) * g, vocab, tf


def cluster(X, k=0, seed=0):
    """SVD → EM. k=0이면 BIC 최소인 k를 4..MAX_K에서 선택(원 논문은 최대 20개만 지정)."""
    dim = min(SVD_DIM, X.shape[1] - 1, X.shape[0] - 1)
    Z = normalize(TruncatedSVD(dim, random_state=seed).fit_transform(X))
    ks = [k] if k else range(4, min(MAX_K, len(Z) // 15) + 1)
    fits = [GaussianMixture(kk, covariance_type="diag", n_init=5, random_state=seed).fit(Z) for kk in ks]
    best = min(fits, key=lambda m: m.bic(Z))
    bic = pd.Series({m.n_components: m.bic(Z) for m in fits}, name="BIC")
    return best.predict(Z), best.n_components, bic


def descriptive_terms(labels, tf, vocab, m=5):
    """원 논문 4.2: 군집 내 상위 2m 빈출어 중 이항확률 P(X≥k | n_c, p_전체)가 작은 순으로 m개."""
    present = tf > 0
    p_all = present.mean(axis=0)
    out = {}
    for c in sorted(set(labels)):
        mask = labels == c
        k = present[mask].sum(axis=0)
        enriched = (k > 0) & (k / mask.sum() > p_all)  # 군집 밖보다 군집 안에서 더 흔한 단어만 후보
        cand = [i for i in np.argsort(-k)[: 2 * m] if enriched[i]] or list(np.argsort(-k)[:m])
        cand = np.array(cand)
        pv = binom.sf(k[cand] - 1, mask.sum(), p_all[cand])
        out[c] = [vocab[i] for i in cand[np.argsort(pv)][:m]]
    return out


def assoc_rules(sub, top_items):
    """2-항목 규칙 A→B (A,B ∈ 관심 군집의 상위 10 IPC). 원 논문 식: conf=P(B|A), lift=P(A∩B)/(P(A)P(B))."""
    n = len(sub)
    if n == 0:
        return []
    sets = sub["ipc_groups"].map(set)
    cnt = {i: sets.map(lambda s: i in s).sum() for i in top_items}
    rows = []
    for a, b in itertools.permutations(top_items, 2):
        ab = sets.map(lambda s: a in s and b in s).sum()
        if ab == 0 or cnt[a] == 0:
            continue
        sup, conf = ab / n, ab / cnt[a]
        lift = sup / ((cnt[a] / n) * (cnt[b] / n))
        if sup >= MIN_SUPPORT and conf >= MIN_CONF and lift > MIN_LIFT:
            rows.append({"rule": f"{a} → {b}", "count": int(ab), "support": sup, "confidence": conf, "lift": lift})
    return rows


def rta(counts):
    """RTA_ij = (n_ij / n_i) / (n_.j / n_..). 1 초과면 해당 군집에 상대적 특화."""
    share_firm = counts.div(counts.sum(axis=1), axis=0)
    share_ind = counts.sum(axis=0) / counts.values.sum()
    return share_firm.div(share_ind, axis=1)


def fig_firm_bars(s, title, fname, out, fmt="{:.0f}"):
    s = s.sort_values()
    fig, ax = plt.subplots(figsize=(6.5, 0.35 * len(s) + 1))
    ax.barh(s.index, s.values, color=[C_FOCAL if i == FOCAL else C_PEER for i in s.index], height=0.6)
    for y, v in enumerate(s.values):
        ax.text(v, y, " " + fmt.format(v), va="center", fontsize=8)
    ax.set_title(title, loc="left", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    fig.savefig(out / fname, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--asof", required=True)
    ap.add_argument("--out", default="out_industry")
    ap.add_argument("--k", type=int, default=0, help="군집 수 고정(0이면 BIC로 선택)")
    ap.add_argument("--merge", help="군집 병합표 CSV(열: cluster,field). 원 논문처럼 유사 군집을 묶을 때 사용")
    ap.add_argument("--focus", type=int, default=4, help="연관규칙을 볼 관심 군집 수(비중 상위)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # ---- 4.1 데이터 선정
    df = load(a.input)
    df = df[df["year"].between(PERIODS[0][1], PERIODS[-1][2])].copy()
    df["firms"] = df["applicant"].map(firm_of)
    unmatched = df[df["firms"].map(len).eq(0)]["applicant"].value_counts()
    df = df[df["firms"].map(len).gt(0)].copy()
    df["period"] = df["year"].map(lambda y: next(p for p, s, e in PERIODS if s <= y <= e))
    df["ipc_groups"] = df["ipc"].astype(str).map(lambda s: sorted({f"{m[0]} {m[1]}" for m in IPC_RE.findall(s)}))
    df["ipc_subclasses"] = df["ipc_groups"].map(lambda g: sorted({x.split()[0] for x in g}))
    df["text"] = (df["title"].astype(str) + " " + df["abstract"].astype(str)).str.replace(r"\s+", " ", regex=True)
    cutoff = pd.Timestamp(a.asof) - pd.DateOffset(months=DISCLOSURE_LAG_MONTHS)
    df = df.reset_index(drop=True)

    # ---- 4.2 텍스트 군집
    tokens = tokenize(df["text"])
    X, vocab, tf = log_entropy(tokens)
    labels, k, bic = cluster(X, a.k)
    # 안정성: 다른 seed로 재군집했을 때의 조정 랜드지수(ARI). 0.6 미만이면 군집 해석에 주의
    ari = [adjusted_rand_score(labels, cluster(X, k, seed=s)[0]) for s in (1, 2)]
    terms = descriptive_terms(labels, tf, vocab)
    df["cluster"] = [f"C{c:02d} " + "·".join(terms[c][:3]) for c in labels]
    if a.merge:  # 병합 전 군집표는 아래 01 시트에 남고, 이후 분석은 병합된 분야 기준
        mp = pd.read_csv(a.merge).set_index("cluster")["field"].to_dict()
        df["cluster_raw"] = df["cluster"]
        df["cluster"] = df["cluster"].map(lambda c: mp.get(c, c))
    cl_names = sorted(df["cluster"].unique())

    raw_terms = pd.Series({f"C{c:02d} " + "·".join(t[:3]): ", ".join(t) for c, t in terms.items()},
                          name="대표어(이항확률순)")
    by_period = (df.groupby(["period", "cluster"]).size().unstack(0, fill_value=0)
                 .reindex(columns=[p for p, *_ in PERIODS], fill_value=0))
    share = by_period.div(by_period.sum(axis=0), axis=1) * 100          # 원 논문 Table II 대응
    cluster_tbl = by_period.join(share.round(1).add_suffix(" (%)"))
    if not a.merge:
        cluster_tbl = raw_terms.to_frame().join(cluster_tbl)

    # ---- 4.3 연관규칙: 전 기간 비중 상위 군집(관심분야)마다, 상위 10 IPC 사이 규칙을 기간별로
    focus = df["cluster"].value_counts().index[: a.focus]
    rules = []
    for c in focus:
        sub_c = df[df["cluster"] == c]
        top10 = [g for g, _ in Counter(g for gs in sub_c["ipc_groups"] for g in gs).most_common(10)]
        for p, *_ in PERIODS:
            for r in assoc_rules(sub_c[sub_c["period"] == p], top10):
                rules.append({"cluster": c, "period": p, **r})
    rules = pd.DataFrame(rules)

    # ---- 포지셔닝: 공동출원은 각 기업에 1건씩 계상(full counting)
    ex = df.explode("firms")
    firm_n = ex.groupby(["firms", "period"]).size().unstack(fill_value=0).reindex(columns=[p for p, *_ in PERIODS],
                                                                                  fill_value=0)
    firm_cl = ex.groupby(["firms", "cluster"]).size().unstack(fill_value=0)
    rta_tbl = rta(firm_cl)
    entry = ex.groupby(["firms", "cluster"])["year"].min().unstack()
    ex["multi_sub"] = ex["ipc_subclasses"].map(len).ge(2)
    conv = ex.groupby("firms").agg(n=("app_no", "size"), IPC서브클래스복수=("multi_sub", "mean"),
                                   평균IPC메인그룹수=("ipc_groups", lambda s: s.map(len).mean()))
    conv["IPC서브클래스복수"] *= 100
    # 사전 분류(C안)를 교차검증용으로 병행
    for axis, dic in (("vc", VALUE_CHAIN), ("tech", TECHNOLOGY)):
        df[axis] = df["text"].map(lambda t: [kk for kk, kws in dic.items() if any(match(w, t) for w in kws)])
    ex = df.explode("firms")
    firm_vc = pd.DataFrame({f: Counter(v for vs in g["vc"] for v in vs) for f, g in ex.groupby("firms")}).T.fillna(0)
    firm_tech = pd.DataFrame({f: Counter(v for vs in g["tech"] for v in vs) for f, g in ex.groupby("firms")}).T.fillna(0)

    with pd.ExcelWriter(out / "industry_tables.xlsx") as xw:
        cluster_tbl.to_excel(xw, sheet_name="01_군집_기간별비중")
        raw_terms.to_frame().assign(field="").rename_axis("cluster").to_excel(xw, sheet_name="01b_병합표_템플릿")
        bic.to_frame().to_excel(xw, sheet_name="02_BIC_k선택")
        rules.round(3).to_excel(xw, sheet_name="03_연관규칙", index=False)
        firm_n.to_excel(xw, sheet_name="04_기업별_출원")
        firm_cl.to_excel(xw, sheet_name="05_기업x군집_건수")
        rta_tbl.round(2).to_excel(xw, sheet_name="06_기업x군집_RTA")
        entry.to_excel(xw, sheet_name="07_군집_최초진입연도")
        conv.round(2).to_excel(xw, sheet_name="08_기업별_융합지표")
        rta(firm_vc).round(2).to_excel(xw, sheet_name="09_RTA_가치사슬(사전)")
        rta(firm_tech).round(2).to_excel(xw, sheet_name="10_RTA_기술요소(사전)")
        unmatched.to_frame("건수").to_excel(xw, sheet_name="11_미매칭_출원인")
        df.drop(columns=["text"]).assign(**{c: df[c].map("; ".join) for c in
                                            ("firms", "ipc_groups", "ipc_subclasses", "vc", "tech")}).to_excel(
            xw, sheet_name="00_원자료_분류결과", index=False)

    fig_heat(share.T, "기간별 기술군집 비중(%) — 보험산업 전체", "figA1_cluster_share.png", out)
    fig_heat(rta_tbl.reindex(firm_n.sum(axis=1).sort_values(ascending=False).index), "기업 × 기술군집 RTA (1 초과 = 상대 특화)",
             "figA2_rta.png", out, fmt="{:.1f}", cmap="RdBu_r",
             norm=LogNorm(vmin=1 / 3, vmax=3), color_clip=(1 / 3, 3))  # 1(중립)을 중심으로 대칭: 1/3 ↔ 3
    fig_firm_bars(firm_n.sum(axis=1), "기업별 출원 건수 (2016–2025, 공동출원 중복계상)", "figA3_firm_n.png", out)
    fig_firm_bars(conv["IPC서브클래스복수"], "기업별 융합 출원 비율(%) — IPC 서브클래스 2개 이상", "figA4_conv.png", out)

    n = len(df)
    db = firm_n.loc[FOCAL].sum() if FOCAL in firm_n.index else 0
    lines = [
        "# A안 분석 요약 (자동 생성 — 해석은 직접 기입)",
        f"- 대상: {len(FIRMS)}개사 출원 {n}건 (2016–2025), {FOCAL} {db}건 ({db / n * 100:.1f}%)",
        f"- 군집 수 k={k} ({'고정' if a.k else 'BIC 최소'}), 어휘 {len(vocab)}개, SVD {min(SVD_DIM, X.shape[1] - 1)}차원",
        f"- 군집 안정성 ARI(seed 1, 2) = {ari[0]:.2f}, {ari[1]:.2f}"
        + (" ⚠ k가 상한에 걸림 → 과분할 가능, 01b 시트로 병합표를 만들어 --merge로 재실행" if k == MAX_K or k == min(MAX_K, n // 15) else ""),
        f"- 미공개 가능 출원일: {cutoff.date()} 이후 → 해당 {int((df['app_date'] > cutoff).sum())}건, P3 과소집계 가능",
        f"- 미매칭 출원인 {int(unmatched.sum())}건 → 시트 11 확인 후 FIRMS에 추가",
        "", "## 기술군집 (원 논문 Table II 대응)", cluster_tbl.to_markdown(), "",
        f"## {FOCAL} RTA 상위/하위 군집",
        rta_tbl.loc[FOCAL].sort_values(ascending=False).round(2).to_frame("RTA").to_markdown()
        if FOCAL in rta_tbl.index else "(DB손보 출원 없음)", "",
        f"## 연관규칙 {len(rules)}개 (support≥{MIN_SUPPORT}, conf≥{MIN_CONF}, lift>{MIN_LIFT})",
        rules.sort_values("lift", ascending=False).head(10).round(2).to_markdown(index=False) if len(rules) else "(없음)",
    ]
    (out / "industry_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
