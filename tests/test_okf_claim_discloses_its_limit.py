"""The OKF evidence row must disclose that retrieval sufficiency was assumed, not measured.

`evals/m4-okf/run_okf_eval.py` measures one thing: the token cost of loading context under four
strategies. Its docstring says so plainly ("measure the token cost of answering knowledge
questions four ways"). It contains no assertion that any strategy actually answers correctly.

The `needed` field in each question declares which concepts index-first has to retrieve. That
list is written by the eval author. The eval then measures the cost of retrieving exactly it.
Sufficiency is the premise, not the finding. If index-first would miss a concept that matters,
this eval cannot detect it, because `needed` is the index-first answer treated as ground truth.

The 31x figure is correct as a cost measurement. The risk is where it sits: an evidence table
whose other rows report resolved rates and silent-failure counts, which are outcome measures. A
reader carries that framing across and reads 31x as "index-first is better" rather than
"index-first is cheaper, assuming it retrieves enough".

Same failure shape as the phoenix_accept overclaim in #148: a true narrow claim standing where
it reads as a broad one. This guard keeps the qualifier attached to the number.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
OKF_RESULT = REPO_ROOT / "evals" / "m4-okf" / "RESULT.md"
OKF_EVAL = REPO_ROOT / "evals" / "m4-okf" / "run_okf_eval.py"

_DISCLOSURE = re.compile(
    r"sufficien\w*[^.|]{0,90}(assum|not measur|unmeasur)"
    r"|(assum|not measur|unmeasur)\w*[^.|]{0,90}sufficien",
    re.IGNORECASE,
)


def _okf_row(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("|") and "m4-okf" in line:
            return line
    raise AssertionError("README no longer has an OKF evidence-table row")


def test_readme_okf_row_discloses_that_sufficiency_was_assumed():
    row = _okf_row(README.read_text(encoding="utf-8"))
    assert _DISCLOSURE.search(row), (
        "The OKF row reports a token-cost ratio in a table whose other rows report outcome "
        "measures. Its scope cell must say that retrieval sufficiency was assumed rather than "
        f"measured, or the number reads as a quality claim it does not support. Row was: {row}"
    )


def test_okf_result_discloses_that_sufficiency_was_assumed():
    text = OKF_RESULT.read_text(encoding="utf-8")
    assert _DISCLOSURE.search(text), (
        "evals/m4-okf/RESULT.md must state that the eval measures token cost and assumes "
        "retrieval sufficiency. It already carries an 'Honest negative' about grep being "
        "competitive; the assumed-sufficiency limit belongs alongside it."
    )


def test_the_eval_still_only_measures_cost():
    """Pins the premise. If someone adds a real correctness check, this guard must be revisited.

    Deliberately structural. It fails when the eval starts comparing answers, which is the
    signal that the disclosure above is out of date and the honest limit can be narrowed.
    """
    src = OKF_EVAL.read_text(encoding="utf-8")
    assert "needed" in src, "eval no longer declares a `needed` set; revisit the disclosure"
    assert not re.search(r"^\s*assert\s", src, re.MULTILINE), (
        "run_okf_eval.py now contains assertions. If it verifies answer correctness, the "
        "assumed-sufficiency disclosure in README.md and RESULT.md should be narrowed to match "
        "what the eval now proves."
    )
