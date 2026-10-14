"""1편(Scientometrics) 강건성 분석: 선도기업 대리변수 검증 · 등록 로지스틱 회귀 · 연관규칙 유의성.

사용법:
    python paper1/robustness.py <G06Q4008.xlsx> <ecosystem_tables.xlsx> <actors.csv> --out <dir> [--draws 500]

1) 선도기업 대리변수 검증 — 군집 k ∈ {8,10,12,14,16} × 초기값 5개 × 선도기업 정의 4개
   지표: 기간별 구성 유사도(코사인), 비중 증감 순위상관(Spearman), 선행상관
   귀무분포: 선도기업과 출원 규모가 같은 '무작위 출원인 묶음'(출원인 단위 순열)
2) 등록 로지스틱 회귀 — 심사 종결 출원(2016–2022), 출원주체 유형 + 연도·군집 고정효과
3) 연관규칙 유의성 — 초기하분포 p값 + Benjamini–Hochberg 보정
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import hypergeom, spearmanr
from sklearn.decomposition import TruncatedSVD
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import normalize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ecosystem as E  # noqa: E402
import industry as I  # noqa: E402
from analyze import IPC_RE, PERIODS, load  # noqa: E402

PER = [p for p, *_ in PERIODS]
LEADERS = {
    "삼성생명+삼성화재": {"삼성생명", "삼성화재"},
    "삼성화재": {"삼성화재"},
    "삼성생명": {"삼성생명"},
    "상위3사(삼성생명·삼성화재·롯데손보)": {"삼성생명", "삼성화재", "롯데손보"},
}
TYPE_PRIORITY = ["보험사", "인슈어테크", "헬스케어·의료IT", "IT·플랫폼", "모빌리티·제조", "금융(은행·카드·증권)",
                 "대학·연구기관", "해외 기업", "유관기관·공공", "개인", "기타 기업"]


def prep(path, actors):
    df = load(path)
    df = df[df["year"].between(2016, 2025)].reset_index(drop=True)
    df["period"] = df["year"].map(lambda y: next(p for p, s, e in PERIODS if s <= y <= e))
    df["ipc_groups"] = df["ipc"].astype(str).map(lambda s: sorted({f"{m[0]} {m[1]}" for m in IPC_RE.findall(s)}))
    raw = df["applicant"].map(E.split_applicants)
    df["apps"] = raw.map(lambda ns: sorted({E.canon(n) for n in ns}))
    override = pd.read_csv(actors).set_index("applicant")["type"].to_dict()
    types = raw.map(lambda ns: {E.actor_type(n, override) for n in ns})
    df["ptype"] = types.map(lambda ts: next(t for t in TYPE_PRIORITY if t in ts))  # 공동출원은 우선순위로 1개 유형
    df["text"] = (df["title"].astype(str) + " " + df["abstract"].astype(str))
    return df


def profiles(labels, mask, period, k):
    out = {}
    for p in PER:
        m = period == p
        a = np.bincount(labels[m & mask], minlength=k).astype(float)
        b = np.bincount(labels[m & ~mask], minlength=k).astype(float)
        out[p] = (a / max(a.sum(), 1), b / max(b.sum(), 1))
    return out


def metrics(labels, mask, period, k):
    pr = profiles(labels, mask, period, k)
    cos = {p: float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) or 1)) for p, (a, b) in pr.items()}
    gl = pr[PER[-1]][0] - pr[PER[0]][0]
    gr = pr[PER[-1]][1] - pr[PER[0]][1]
    rho = spearmanr(gl, gr).statistic
    lead = spearmanr(pr[PER[1]][0] - pr[PER[0]][0], pr[PER[2]][1] - pr[PER[1]][1]).statistic
    return cos, rho, lead


def random_group_masks(df, leader_set, rng, draws):
    """선도기업과 총 출원 건수가 비슷한 무작위 출원인 묶음(선도기업 제외)을 뽑는다."""
    target = int(df["apps"].map(lambda a: bool(leader_set & set(a))).sum())
    app_idx = {}
    for i, apps in enumerate(df["apps"]):
        for a in apps:
            if a not in leader_set:
                app_idx.setdefault(a, []).append(i)
    names = np.array(list(app_idx))
    masks = []
    for _ in range(draws):
        rng.shuffle(names)
        chosen, n = set(), 0
        for a in names:
            if n >= target:
                break
            new = set(app_idx[a]) - chosen
            chosen |= new
            n += len(new)
        m = np.zeros(len(df), bool)
        m[list(chosen)] = True
        masks.append(m)
    return masks


def leader_proxy(df, draws, ks=(8, 10, 12, 14, 16), seeds=range(5), dim=25):
    X, vocab, tf = I.log_entropy(I.tokenize(df["text"]))
    period = df["period"].to_numpy()
    rng = np.random.default_rng(42)
    null_masks = {name: random_group_masks(df, s, rng, draws) for name, s in LEADERS.items()}
    lmask = {name: df["apps"].map(lambda a, s=s: bool(s & set(a))).to_numpy() for name, s in LEADERS.items()}
    rows = []
    for seed in seeds:
        Z = normalize(TruncatedSVD(dim, random_state=seed).fit_transform(X))
        for k in ks:
            labels = GaussianMixture(k, covariance_type="diag", n_init=3, random_state=seed).fit(Z).predict(Z)
            for name in LEADERS:
                cos, rho, lead = metrics(labels, lmask[name], period, k)
                null = [metrics(labels, m, period, k) for m in null_masks[name]]
                row = {"leader": name, "k": k, "seed": seed, "n_leader": int(lmask[name].sum()),
                       "rho_growth": rho, "p_rho(무작위보다 낮음)": np.mean([n[1] <= rho for n in null]),
                       "lead_corr": lead, "p_lead": np.mean([n[2] >= lead for n in null])}
                for p in PER:
                    row[f"cos {p}"] = cos[p]
                    row[f"p_cos {p}"] = np.mean([n[0][p] <= cos[p] for n in null])
                    row[f"null_cos_med {p}"] = np.median([n[0][p] for n in null])
                rows.append(row)
        print(f"seed {seed} done", flush=True)
    det = pd.DataFrame(rows)
    agg = {c: "median" for c in det.columns if c not in ("leader", "k", "seed")}
    summ = det.groupby("leader").agg(agg)
    for c in [c for c in det.columns if c.startswith("p_")]:
        summ[c.replace("p_", "share_p<.05 ")] = det.groupby("leader")[c].apply(lambda s: (s < 0.05).mean())
    return det, summ


def grant_logit(df, clusters):
    import statsmodels.formula.api as smf
    d = df.assign(app_no=df["app_no"].astype(str)).merge(
        clusters.assign(app_no=clusters["app_no"].astype(str)), on="app_no", how="left")
    d = d[d["year"] <= 2022].copy()
    st = d["status"].astype(str).str.replace(r"\s*\(.*", "", regex=True)
    d = d[st.isin(["등록", "소멸", "거절", "취하", "포기"])].copy()
    d["granted"] = st.loc[d.index].isin(["등록", "소멸"]).astype(int)
    d["n_ipc"] = d["ipc_groups"].map(len)
    d["claim_len"] = d["claim"].astype(str).str.len() / 100
    d["ptype"] = d["ptype"].replace({"유관기관·공공": "기타 기업", "해외 기업": "기타 기업"})
    out = {}
    for name, f in {
        "M1 유형만": "granted ~ C(ptype, Treatment('기타 기업'))",
        "M2 +연도·군집 FE": "granted ~ C(ptype, Treatment('기타 기업')) + C(year) + C(cluster)",
        "M3 +IPC수·청구항길이": "granted ~ C(ptype, Treatment('기타 기업')) + C(year) + C(cluster) + n_ipc + claim_len",
    }.items():
        m = smf.logit(f, data=d).fit(disp=0, cov_type="HC1")
        t = pd.DataFrame({"coef": m.params, "OR": np.exp(m.params), "se": m.bse, "p": m.pvalues})
        out[name] = (t[t.index.str.contains("ptype|n_ipc|claim_len")], m.nobs, m.prsquared)
    rates = d.groupby("ptype")["granted"].agg(["count", "mean"]).sort_values("count", ascending=False)
    return out, rates


def rule_significance(eco_xlsx):
    raw = pd.read_excel(eco_xlsx, sheet_name="00_원자료", dtype=str)
    raw["g"] = raw["ipc_groups"].fillna("").str.split("; ").map(set)
    rules = pd.read_excel(eco_xlsx, sheet_name="06_연관규칙")
    ps = []
    for r in rules.itertuples():
        sub = raw[(raw["cluster"] == r.cluster) & (raw["period"] == r.period)]
        lhs, rhs = [set(x.split(" + ")) for x in r.rule.split(" → ")]
        n = len(sub)
        cx = sub["g"].map(lambda g: lhs <= g).sum()
        cy = sub["g"].map(lambda g: rhs <= g).sum()
        ps.append(hypergeom.sf(r.count - 1, n, cy, cx))
    rules["p_hypergeom"] = ps
    order = np.argsort(ps)
    m = len(ps)
    q = np.empty(m)
    prev = 1.0
    for rank, i in reversed(list(enumerate(order, start=1))):
        prev = min(prev, ps[i] * m / rank)
        q[i] = prev
    rules["q_BH"] = q
    return rules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patents")
    ap.add_argument("eco_tables")
    ap.add_argument("actors")
    ap.add_argument("--out", default="out_paper1")
    ap.add_argument("--draws", type=int, default=500)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df = prep(a.patents, a.actors)
    clusters = pd.read_excel(a.eco_tables, sheet_name="00_원자료", dtype=str)[["app_no", "cluster"]]

    cache = out / "leader_proxy_detail.csv"
    if cache.exists():  # 오래 걸리는 단계라 결과를 저장해 두고 재사용
        det = pd.read_csv(cache)
        agg = {c: "median" for c in det.columns if c not in ("leader", "k", "seed")}
        summ = det.groupby("leader").agg(agg)
        for c in [c for c in det.columns if c.startswith("p_")]:
            summ[c.replace("p_", "share_p<.05 ")] = det.groupby("leader")[c].apply(lambda s: (s < 0.05).mean())
    else:
        det, summ = leader_proxy(df, a.draws)
        det.to_csv(cache, index=False)
    logits, rates = grant_logit(df, clusters)
    rules = rule_significance(a.eco_tables)

    with pd.ExcelWriter(out / "paper1_robustness.xlsx") as xw:
        summ.round(3).to_excel(xw, sheet_name="01_대리변수_요약")
        det.round(3).to_excel(xw, sheet_name="02_대리변수_전체", index=False)
        rates.round(3).to_excel(xw, sheet_name="03_유형별_등록률")
        for i, (name, (t, n, r2)) in enumerate(logits.items()):
            t.round(4).to_excel(xw, sheet_name=f"04_logit_M{i + 1}")
        rules.round(4).to_excel(xw, sheet_name="05_규칙_유의성", index=False)
    pd.set_option("display.width", 250)
    print(summ.round(3).T.to_string())
    print(rates.round(3).to_string())
    for name, (t, n, r2) in logits.items():
        print(f"\n{name}  n={int(n)}  pseudo-R2={r2:.3f}")
        print(t.round(3).to_string())
    print(f"\n규칙 {len(rules)}개 중 p<.05: {(rules.p_hypergeom < .05).sum()}, q<.05: {(rules.q_BH < .05).sum()}, "
          f"q<.10: {(rules.q_BH < .10).sum()}")
    print(rules.sort_values("q_BH").head(15)[["cluster", "period", "rule", "count", "lift", "p_hypergeom", "q_BH"]]
          .round(4).to_string(index=False))


if __name__ == "__main__":
    main()
