"""B안: 보험 기술영역(IPC G06Q 40/08)을 '비즈니스 생태계'로 정의하고 DB손해보험의 위치를 분석한다.

Suh & Sohn(2015)은 생태계를 '선도기업의 특허'로 대리했다. 보험업은 선도기업 하나가 생태계를 대표하지 않으므로,
기술영역에 출원한 모든 주체(보험사·IT/플랫폼·모빌리티·금융·대학·개인·해외 등)를 생태계로 보고
(1) 누가 생태계를 이끄는가, (2) 기술군집과 융합은 어떻게 변하는가, (3) DB손보는 어디에 서 있고 어디가 기회인가를 본다.

사용법:
    python ecosystem.py <KIPRIS_추출(G06Q 40/08 전체).xlsx> --asof 2026-10-14 [--broad] [--actors actors.csv] [--merge merge.csv]
"""
import argparse
import re
from collections import Counter
from pathlib import Path

import koreanize_matplotlib  # noqa: F401
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analyze import DISCLOSURE_LAG_MONTHS, IPC_RE, PERIODS, fig_heat, load
from industry import (FIRMS, FOCAL, assoc_rules, cluster, descriptive_terms, fig_firm_bars, firm_of, log_entropy, rta,
                      tokenize)
from sklearn.metrics import adjusted_rand_score

import industry

CORE_IPC = "G06Q 40/08"  # 보험(Insurance). --broad면 제목·요약에 '보험'이 있는 출원도 포함
ENTRY_MIN = 3            # 군집의 '생태계 등장 연도' = 누적 출원이 이 건수에 도달한 해
TOP_APPLICANTS = 30      # 유사도 비교 대상 상위 출원인 수

# 출원인 유형 규칙(위에서부터 우선 적용). 휴리스틱이므로 --actors CSV(열: applicant,type)로 덮어쓸 것.
ACTOR_RULES = [
    ("유관기관·공공", r"보험개발원|신용정보원|보험연구원|금융결제원|공단|공사$|정부|대한민국|청$"),
    ("대학·연구기관", r"대학|산학협력단|연구원|연구소|기술원|KAIST|과학기술"),
    ("보험사", r"보험|화재|생명|손해|Insurance|Life|Assurance|Re$"),
    ("금융(은행·카드·증권)", r"은행|카드|증권|캐피탈|금융지주|Bank"),
    ("IT·플랫폼", r"삼성에스디에스|엘지씨엔에스|LG CNS|에스케이|케이티|KT|네이버|카카오|비바리퍼블리카|현대오토에버|"
                 r"쿠팡|NHN|엔에이치엔|SK주식회사|에스케이텔레콤|엘지유플러스"),
    ("모빌리티·제조", r"자동차|모비스|기아|만도|르노|쌍용|타이어|전자"),
    ("해외 기업", r"\b(Inc|LLC|Corp|Corporation|Ltd|Limited|GmbH|AG|S\.A|B\.V|Co\.)\b"),
]
ACTOR_ORDER = ["보험사", "인슈어테크", "헬스케어·의료IT", "IT·플랫폼", "모빌리티·제조", "금융(은행·카드·증권)",
               "대학·연구기관", "해외 기업", "기타 기업", "유관기관·공공", "개인"]
# 인슈어테크·헬스케어·의료IT는 이름 규칙으로 판별할 수 없어 --actors CSV로만 지정된다(출원 내용 기준 분석자 판단).
# 9번째(기타 기업) 이후는 회색으로 접는다.
# 기본 분류 팔레트(검증된 순서 그대로, 9번째 이후는 회색으로 접음)
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948", "#b4b2a9"]


def split_applicants(s):
    return [p.strip() for p in re.split(r"[|;]", str(s)) if p.strip()]


def canon(name):
    """보험사는 사명 변경 전후를 표준 기업명으로 통합(예: 동부화재 → DB손보). 그 외는 원래 표기."""
    f = firm_of(name)
    return f[0] if f else name


def actor_type(name, override):
    if name in override:
        return override[name]
    if firm_of(name):
        return "보험사"
    for t, pat in ACTOR_RULES:
        if re.search(pat, name):
            return t
    corp = re.search(r"주식회사|\(주\)|㈜|유한|법인|재단|협회|조합|센터|그룹|컴퍼니|랩|테크|시스템", name)
    if not corp and re.fullmatch(r"[가-힣]{2,4}", name):
        return "개인"
    return "기타 기업"  # 인슈어테크·스타트업·중소 IT 등이 대부분 여기에 들어간다(추정) → --actors로 세분화


def hhi(counts):
    s = counts / counts.sum()
    return float((s ** 2).sum() * 10000)


def fig_actor_share(tbl, out):
    """기간별 출원주체 유형 비중 — 100% 누적 가로막대(인접 쌍 기준 팔레트)."""
    t = tbl.div(tbl.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(8.5, 2.6))
    left = np.zeros(len(t))
    for i, c in enumerate(t.columns):
        ax.barh(t.index, t[c], left=left, color=PALETTE[min(i, 8)], height=0.55, label=c,
                edgecolor="white", linewidth=1.5)
        for y, (l, v) in enumerate(zip(left, t[c])):
            if v >= 6:
                ax.text(l + v / 2, y, f"{v:.0f}", ha="center", va="center", fontsize=7, color="white")
        left += t[c].values
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("%", fontsize=8)
    ax.set_title("기간별 출원주체 유형 비중 (G06Q 40/08 생태계, 공동출원 중복계상)", loc="left", fontsize=10)
    ax.legend(ncol=5, fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(0, -0.25))
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    fig.savefig(out / "figB1_actor_share.png", dpi=200)
    plt.close(fig)


def fig_opportunity(opp, out):
    """기회 맵: x=군집 비중 변화(P1→P3, %p), y=DB손보 RTA(로그), 점 크기=군집 규모."""
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    y = opp["DB_RTA"].clip(lower=0.1)
    ax.scatter(opp["share_change_pp"], y, s=30 + opp["n"] * 1.2, color="#2a78d6", alpha=0.85,
               edgecolors="white", linewidths=2, zorder=3)
    for name, r in opp.iterrows():
        ax.annotate(name.split(" ", 1)[-1], (r["share_change_pp"], max(r["DB_RTA"], 0.1)), fontsize=7,
                    xytext=(5, 4), textcoords="offset points", color="#0b0b0b")
    ax.set_yscale("log")
    ax.set_yticks([0.1, 0.25, 0.5, 1, 2, 4], ["0.1", "0.25", "0.5", "1", "2", "4"])
    ax.yaxis.set_minor_formatter(plt.NullFormatter())
    ax.axhline(1, color="#8a8984", linewidth=0.8)
    ax.axvline(0, color="#8a8984", linewidth=0.8)
    xl, yl = ax.get_xlim(), ax.get_ylim()
    for (xx, yy, txt, ha, va) in [(xl[1], yl[1], "성장 × DB 특화\n(강점 유지)", "right", "top"),
                                   (xl[1], yl[0], "성장 × DB 열위\n(기회·위협)", "right", "bottom"),
                                   (xl[0], yl[1], "정체 × DB 특화\n(재점검)", "left", "top"),
                                   (xl[0], yl[0], "정체 × DB 열위", "left", "bottom")]:
        ax.text(xx, yy, txt, ha=ha, va=va, fontsize=8, color="#52514e")
    ax.set_xlabel("생태계 내 군집 비중 변화 P1→P3 (%p)", fontsize=8)
    ax.set_ylabel("DB손보 RTA (로그, 0은 0.1로 표시)", fontsize=8)
    ax.set_title("기술군집 기회 맵 — DB손보 관점", loc="left", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    fig.savefig(out / "figB3_opportunity.png", dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--asof", required=True)
    ap.add_argument("--out", default="out_ecosystem")
    ap.add_argument("--broad", action="store_true", help="G06Q 40/08 외에 제목·요약에 '보험' 포함 출원도 생태계에 포함")
    ap.add_argument("--actors", help="출원인 유형 수작업 지정 CSV(열: applicant,type)")
    ap.add_argument("--merge", help="군집 병합표 CSV(열: cluster,field)")
    ap.add_argument("--k", type=int, default=0)
    ap.add_argument("--svd", type=int, default=industry.SVD_DIM, help="SVD 차원(원 논문 25)")
    ap.add_argument("--kmax", type=int, default=industry.MAX_K)
    ap.add_argument("--min-count", type=int, default=industry.MIN_COUNT, help="연관규칙 최소 동시출현")
    ap.add_argument("--focus", type=int, default=4)
    a = ap.parse_args()
    industry.SVD_DIM, industry.MAX_K, industry.MIN_COUNT = a.svd, a.kmax, a.min_count
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    override = pd.read_csv(a.actors).set_index("applicant")["type"].to_dict() if a.actors else {}

    # ---- 생태계 정의
    df = load(a.input)
    df = df[df["year"].between(PERIODS[0][1], PERIODS[-1][2])].copy()
    df["text"] = (df["title"].astype(str) + " " + df["abstract"].astype(str)).str.replace(r"\s+", " ", regex=True)
    core = df["ipc"].astype(str).str.replace(" ", "").str.contains(CORE_IPC.replace(" ", ""), regex=False)
    df = df[core | (df["text"].str.contains("보험") if a.broad else False)].reset_index(drop=True)
    df["period"] = df["year"].map(lambda y: next(p for p, s, e in PERIODS if s <= y <= e))
    df["ipc_groups"] = df["ipc"].astype(str).map(lambda s: sorted({f"{m[0]} {m[1]}" for m in IPC_RE.findall(s)}))
    df["applicants_raw"] = df["applicant"].map(split_applicants)
    df["actor_types"] = df["applicants_raw"].map(lambda ns: sorted({actor_type(n, override) for n in ns}))
    df["applicants"] = df["applicants_raw"].map(lambda ns: sorted({canon(n) for n in ns}))
    df["is_focal"] = df["applicant"].map(lambda s: FOCAL in firm_of(s))
    cutoff = pd.Timestamp(a.asof) - pd.DateOffset(months=DISCLOSURE_LAG_MONTHS)

    # ---- (1) 생태계 구조: 주체 유형, 선도 출원인, 집중도
    ex_t = df.explode("actor_types")
    actor_tbl = (ex_t.groupby(["period", "actor_types"]).size().unstack(fill_value=0)
                 .reindex(columns=[c for c in ACTOR_ORDER if c in set(ex_t["actor_types"])], fill_value=0))
    ex_a = df.explode("applicants")
    ex_a["type"] = ex_a["applicants"].map(lambda n: "보험사" if n in FIRMS else actor_type(n, override))
    top_app = (ex_a.groupby(["applicants", "type"]).size().rename("n").reset_index()
               .sort_values("n", ascending=False).head(TOP_APPLICANTS))
    app_period = ex_a.groupby(["applicants", "period"]).size().unstack(fill_value=0)
    top_app = top_app.join(app_period, on="applicants")
    conc = pd.DataFrame({p: {"출원 건수": int((df["period"] == p).sum()),
                             "출원인 수": ex_a.loc[ex_a["period"] == p, "applicants"].nunique(),
                             "HHI(출원인)": hhi(ex_a.loc[ex_a["period"] == p, "applicants"].value_counts()),
                             "보험사 비중(%)": df.loc[df["period"] == p, "actor_types"].map(lambda t: "보험사" in t).mean() * 100,
                             f"{FOCAL} 비중(%)": df.loc[df["period"] == p, "is_focal"].mean() * 100}
                         for p, *_ in PERIODS}).T

    # ---- (2) 기술군집(원 논문 4.2)과 연관규칙(4.3)
    tokens = tokenize(df["text"])
    X, vocab, tf = log_entropy(tokens)
    labels, k, bic = cluster(X, a.k)
    ari = [adjusted_rand_score(labels, cluster(X, k, seed=s)[0]) for s in (1, 2)]
    terms = descriptive_terms(labels, tf, vocab)
    raw = pd.Series({f"C{c:02d} " + "·".join(t[:3]): ", ".join(t) for c, t in terms.items()}, name="대표어")
    df["cluster"] = [f"C{c:02d} " + "·".join(terms[c][:3]) for c in labels]
    if a.merge:
        mp = pd.read_csv(a.merge).set_index("cluster")["field"].to_dict()
        df["cluster"] = df["cluster"].map(lambda c: mp.get(c, c))
    periods = [p for p, *_ in PERIODS]
    cl_period = df.groupby(["cluster", "period"]).size().unstack(fill_value=0).reindex(columns=periods, fill_value=0)
    cl_share = cl_period.div(cl_period.sum(axis=0), axis=1) * 100
    ex_t = df.explode("actor_types")
    cl_actor = ex_t.groupby(["cluster", "actor_types"]).size().unstack(fill_value=0)
    cl_actor_share = cl_actor.div(cl_actor.sum(axis=1), axis=0) * 100   # 군집별로 누가 출원하나

    rules = []
    for c in df["cluster"].value_counts().index[: a.focus]:
        sub_c = df[df["cluster"] == c]
        top10 = [g for g, _ in Counter(g for gs in sub_c["ipc_groups"] for g in gs).most_common(10)]
        for p in periods:
            rules += [{"cluster": c, "period": p, **r} for r in assoc_rules(sub_c[sub_c["period"] == p], top10)]
    rules = pd.DataFrame(rules)

    # ---- (3) DB손보 포지셔닝
    ex_a = df.explode("applicants")
    ex_a["type"] = ex_a["applicants"].map(lambda n: "보험사" if n in FIRMS else actor_type(n, override))
    app_cl = ex_a.groupby(["applicants", "cluster"]).size().unstack(fill_value=0)
    focal_names = [FOCAL] if FOCAL in app_cl.index else []
    focal_vec = app_cl.loc[focal_names].sum() if focal_names else pd.Series(0, index=app_cl.columns)
    eco_vec = cl_period.sum(axis=1)
    db_rta = rta(pd.DataFrame([focal_vec, eco_vec], index=[FOCAL, "생태계"])).loc[FOCAL]
    # 진입 시차: DB 첫 출원 연도 − 군집이 생태계에서 누적 ENTRY_MIN건에 도달한 연도 (음수 = 선도)
    eco_entry = df.sort_values("app_date").groupby("cluster")["year"].apply(
        lambda s: s.iloc[ENTRY_MIN - 1] if len(s) >= ENTRY_MIN else np.nan)
    db_entry = df[df["is_focal"]].groupby("cluster")["year"].min()
    opp = pd.DataFrame({"n": eco_vec, "share_P1(%)": cl_share[periods[0]], "share_P3(%)": cl_share[periods[-1]],
                        "share_change_pp": cl_share[periods[-1]] - cl_share[periods[0]],
                        "보험사 비중(%)": cl_actor_share.get("보험사", 0),
                        "DB_n": focal_vec, "DB_RTA": db_rta, "생태계_등장연도": eco_entry,
                        "DB_진입연도": db_entry})
    opp["진입시차(년)"] = opp["DB_진입연도"] - opp["생태계_등장연도"]
    opp["사분면"] = np.select(
        [(opp.share_change_pp >= 0) & (opp.DB_RTA >= 1), (opp.share_change_pp >= 0) & (opp.DB_RTA < 1),
         (opp.share_change_pp < 0) & (opp.DB_RTA >= 1)], ["성장×특화", "성장×열위", "정체×특화"], "정체×열위")
    # 기술 프로파일 코사인 유사도: DB와 가장 닮은 출원인(잠재 경쟁자·협력 후보)
    peers = app_cl.loc[[n for n in top_app["applicants"] if n not in focal_names and n in app_cl.index]]
    sim = (peers @ focal_vec) / (np.linalg.norm(peers, axis=1) * (np.linalg.norm(focal_vec) or 1))
    sim = sim.rename("코사인유사도").to_frame().join(top_app.set_index("applicants")[["type", "n"]]) \
        .sort_values("코사인유사도", ascending=False)

    with pd.ExcelWriter(out / "ecosystem_tables.xlsx") as xw:
        conc.round(1).to_excel(xw, sheet_name="01_생태계_규모·집중도")
        actor_tbl.to_excel(xw, sheet_name="02_주체유형x기간")
        top_app.to_excel(xw, sheet_name="03_상위출원인", index=False)
        raw.to_frame().assign(field="").rename_axis("cluster").to_excel(xw, sheet_name="04a_병합표_템플릿")
        cl_period.join(cl_share.round(1).add_suffix(" (%)")).to_excel(xw, sheet_name="04_군집x기간")
        cl_actor_share.round(1).to_excel(xw, sheet_name="05_군집x주체유형(%)")
        rules.round(3).to_excel(xw, sheet_name="06_연관규칙", index=False)
        opp.round(2).sort_values("share_change_pp", ascending=False).to_excel(xw, sheet_name="07_DB_기회맵")
        sim.round(3).to_excel(xw, sheet_name="08_DB_유사출원인")
        ex_a[["applicants", "type"]].drop_duplicates().sort_values(["type", "applicants"]).to_excel(
            xw, sheet_name="09_출원인유형_검토", index=False)
        df.drop(columns=["text"]).assign(**{c: df[c].map("; ".join) for c in
                                            ("ipc_groups", "applicants", "applicants_raw", "actor_types")}).to_excel(
            xw, sheet_name="00_원자료", index=False)

    fig_actor_share(actor_tbl, out)
    s = top_app.set_index("applicants")["n"].head(15)
    s.index = [n.replace("주식회사", "").strip() for n in s.index]
    fig_firm_bars(s,
                  "생태계 상위 출원인 15 (2016–2025)", "figB2_top_applicants.png", out)
    fig_opportunity(opp, out)
    fig_heat(cl_actor_share.reindex(columns=[c for c in ACTOR_ORDER if c in cl_actor_share.columns]),
             "군집별 출원주체 구성(%, 행 합 100 기준 중복계상)", "figB4_cluster_actor.png", out)

    lines = [
        "# B안 분석 요약 (자동 생성 — 해석은 직접 기입)",
        f"- 생태계 정의: IPC {CORE_IPC}" + (" + 제목·요약 '보험' 포함" if a.broad else "") +
        f", 2016–2025 출원 {len(df)}건, 출원인 {ex_a['applicants'].nunique()}명(곳)",
        f"- {FOCAL} {int(df['is_focal'].sum())}건 ({df['is_focal'].mean() * 100:.1f}%)",
        f"- 군집 k={k}, 안정성 ARI={ari[0]:.2f}/{ari[1]:.2f}" + (" ⚠ k 상한 → 04a 시트로 병합 후 --merge" if k >= 20 or k == len(df) // 15 else ""),
        f"- 미공개 가능 출원일 {cutoff.date()} 이후 {int((df['app_date'] > cutoff).sum())}건 (P3 과소집계 가능)",
        f"- '기타 기업' {int((ex_a['type'] == '기타 기업').sum())}건 → 09 시트 보고 --actors로 인슈어테크 등 세분화 권장",
        "", "## 생태계 규모·집중도", conc.round(1).to_markdown(), "",
        "## DB손보 기회 맵(사분면)", opp[["n", "share_change_pp", "DB_n", "DB_RTA", "진입시차(년)", "사분면"]]
        .sort_values("share_change_pp", ascending=False).round(2).to_markdown(), "",
        "## DB손보와 기술 프로파일이 가장 유사한 출원인 5", sim.head(5).round(2).to_markdown(),
    ]
    (out / "ecosystem_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
