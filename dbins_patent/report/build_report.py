"""분석 결과(엑셀·CSV)를 읽어 실무보고서 HTML을 만든다. 숫자는 모두 파일에서 읽는다."""
import html
import math
import sys
from pathlib import Path

import pandas as pd

S = Path(sys.argv[1])            # scratchpad
OUT = Path(sys.argv[2])
X = S / "out_a" / "industry_tables.xlsx"
CODING = S / "report_c" / "coding.csv"

d = pd.read_excel(X, sheet_name="00_원자료_분류결과", dtype=str)
d["g"] = d["ipc_groups"].fillna("").str.split("; ").map(set)
d["year"] = d["year"].astype(int)
cl = pd.read_excel(X, sheet_name="01_군집_기간별비중", index_col=0)
rules = pd.read_excel(X, sheet_name="03_연관규칙")
firm_cl = pd.read_excel(X, sheet_name="05_기업x군집_건수", index_col=0)
rta = pd.read_excel(X, sheet_name="06_기업x군집_RTA", index_col=0)
entry = pd.read_excel(X, sheet_name="07_군집_최초진입연도", index_col=0)
coding = pd.read_csv(CODING, dtype={"app_no": str})

PER = ["P1 2016–19", "P2 2020–22", "P3 2023–25"]
NAME = {  # 자동 대표어 → 내용 기준 해석 이름(분석자 판단)
    "C00": "설계사·고객 관리", "C01": "상품·보장 설계(일반)", "C02": "상담·전자문서·음성",
    "C03": "AI 예측 모델", "C04": "대리점·영업관리", "C05": "운전 안전·운전자 위험",
    "C06": "자동차 사고·보험료", "C07": "고지·상병 인수심사", "C08": "이미지·문장 인식",
}
IPC = {"G06Q 40": "금융·보험", "G06Q 50": "업종 특화 시스템", "G06Q 10": "관리·업무", "G06Q 30": "상거래",
       "G06V 10": "이미지 인식", "G06V 20": "장면·영상 인식", "G06F 16": "정보검색·DB", "G06N 20": "기계학습",
       "G06N 3": "신경망", "H04W 4": "무선 위치 서비스", "G07C 5": "차량 운행기록", "G16H 10": "환자 데이터",
       "G16H 50": "의료 데이터 분석", "H04L 51": "메시징", "G06F 40": "자연어 처리", "G10L 15": "음성 인식",
       "G06F 21": "보안·인증"}
e = html.escape


def cid(c):
    return c.split()[0]


def firms_behind(items, cluster, period):
    s = d[(d["cluster"] == cluster) & (d["period"] == period) & d["g"].map(lambda g: set(items) <= g)]
    cnt = {}
    for fs in s["firms"]:
        for f in fs.split("; "):
            cnt[f] = cnt.get(f, 0) + 1
    return ", ".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]))


def ipc_label(side):
    return " + ".join(f'<span class="ipc">{e(c)}</span><small>{e(IPC.get(c, ""))}</small>' for c in side.split(" + "))


# ---------- 1. 연도별 출원(삼성 2사 vs 그 외)
d["samsung"] = d["firms"].str.contains("삼성")
yr = d.groupby(["year", "samsung"]).size().unstack(fill_value=0).reindex(range(2016, 2026), fill_value=0)
ymax = int(yr.sum(axis=1).max())
bars = []
for y, r in yr.iterrows():
    sam, oth = int(r.get(True, 0)), int(r.get(False, 0))
    tot = sam + oth
    trunc = ' trunc' if y == 2025 else ''
    bars.append(
        f'<div class="col{trunc}" role="img" aria-label="{y}년 {tot}건(삼성 {sam}, 그 외 {oth})">'
        f'<span class="tot">{tot}</span>'
        f'<div class="stack" style="height:{tot / ymax * 100:.1f}%">'
        f'<i class="seg oth" style="flex:{oth}"></i><i class="seg sam" style="flex:{sam}"></i></div>'
        f'<span class="yr">{y}</span></div>')
n_total, n_sam = len(d), int(d["samsung"].sum())

# ---------- 2. 기업별 출원(공동출원 중복계상)
firm_tot = firm_cl.sum(axis=1).sort_values(ascending=False)
firm_tot["흥국화재"] = 0
fmax = firm_tot.max()
firm_rows = "".join(
    f'<div class="hrow{" focal" if f == "DB손보" else ""}"><span class="hl">{e(f)}</span>'
    f'<span class="htrack"><i style="width:{v / fmax * 100:.1f}%"></i></span><span class="hv">{int(v)}</span></div>'
    for f, v in firm_tot.items())

# ---------- 3. 군집 비중 히트 테이블
pct = cl[[p + " (%)" for p in PER]]
cnt = cl[PER]
growth = pct[PER[-1] + " (%)"] - pct[PER[0] + " (%)"]
order = growth.sort_values(ascending=False).index
pmax = pct.values.max()
crow = []
for c in order:
    top_firm = firm_cl[c].idxmax()
    top_share = firm_cl[c].max() / firm_cl[c].sum() * 100
    cells = "".join(
        f'<td class="heat" style="--v:{pct.loc[c, p + " (%)"] / pmax * 85:.0f}">'
        f'{pct.loc[c, p + " (%)"]:.0f}<small>{int(cnt.loc[c, p])}건</small></td>' for p in PER)
    g = growth[c]
    crow.append(f'<tr><th scope="row">{e(NAME[cid(c)])}<small>{e(c)}</small></th>{cells}'
                f'<td class="num {"up" if g > 0 else "down"}">{g:+.1f}</td>'
                f'<td>{e(top_firm)} {top_share:.0f}%</td></tr>')
per_n = d.groupby("period").size()

# ---------- 4. 핵심 융합 규칙(동시출현 3건 이상, 대표 규칙만)
pick = [("C06", "P3 2023–25", "G06V 10 → G06Q 40 + G06Q 50 + G06V 20"),
        ("C06", "P3 2023–25", "H04W 4 → G07C 5"),
        ("C06", "P3 2023–25", "G06F 16 + G06Q 40 → G06N 20 + G06Q 50"),
        ("C03", "P3 2023–25", "G06Q 40 + G06Q 50 → G06F 16"),
        ("C03", "P2 2020–22", "G06N 3 → G16H 10"),
        ("C04", "P3 2023–25", "H04L 51 → G06Q 10 + G06Q 40")]
rrows = []
for c, p, rule in pick:
    r = rules[(rules["cluster"].str.startswith(c)) & (rules["period"] == p) & (rules["rule"] == rule)]
    if r.empty:
        continue
    r = r.iloc[0]
    lhs, rhs = rule.split(" → ")
    items = lhs.split(" + ") + rhs.split(" + ")
    who = firms_behind(items, r["cluster"], p)
    focal = " focal" if "DB손보" in who else ""
    rrows.append(f'<tr class="{focal.strip()}"><td>{e(NAME[c])}<small>{e(p)}</small></td>'
                 f'<td class="rule">{ipc_label(lhs)} <b>→</b> {ipc_label(rhs)}</td>'
                 f'<td class="num">{int(r["count"])}</td><td class="num">{r["confidence"]:.2f}</td>'
                 f'<td class="num">{r["lift"]:.2f}</td><td>{e(who)}</td></tr>')
n_rules, n_rules3 = len(rules), int((rules["count"] >= 3).sum())

# ---------- 5. RTA (출원 9건 이상 기업)
firm_n = firm_cl.sum(axis=1)
big = firm_n[firm_n >= 9].sort_values(ascending=False).index
cols = [c for c in order]
rta_head = "".join(f'<th scope="col">{e(NAME[cid(c)])}</th>' for c in cols)
rta_rows = []
for f in big:
    cells = []
    for c in cols:
        v, k = rta.loc[f, c], int(firm_cl.loc[f, c])
        if k == 0:
            cells.append('<td class="rta none">–</td>')
        else:
            t = max(-1, min(1, math.log(v, 3)))  # 1/3 ↔ 3을 −1 ↔ 1로
            cls = "pos" if t > 0 else "neg"
            cells.append(f'<td class="rta {cls}" style="--t:{abs(t) * 70:.0f}">{v:.1f}<small>{k}</small></td>')
    rta_rows.append(f'<tr class="{"focal" if f == "DB손보" else ""}"><th scope="row">{e(f)}'
                    f'<small>{int(firm_n[f])}건</small></th>{"".join(cells)}</tr>')

# ---------- 6. DB손보 11건
db = d[d["firms"].str.contains("DB손보")][["app_no", "cluster"]]
cd = coding.merge(db, on="app_no", how="left")
status_cls = {"등록 유지": "ok", "등록 후 소멸": "lapsed", "취하": "wd"}
db_rows = "".join(
    f'<tr><td class="num">{r.year}</td><td>{e(r.short)}</td><td>{e(r.group)}</td><td>{e(r.tech)}</td>'
    f'<td><span class="pill {status_cls[r.status_grp]}">{e(r.status_grp)}</span></td>'
    f'<td>{e(NAME[cid(r.cluster)])}</td></tr>' for r in cd.sort_values("year").itertuples())
early, late = cd[cd.year <= 2018], cd[cd.year >= 2023]
db_entry_c06, sf_entry_c06 = int(entry.loc["DB손보"].filter(like="C06").iloc[0]), int(entry.loc["삼성화재"].filter(like="C06").iloc[0])


# ================= B안: G06Q 40/08 생태계 =================
XB = S / "out_b" / "ecosystem_tables.xlsx"
XBB = S / "out_b_broad" / "ecosystem_tables.xlsx"
db_ = pd.read_excel(XB, sheet_name="00_원자료", dtype=str)
db_["g"] = db_["ipc_groups"].fillna("").str.split("; ").map(set)
actor = pd.read_excel(XB, sheet_name="02_주체유형x기간", index_col=0)
opp = pd.read_excel(XB, sheet_name="07_DB_기회맵", index_col=0)
sim = pd.read_excel(XB, sheet_name="08_DB_유사출원인", index_col=0)
rulesB = pd.read_excel(XB, sheet_name="06_연관규칙")
concB = pd.read_excel(XB, sheet_name="01_생태계_규모·집중도", index_col=0)
concBB = pd.read_excel(XBB, sheet_name="01_생태계_규모·집중도", index_col=0)
NAMEB = {"C00": "보험금 청구·진료(실손)", "C01": "반려동물 보험", "C02": "AI 예측 모델", "C03": "계약·지급 관리(일반)",
         "C04": "운행·운전습관", "C05": "상품 추천·설계", "C06": "의료기관·환자 데이터", "C07": "설계사·고객 상담",
         "C08": "차량 사고", "C09": "건강 위험 예측", "C10": "자동차보험 중개·거래", "C11": "연금·퇴직"}
GROUP = {"보험사": "보험사", "인슈어테크": "인슈어테크", "헬스케어·의료IT": "헬스케어·의료IT", "모빌리티·제조": "모빌리티·제조",
         "IT·플랫폼": "IT·플랫폼·금융", "금융(은행·카드·증권)": "IT·플랫폼·금융", "개인": "개인"}
GORDER = ["보험사", "인슈어테크", "헬스케어·의료IT", "모빌리티·제조", "IT·플랫폼·금융", "그 외 기업·기관", "개인"]
GCLS = ["g1", "g2", "g3", "g4", "g5", "g6", "g7"]
ag = actor.T.groupby(lambda t: GROUP.get(t, "그 외 기업·기관")).sum().T.reindex(columns=GORDER, fill_value=0)
agp = ag.div(ag.sum(axis=1), axis=0) * 100
actor_rows = []
for per, r in agp.iterrows():
    segs = "".join(f'<i class="aseg {GCLS[i]}" style="flex:{r[g]:.2f}" title="{e(g)} {r[g]:.1f}%">'
                   f'{f"<b>{r[g]:.0f}</b>" if r[g] >= 7 else ""}</i>' for i, g in enumerate(GORDER))
    actor_rows.append(f'<div class="arow"><span class="al">{e(per)}<small>{int(ag.loc[per].sum())}건</small></span>'
                      f'<span class="atrack">{segs}</span></div>')
actor_legend = "".join(f'<span><i class="{GCLS[i]}"></i>{e(g)}</span>' for i, g in enumerate(GORDER))
ins_share = agp["보험사"]; tech_share = agp["인슈어테크"]

o = opp.sort_values("share_change_pp", ascending=False)
quad_cls = {"성장×특화": "q1", "성장×열위": "q2", "정체×특화": "q3", "정체×열위": "q4"}
eco_rows = []
for c, r in o.iterrows():
    dbn = int(r["DB_n"])
    eco_rows.append(
        f'<tr class="{"focal" if dbn else ""}"><th scope="row">{e(NAMEB[cid(c)])}<small>{e(c)}</small></th>'
        f'<td class="num">{int(r["n"])}</td><td class="num">{r["share_P1(%)"]:.1f}</td><td class="num">{r["share_P3(%)"]:.1f}</td>'
        f'<td class="num {"up" if r["share_change_pp"] > 0 else "down"}">{r["share_change_pp"]:+.1f}</td>'
        f'<td class="num">{r["보험사 비중(%)"]:.0f}</td><td class="num">{dbn}</td>'
        f'<td class="num">{(f"{r.DB_RTA:.1f}" if dbn else "–")}</td>'
        f'<td><span class="quad {quad_cls[r["사분면"]]}">{e(r["사분면"])}</span></td></tr>')

def firms_behind_b(items, cluster, period):
    s_ = db_[(db_["cluster"] == cluster) & (db_["period"] == period) & db_["g"].map(lambda g: set(items) <= g)]
    cnt = {}
    for fs in s_["applicants"]:
        for f in fs.split("; "):
            cnt[f] = cnt.get(f, 0) + 1
    top = sorted(cnt.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{k.replace('주식회사', '').strip()} {v}" for k, v in top[:3]) + (f" 외 {len(top) - 3}곳" if len(top) > 3 else "")

pickB = [("C02", "P2 2020–22", "G16H 50 → G06Q 40 + G16H 10"),
         ("C02", "P2 2020–22", "G06N 20 + G16H 10 → G06Q 40 + G16H 50"),
         ("C02", "P3 2023–25", "G06N 3 + G06Q 30 → G06Q 40 + G06Q 50"),
         ("C03", "P1 2016–19", "G06F 21 → G06Q 40 + H04L 9")]
IPC.update({"H04L 9": "암호·블록체인", "G06Q 20": "결제"})
rrowsB = []
for c, p, rule in pickB:
    r = rulesB[(rulesB["cluster"].str.startswith(c)) & (rulesB["period"] == p) & (rulesB["rule"] == rule)]
    if r.empty:
        continue
    r = r.iloc[0]
    lhs, rhs = rule.split(" → ")
    rrowsB.append(f'<tr><td>{e(NAMEB[c])}<small>{e(p)}</small></td><td class="rule">{ipc_label(lhs)} <b>→</b> {ipc_label(rhs)}</td>'
                  f'<td class="num">{int(r["count"])}</td><td class="num">{r["confidence"]:.2f}</td><td class="num">{r["lift"]:.2f}</td>'
                  f'<td>{e(firms_behind_b(lhs.split(" + ") + rhs.split(" + "), r["cluster"], p))}</td></tr>')
sim_rows = "".join(f'<tr><td>{e(a.replace("주식회사", "").strip())}</td><td>{e(r["type"])}</td><td class="num">{int(r["n"])}</td>'
                   f'<td class="num">{r["코사인유사도"]:.2f}</td></tr>' for a, r in sim.head(6).iterrows())
ai = o.loc[[c for c in o.index if c.startswith("C02")][0]]
c02 = db_[db_["cluster"].str.startswith("C02")]
ai_ins = c02.groupby("period")["actor_types"].apply(lambda s_: s_.str.contains("보험사").mean() * 100)

tmpl = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
out = (tmpl.replace("{{BARS}}", "".join(bars)).replace("{{N_TOTAL}}", str(n_total))
       .replace("{{N_SAM}}", str(n_sam)).replace("{{SAM_PCT}}", f"{n_sam / n_total * 100:.1f}")
       .replace("{{FIRM_ROWS}}", firm_rows).replace("{{CLUSTER_ROWS}}", "".join(crow))
       .replace("{{P1N}}", str(per_n[PER[0]])).replace("{{P2N}}", str(per_n[PER[1]])).replace("{{P3N}}", str(per_n[PER[2]]))
       .replace("{{RULE_ROWS}}", "".join(rrows)).replace("{{N_RULES}}", str(n_rules)).replace("{{N_RULES3}}", str(n_rules3))
       .replace("{{RTA_HEAD}}", rta_head).replace("{{RTA_ROWS}}", "".join(rta_rows))
       .replace("{{DB_ROWS}}", db_rows)
       .replace("{{EARLY_N}}", str(len(early))).replace("{{EARLY_KEEP}}", str(int((early.status_grp == "등록 유지").sum())))
       .replace("{{LATE_N}}", str(len(late))).replace("{{LATE_KEEP}}", str(int((late.status_grp == "등록 유지").sum())))
       .replace("{{DB_C06}}", str(db_entry_c06)).replace("{{SF_C06}}", str(sf_entry_c06))
       .replace("{{B_N}}", str(int(concB["출원 건수"].sum()))).replace("{{B_APPS}}", f"{len(set(a for x in db_['applicants'] for a in x.split('; '))):,}")
       .replace("{{ACTOR_ROWS}}", "".join(actor_rows)).replace("{{ACTOR_LEGEND}}", actor_legend)
       .replace("{{INS1}}", f"{ins_share.iloc[0]:.0f}").replace("{{INS2}}", f"{ins_share.iloc[1]:.0f}").replace("{{INS3}}", f"{ins_share.iloc[2]:.0f}")
       .replace("{{TECH1}}", f"{tech_share.iloc[0]:.0f}").replace("{{TECH3}}", f"{tech_share.iloc[2]:.0f}")
       .replace("{{ECO_ROWS}}", "".join(eco_rows)).replace("{{RULEB_ROWS}}", "".join(rrowsB)).replace("{{SIM_ROWS}}", sim_rows)
       .replace("{{AI_P1}}", f"{ai['share_P1(%)']:.1f}").replace("{{AI_P3}}", f"{ai['share_P3(%)']:.1f}")
       .replace("{{AI_INS1}}", f"{ai_ins.iloc[0]:.0f}").replace("{{AI_INS3}}", f"{ai_ins.iloc[-1]:.0f}")
       .replace("{{BB_N}}", str(int(concBB["출원 건수"].sum())))
       .replace("{{BB_INS1}}", f"{concBB['보험사 비중(%)'].iloc[0]:.0f}").replace("{{BB_INS2}}", f"{concBB['보험사 비중(%)'].iloc[1]:.0f}").replace("{{BB_INS3}}", f"{concBB['보험사 비중(%)'].iloc[2]:.0f}")
       .replace("{{HHI1}}", f"{concB['HHI(출원인)'].min():.0f}").replace("{{HHI3}}", f"{concB['HHI(출원인)'].max():.0f}"))
assert "{{" not in out, [l for l in out.splitlines() if "{{" in l][:3]
OUT.write_text(out, encoding="utf-8")
print("written", OUT, len(out))
