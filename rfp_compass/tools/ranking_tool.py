"""Stable deterministic ranking and human-readable tie-break explanations."""

from __future__ import annotations

from datetime import date
from typing import Any


class RankingTool:
    """Rank by compliance lane, PPI, date, experience, and ascending name."""

    def rank(self, suppliers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = [dict(s) for s in suppliers]
        rows.sort(key=lambda s: (not bool(s.get("compliant", True)), -float(s.get("ppi", 0)),
                                 self._date(s.get("submission_date")), -float(s.get("experience_rating", 0)),
                                 str(s.get("supplier_name", "")).casefold()))
        for i, row in enumerate(rows, 1):
            row["rank"] = i
            row["tie_break_explanation"] = ""
        for left, right in zip(rows, rows[1:]):
            if abs(float(left.get("ppi", 0)) - float(right.get("ppi", 0))) < 1e-12:
                left["tie_break_explanation"] = self.explain(left, right)
                right["tie_break_explanation"] = self.explain(right, left)
        return rows

    @staticmethod
    def _date(value: Any) -> str:
        if isinstance(value, date):
            return value.isoformat()
        return str(value or "9999-12-31")

    @staticmethod
    def explain(a: dict[str, Any], b: dict[str, Any]) -> str:
        if bool(a.get("compliant", True)) != bool(b.get("compliant", True)):
            return "Mandatory gate policy places compliant suppliers above non-compliant suppliers."
        if float(a.get("ppi", 0)) != float(b.get("ppi", 0)):
            return f"{a['supplier_name']} ranks by higher PPI ({a['ppi']:.4f} vs {b['ppi']:.4f})."
        da, db = RankingTool._date(a.get("submission_date")), RankingTool._date(b.get("submission_date"))
        if da != db:
            return f"Equal PPI; earlier submission date ({da} before {db}) breaks the tie."
        ea, eb = float(a.get("experience_rating", 0)), float(b.get("experience_rating", 0))
        if ea != eb:
            return f"Equal PPI and date; higher experience rating ({ea:g} vs {eb:g}) breaks the tie."
        return f"Equal PPI, date, and experience; supplier name ascending ({a['supplier_name']} before {b['supplier_name']}) breaks the tie."
