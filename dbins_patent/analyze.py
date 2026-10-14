"""DB손해보험 특허 기술동향 분석 (Suh & Sohn, 2015 프레임워크의 소표본 축소판).

사용법:
    python analyze.py <KIPRIS_추출파일.xlsx|csv> --asof 2026-10-14 [--out out]

입력: KIPRIS 검색결과 다운로드 파일. 열 이름은 COLUMN_ALIASES로 자동 매핑한다.
출력: out/tables.xlsx, out/fig_*.png, out/summary.md
"""
import argparse
import itertools
import re
from collections import Counter
from pathlib import Path

import koreanize_matplotlib  # noqa: F401  (한글 폰트 등록)
import matplotlib
matplotlib.rcParams["axes.unicode_minus"] = False  # 나눔고딕에 U+2212 글리프 없음
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

from taxonomy import TECHNOLOGY, VALUE_CHAIN

# 기간 구분: 2년 단위(원 논문)는 구간당 표본이 너무 작아 3구간으로 묶는다
PERIODS = [("P1 2016–19", 2016, 2019), ("P2 2020–22", 2020, 2022), ("P3 2023–25", 2023, 2025)]
FOCAL_NAMES = ["DB손해보험", "디비손해보험", "동부화재"]  # 2017년 사명 변경 전후 모두 포함
DISCLOSURE_LAG_MONTHS = 18  # 특허법 제64조: 출원 후 1년 6개월 경과 시 공개

COLUMN_ALIASES = {
    "app_no": ["출원번호", "출원번호(일자)"],
    "app_date": ["출원일자", "출원일"],
    "title": ["발명의명칭", "발명의 명칭", "명칭", "발명의명칭(국문)"],
    "abstract": ["요약", "초록", "요약(국문)"],
    "claim": ["대표청구항", "청구항"],
    "ipc": ["IPC", "IPC분류", "국제특허분류", "IPC코드"],
    "applicant": ["출원인", "출원인명"],
    "status": ["행정처리상태", "법적상태", "상태", "최종처분"],
    "reg_no": ["등록번호"],
}

C_BLUE, C_GRAY, C_ORANGE = "#2a78d6", "#b4b2a9", "#eb6834"
IPC_RE = re.compile(r"([A-H]\d{2}[A-Z])\s*(\d{1,4})\s*/\s*(\d{1,6})")


def load(path):
    df = pd.read_csv(path) if str(path).endswith(".csv") else pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    for key, aliases in COLUMN_ALIASES.items():
        hit = next((a for a in aliases if a in df.columns), None)
        if hit:
            rename[hit] = key
    df = df.rename(columns=rename)
    missing = [k for k in ("app_no", "app_date", "title", "ipc", "applicant") if k not in df.columns]
    if missing:
        raise SystemExit(f"필수 열 없음: {missing}. 실제 열: {list(df.columns)} → COLUMN_ALIASES에 추가하세요.")
    for k in ("abstract", "claim", "status", "reg_no"):
        if k not in df.columns:
            df[k] = ""
    df = df.fillna({"abstract": "", "claim": "", "status": "", "reg_no": ""})
    df["app_date"] = pd.to_datetime(df["app_date"].astype(str).str.extract(r"(\d{4}[.\-]?\d{2}[.\-]?\d{2})")[0]
                                    .str.replace(r"[.\-]", "", regex=True), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["app_date"]).drop_duplicates("app_no")
    df["year"] = df["app_date"].dt.year
    return df


def prepare(df, asof):
    df = df[df["applicant"].astype(str).str.contains("|".join(FOCAL_NAMES))].copy()
    df = df[df["year"].between(PERIODS[0][1], PERIODS[-1][2])]

    def period(y):
        return next(p for p, a, b in PERIODS if a <= y <= b)

    df["period"] = df["year"].map(period)
    df["ipc_groups"] = df["ipc"].astype(str).map(
        lambda s: sorted({f"{m[0]} {m[1]}" for m in IPC_RE.findall(s)}))          # 메인그룹(예: G06Q 40)
    df["ipc_subclasses"] = df["ipc_groups"].map(lambda g: sorted({x.split()[0] for x in g}))  # 서브클래스(G06Q)
    df["registered"] = (df["reg_no"].astype(str).str.strip().ne("")
                        | df["status"].astype(str).str.contains("등록"))
    # 공동출원: 출원인 문자열을 구분자로 나눠 DB/동부 외 주체가 있는지 확인
    df["co_applied"] = df["applicant"].astype(str).map(
        lambda s: any(p.strip() and not any(n in p for n in FOCAL_NAMES) for p in re.split(r"[|;,/]", s)))
    cutoff = pd.Timestamp(asof) - pd.DateOffset(months=DISCLOSURE_LAG_MONTHS)
    df["maybe_truncated"] = df["app_date"] > cutoff
    text = (df["title"].astype(str) + " " + df["abstract"].astype(str)).str.replace(r"\s+", " ", regex=True)
    df["text"] = text
    for axis, dic in (("vc", VALUE_CHAIN), ("tech", TECHNOLOGY)):
        df[axis] = text.map(lambda t: [k for k, kws in dic.items() if any(match(kw, t) for kw in kws)])
    return df, cutoff


def match(kw, text):
    if re.fullmatch(r"[A-Za-z]+", kw):  # 영문 약어는 단어 경계로 매칭(예: AI가 AIR에 걸리지 않게)
        return re.search(rf"(?<![A-Za-z]){kw}(?![A-Za-z])", text) is not None
    return kw in text


def share_table(df, col, labels):
    """기간별 라벨 비중(%) — 원 논문 Table II에 대응. 다중라벨이므로 합계가 100%를 넘을 수 있다."""
    rows = {}
    for p, *_ in PERIODS:
        sub = df[df["period"] == p]
        n = len(sub)
        rows[p] = {l: (sub[col].map(lambda x: l in x).sum() / n * 100 if n else np.nan) for l in labels}
        rows[p]["(미분류)"] = sub[col].map(len).eq(0).sum() / n * 100 if n else np.nan
        rows[p]["n"] = n
    return pd.DataFrame(rows).T


def cooccurrence(df, col, min_count=2):
    """항목 쌍의 동시출현과 Suh & Sohn(2015)의 support/confidence/lift(기술통계로만 보고)."""
    n = len(df)
    item_cnt = Counter(i for items in df[col] for i in set(items))
    pair_cnt = Counter(p for items in df[col] for p in itertools.combinations(sorted(set(items)), 2))
    rows = []
    for (a, b), c in pair_cnt.items():
        if c < min_count:
            continue
        rows.append({"A": a, "B": b, "count": c, "support": c / n,
                     "conf(A→B)": c / item_cnt[a], "conf(B→A)": c / item_cnt[b],
                     "lift": (c / n) / ((item_cnt[a] / n) * (item_cnt[b] / n))})
    return pd.DataFrame(rows).sort_values(["count", "lift"], ascending=False) if rows else pd.DataFrame(
        columns=["A", "B", "count", "support", "conf(A→B)", "conf(B→A)", "lift"])


def convergence_index(df):
    """기간별 융합 지표: 서로 다른 IPC 서브클래스 ≥2개, 기술요소 ≥2개, 가치사슬×기술 동시 부여 비율."""
    out = {}
    for p, *_ in PERIODS:
        sub = df[df["period"] == p]
        n = len(sub)
        out[p] = {"n": n,
                  "IPC 서브클래스 복수(%)": sub["ipc_subclasses"].map(len).ge(2).mean() * 100 if n else np.nan,
                  "평균 IPC 메인그룹 수": sub["ipc_groups"].map(len).mean() if n else np.nan,
                  "기술요소 복수(%)": sub["tech"].map(len).ge(2).mean() * 100 if n else np.nan,
                  "공동출원(%)": sub["co_applied"].mean() * 100 if n else np.nan}
    return pd.DataFrame(out).T


def keyword_trend(df, top=15):
    """기간별 명사 키워드 빈도(문서빈도) — 부상/쇠퇴 키워드 식별용."""
    from kiwipiepy import Kiwi
    kiwi = Kiwi()
    for w in ["인공지능", "블랙박스", "손해사정", "보험금", "언더라이팅", "텔레매틱스", "빅데이터", "챗봇", "과실비율"]:
        kiwi.add_user_word(w, "NNG")
    stop = {"시스템", "방법", "장치", "서버", "단말", "정보", "제공", "이용", "기반", "관련", "처리", "단계", "수행",
            "포함", "사용자", "데이터", "프로그램", "기록", "매체", "보험", "컴퓨터", "본", "발명", "상기", "통해", "위해"}
    docs = df["text"].map(lambda t: {tok.form for tok in kiwi.tokenize(t)
                                     if tok.tag in ("NNG", "NNP", "SL") and len(tok.form) > 1 and tok.form not in stop})
    rows = []
    for p, *_ in PERIODS:
        sub = docs[df["period"] == p]
        n = len(sub)
        for w, c in Counter(w for d in sub for w in d).most_common(top):
            rows.append({"period": p, "keyword": w, "docs": c, "share(%)": c / n * 100})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 그림
def fig_yearly(df, cutoff, out):
    years = list(range(PERIODS[0][1], PERIODS[-1][2] + 1))
    reg = df[df["registered"]].groupby("year").size().reindex(years, fill_value=0)
    tot = df.groupby("year").size().reindex(years, fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.bar(years, reg, color=C_BLUE, width=0.6, label="등록")
    ax.bar(years, tot - reg, bottom=reg, color=C_GRAY, width=0.6, label="미등록(심사중·거절·취하 등)",
           edgecolor="white", linewidth=1)
    ymax = max(tot.max(), 1) * 1.25
    ax.set_ylim(0, ymax)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.axvspan(cutoff.year - 0.5, years[-1] + 0.5, color="#f2f1ee", zorder=0)
    ax.text(cutoff.year - 0.45, ymax * 0.98, f"미공개 가능\n({cutoff.date()} 이후 출원)",
            ha="left", va="top", fontsize=7, color="#52514e")
    for x, y in zip(years, tot):
        ax.text(x, y, str(y), ha="center", va="bottom", fontsize=8, color="#0b0b0b")
    ax.set_xticks(years)
    ax.set_ylabel("출원 건수")
    ax.set_title("연도별 특허 출원 (출원일 기준)", loc="left", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e5e4df", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "fig1_yearly.png", dpi=200)
    plt.close(fig)


def fig_heat(table, title, fname, out, fmt="{:.0f}", cmap="Blues", norm=None, color_clip=None):
    t = table.drop(columns=[c for c in ("n",) if c in table.columns])
    fig, ax = plt.subplots(figsize=(1.0 + 0.9 * t.shape[1], 0.6 + 0.5 * t.shape[0]))
    cv = t.values.astype(float) if color_clip is None else np.clip(t.values.astype(float), *color_clip)
    ax.imshow(cv, cmap=cmap, aspect="auto", **({"norm": norm} if norm else {"vmin": 0}))
    ax.set_xticks(range(t.shape[1]), t.columns, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(t.shape[0]), t.index, fontsize=8)
    vmax = np.nanmax(t.values.astype(float)) if t.size else 1
    for i, j in itertools.product(range(t.shape[0]), range(t.shape[1])):
        v = t.values[i, j]
        if pd.notna(v):
            dark = abs(norm(cv[i, j]) - 0.5) > 0.35 if norm else v > vmax * 0.6
            ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=7,
                    color="white" if dark else "#0b0b0b")
    ax.set_title(title, loc="left", fontsize=10)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout()
    fig.savefig(out / fname, dpi=200)
    plt.close(fig)


def fig_network(co, out, fname="fig5_ipc_network.png", title="IPC 메인그룹 동시출현 네트워크 (2회 이상, 전 기간)"):
    if co.empty:
        return
    g = nx.Graph()
    for r in co.itertuples():
        g.add_edge(r.A, r.B, weight=r.count)
    fig, ax = plt.subplots(figsize=(7, 5.5))
    pos = nx.spring_layout(g, seed=7, weight="weight", k=1.2)
    deg = dict(g.degree(weight="weight"))
    w = [g[u][v]["weight"] for u, v in g.edges]
    nx.draw_networkx_edges(g, pos, width=[0.6 + 2.4 * x / max(w) for x in w], edge_color=C_GRAY, ax=ax)
    nx.draw_networkx_nodes(g, pos, node_size=[80 + 40 * deg[n] for n in g], node_color=C_BLUE,
                           edgecolors="white", linewidths=1.5, ax=ax)
    nx.draw_networkx_labels(g, pos, font_size=8, font_family="NanumGothic", ax=ax,
                            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.8))
    nx.draw_networkx_edge_labels(g, pos, edge_labels={(u, v): g[u][v]["weight"] for u, v in g.edges},
                                 font_size=7, font_color="#52514e", ax=ax)
    ax.set_title(title, loc="left", fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out / fname, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--asof", required=True, help="KIPRIS 추출일(YYYY-MM-DD) — 미공개 구간 계산용")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    df, cutoff = prepare(load(a.input), a.asof)
    if df.empty:
        raise SystemExit("대상 출원 0건 — 출원인명/기간 필터를 확인하세요.")

    vc = share_table(df, "vc", list(VALUE_CHAIN))
    tech = share_table(df, "tech", list(TECHNOLOGY))
    conv = convergence_index(df)
    ipc_sub = (df.explode("ipc_subclasses").groupby(["period", "ipc_subclasses"]).size()
               .unstack(0, fill_value=0))
    ipc_sub = ipc_sub.loc[ipc_sub.sum(axis=1).sort_values(ascending=False).index]
    co_ipc = cooccurrence(df, "ipc_groups")
    # 가치사슬 × 기술 교차표: 원 논문 2단계(관심분야 내 융합)의 사전 기반 대응물
    cross = {p: pd.DataFrame(0, index=list(VALUE_CHAIN), columns=list(TECHNOLOGY)) for p, *_ in PERIODS}
    for r in df.itertuples():
        for v, t in itertools.product(r.vc, r.tech):
            cross[r.period].loc[v, t] += 1
    kw = keyword_trend(df)
    unclassified = df[df["vc"].map(len).eq(0) | df["tech"].map(len).eq(0)][["app_no", "year", "title"]]

    with pd.ExcelWriter(out / "tables.xlsx") as xw:
        df.drop(columns=["text"]).assign(
            ipc_groups=df["ipc_groups"].str.join("; "), ipc_subclasses=df["ipc_subclasses"].str.join("; "),
            vc=df["vc"].str.join("; "), tech=df["tech"].str.join("; ")).to_excel(xw, sheet_name="00_원자료_분류결과", index=False)
        vc.round(1).to_excel(xw, sheet_name="01_가치사슬_비중")
        tech.round(1).to_excel(xw, sheet_name="02_기술요소_비중")
        conv.round(2).to_excel(xw, sheet_name="03_융합지표")
        ipc_sub.to_excel(xw, sheet_name="04_IPC서브클래스")
        co_ipc.round(3).to_excel(xw, sheet_name="05_IPC동시출현", index=False)
        for p, t in cross.items():
            t.to_excel(xw, sheet_name=f"06_교차_{p.split()[0]}")
        kw.round(1).to_excel(xw, sheet_name="07_키워드", index=False)
        unclassified.to_excel(xw, sheet_name="08_미분류_검토", index=False)

    fig_yearly(df, cutoff, out)
    fig_heat(vc.drop(columns=["(미분류)"]), "기간별 가치사슬 분야 비중(%, 다중라벨)", "fig2_valuechain.png", out)
    fig_heat(tech.drop(columns=["(미분류)"]), "기간별 기술요소 비중(%, 다중라벨)", "fig3_technology.png", out)
    total_cross = sum(cross.values())
    fig_heat(total_cross, "가치사슬 × 기술요소 동시부여 건수(전 기간)", "fig4_cross.png", out)
    fig_network(co_ipc, out)
    # 허브 코드(보험 BM특허의 G06Q 40 등)는 거의 모든 출원에 붙어 lift≈1의 자명한 연결만 만든다.
    # 허브를 뺀 네트워크가 실제 '융합' 신호를 보여준다.
    hub = Counter(g for gs in df["ipc_groups"] for g in gs).most_common(1)[0][0]
    fig_network(co_ipc[(co_ipc["A"] != hub) & (co_ipc["B"] != hub)], out, "fig6_ipc_network_nohub.png",
                f"IPC 동시출현 네트워크 — 허브({hub}) 제외")

    n = len(df)
    lines = [
        "# 분석 요약 (자동 생성 — 해석은 직접 기입)",
        f"- 대상: 출원인 {FOCAL_NAMES} 포함, 출원일 {PERIODS[0][1]}–{PERIODS[-1][2]}, **{n}건**"
        f" (등록 {int(df['registered'].sum())}건, 공동출원 {int(df['co_applied'].sum())}건)",
        f"- 추출일 {a.asof} 기준 출원 후 18개월 미경과(미공개 가능) 출원일: {cutoff.date()} 이후 → "
        f"해당 구간 {int(df['maybe_truncated'].sum())}건 관측, 실제보다 과소일 수 있음",
        f"- 가치사슬 미분류 {int(df['vc'].map(len).eq(0).sum())}건, 기술요소 미분류 "
        f"{int(df['tech'].map(len).eq(0).sum())}건 → 08_미분류_검토 시트 보고 taxonomy.py 보완",
        "", "## 기간별 표본", conv[["n"]].to_markdown(), "",
        "## 융합 지표", conv.drop(columns="n").round(1).to_markdown(), "",
        "## IPC 동시출현 상위 10 (기술통계, 유의성 검정 아님)",
        co_ipc.head(10).round(2).to_markdown(index=False) if not co_ipc.empty else "(2회 이상 쌍 없음)",
    ]
    if conv["n"].min() < 20:
        lines.insert(4, "- ⚠ 표본이 20건 미만인 기간이 있음: 해당 기간 비중(%)은 1건 차이로 크게 변동하므로 건수를 함께 제시할 것")
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
