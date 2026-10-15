"""합성 말뭉치 스모크 테스트 — 실제 분석 결과가 아니다. 주제 비중이 연도별로 바뀌는
문서를 만들어, 파이프라인이 군집을 분리하고 비중 추세를 되살리는지만 확인한다."""
import os, random, sys

import numpy as np
import pytest

pytest.importorskip("kiwipiepy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cluster import run, log_entropy            # noqa: E402
from extract import business_section, paragraphs, load_text  # noqa: E402

TOPICS = {
    "auto": "자동차보험 손해율 정비수가 대물배상 교통사고 보상 차량 운전자 할인특약",
    "long": "장기보험 보장성보험 건강보험 실손의료비 암진단비 갱신 독립대리점 설계사 신계약",
    "ifrs": "보험계약마진 위험조정 보험서비스결과 투자서비스결과 할인율 측정모형 전환",
}


def synth(seed=1):
    rnd = random.Random(seed)
    docs = []
    for y in range(2016, 2026):
        w = {"auto": 1.0, "long": 1.0 + 0.3 * (y - 2016), "ifrs": 3.0 if y >= 2023 else 0.05}
        for _ in range(60):
            t = rnd.choices(list(w), weights=list(w.values()))[0]
            words = rnd.sample(TOPICS[t].split(), 6)
            docs.append((y, "당사는 " + " 및 ".join(words) + " 관련 사항을 관리한다"))
    return docs


def test_log_entropy_downweights_uniform_terms():
    from scipy import sparse
    X = sparse.csr_matrix(np.array([[1, 1, 0], [1, 0, 1], [1, 0, 0], [1, 1, 0]]))
    _, g = log_entropy(X)
    assert g[0] == pytest.approx(0.0) and g[2] == pytest.approx(1.0)


def test_pooled_recovers_trend():
    info, clusters, tab, notes, assign = run(synth(), mode="pooled", width=2, max_k=8)
    assert 3 <= info["k"] <= 8
    ifrs = [c for c, t in zip(clusters.cluster, clusters.terms) if "할인율" in t or "위험조정" in t or "보험계약마진" in t]
    assert ifrs
    share = tab.loc[ifrs].sum()
    assert share["2016-2017"] < 5 and share["2024-2025"] > 40


def test_per_period_runs():
    info, clusters, tab, *_ = run(synth(), mode="per-period", width=2, max_k=6)
    assert np.allclose(tab.sum().values, 100, atol=0.05)  # 소수 둘째 자리 반올림


def test_extract_dart_xml(tmp_path):
    xml = ("<DOCUMENT><TITLE>II. 사업의 내용</TITLE><TITLE>III. 재무에 관한 사항</TITLE>"
           "<SECTION-1><TITLE>II. 사업의 내용</TITLE><P>당사는 장기보험과 자동차보험, 일반보험을 영위하는 손해보험회사로서 "
           "보장성 상품 중심의 성장 전략을 추진하고 있습니다.</P><TABLE><TR><TD>1,234</TD></TR></TABLE>"
           "<P>2023</P></SECTION-1><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE><P>재무 내용입니다 길게 길게 길게 길게 길게 길게</P>"
           "</SECTION-1></DOCUMENT>")
    p = tmp_path / "2016.xml"; p.write_text(xml, encoding="utf-8")
    paras = paragraphs(business_section(load_text(str(p))))
    assert len(paras) == 1 and "장기보험" in paras[0]
