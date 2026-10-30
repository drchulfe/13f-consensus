import sys
import koreanize_matplotlib  # noqa: F401
import matplotlib
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import pandas as pd

d = pd.read_csv(sys.argv[1])
groups = ["상품·요율·인수", "판매·청약", "보상", "계약관리·고객서비스", "내부업무·비보험"]
d["g"] = d["group"].map({g: i for i, g in enumerate(groups)})
d = d.sort_values(["g", "year"]).reset_index(drop=True)
style = {"등록 유지": dict(marker="o", s=90, facecolor="#2a78d6", edgecolor="white", lw=1.5),
         "등록 후 소멸": dict(marker="o", s=90, facecolor="white", edgecolor="#2a78d6", lw=2),
         "취하": dict(marker="X", s=90, facecolor="#8a8984", edgecolor="white", lw=1)}
fig, ax = plt.subplots(figsize=(9, 5))
ax.axvspan(2018.5, 2022.5, color="#f2f1ee", zorder=0)
ax.axvspan(2025.29, 2025.99, color="#e5e4df", zorder=0)
seen = {}
for i, r in d.iterrows():
    seen.setdefault(r.status_grp, ax.scatter(r.year, i, zorder=3, **style[r.status_grp]))
ax.set_yticks(range(len(d)), d["short"], fontsize=8)
ax.set_ylim(len(d) - 0.4, -1.4)
# 업무영역 구분선과 영역명
for g, sub in d.groupby("g", sort=True):
    top, bot = sub.index.min(), sub.index.max()
    if top > 0:
        ax.axhline(top - 0.5, color="#c3c2b7", lw=0.8)
    ax.text(2026.05, (top + bot) / 2, groups[g], fontsize=8, va="center", color="#52514e")
ax.text(2020.5, -1.0, "출원 0건 (2019–2022)", ha="center", va="center", fontsize=8, color="#52514e")
ax.text(2025.64, -1.0, "미공개\n가능", ha="center", va="center", fontsize=7, color="#52514e")
ax.set_xticks(range(2016, 2026))
ax.set_xlim(2015.5, 2026.0)
ax.tick_params(axis="x", labelsize=8)
ax.grid(axis="x", color="#eeede9", lw=0.6)
ax.set_axisbelow(True)
ax.spines[["top", "right", "left"]].set_visible(False)
ax.tick_params(axis="y", length=0)
ax.legend([seen[k] for k in style], list(style), fontsize=8, frameon=False, ncol=3,
          loc="upper left", bbox_to_anchor=(0, -0.08))
ax.set_title("DB손해보험 특허 출원 전수(11건): 출원연도 × 법적상태, 업무영역별", loc="left", fontsize=10)
fig.tight_layout()
fig.savefig(sys.argv[2], dpi=200, bbox_inches="tight")
