import pytest

import originals as o


@pytest.fixture(autouse=True)
def _offline_crossref(monkeypatch):
    """Work-level scoring looks DOIs up on Crossref; tests stay offline."""
    monkeypatch.setattr(o, "_work_meta", lambda doi: {})


def test_double_slash_and_truncated_tail():
    assert o._canon("10.1037//0021-843X.108.3.511") == o._canon("10.1037/0021-843x.108.3.511")
    s = o.score_paper({"10.1111/j.1467-7687.2009.00859.x"}, {"10.1111/j.1467-7687.2009.00859"})
    assert not s["hit"] and s["hit_lenient"]


def test_set_scores_and_summary():
    a = o.score_paper({"10.1/a", "10.1/b"}, {"10.1/a", "10.1/c"})
    assert a["tp"] == 1 and a["recall"] == 0.5 and a["precision_lb"] == 0.5 and a["hit"] and not a["exact"]
    none = o.score_paper({"10.1/a"}, set())
    m = o.summarize([a, none])
    assert m["n_papers"] == 2 and m["extracted_none"] == 1 and m["hit_rate"] == 0.5
    assert abs(m["micro_recall"] - 1 / 3) < 1e-9


def test_same_work_merges_records_of_one_work_but_not_different_works():
    """Work-level equivalence (2026-10-15): an SSRN/NBER/PsycEXTRA/JSTOR record and
    the published article are one work; same authors' different papers are not."""
    pub = {"title": "CEO Compensation and Board Structure", "year": 2009, "first_family": "Chhaochharia"}
    ssrn = {"title": "CEO Compensation and Board Structure", "year": 2008, "first_family": "Chhaochharia"}
    assert o.same_work(pub, ssrn)
    psycextra = {"title": "When cheating would make you 'a cheater': Noun wording prevents unethical behavior",
                 "year": 2013, "first_family": "Bryan"}
    jep = {"title": "When cheating would make you a cheater: Implicating the self prevents unethical behavior",
           "year": 2013, "first_family": "Bryan"}
    assert o.same_work(psycextra, jep)               # same main title, same author
    other = {"title": "Spontaneous trait inferences", "year": 2009, "first_family": "Chhaochharia"}
    assert not o.same_work(pub, other)               # same author, different work
    late = dict(ssrn, year=2001)
    assert not o.same_work(pub, late)                # too far apart in time
    assert not o.same_work(pub, {})                  # unregistered (fabricated) DOI


def test_work_matches_uses_registered_metadata(monkeypatch):
    meta = {"10.2139/ssrn.901642": {"title": "CEO Compensation and Board Structure", "year": 2008,
                                    "first_family": "Chhaochharia"},
            "10.1111/j.1540-6261.2008.01433.x": {"title": "CEO Compensation and Board Structure", "year": 2009,
                                                 "first_family": "Chhaochharia"},
            "10.1111/fake.123": {}}
    monkeypatch.setattr(o, "_work_meta", lambda d: meta.get(d, {}))
    gt = {"10.2139/ssrn.901642"}
    assert o.work_matches(gt, {"10.1111/j.1540-6261.2008.01433.x"}) == gt
    assert o.work_matches(gt, {"10.1111/fake.123"}) == set()
    rec = o.score_paper(gt, {"10.1111/j.1540-6261.2008.01433.x"})
    assert rec["hit"] is False and rec["hit_work"] is True
