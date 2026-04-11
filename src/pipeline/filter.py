import json
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FilterPreferences:
    skills: list[str] = field(default_factory=list)
    min_skill_overlap: int = 1
    min_budget: float = 0.0
    require_payment_verified: bool = True
    min_client_spent: float = 0.0
    max_existing_proposals: int = 50
    blacklist_keywords: list[str] = field(default_factory=lambda: [
        "unpaid trial", "free test", "equity only",
        "no budget", "volunteer", "intern",
    ])


class QuickFilter:
    """
    Rule-based filter. Runs in < 500ms. No API calls.
    Saves LLM costs by rejecting obviously poor matches early.
    """

    def __init__(self, prefs: FilterPreferences):
        self.prefs = prefs

    def evaluate(self, job: dict) -> tuple[bool, str]:
        """Returns (passes: bool, reason: str)."""

        # 1. Budget floor
        budget = self._parse_budget(job.get("budget"))
        if budget is not None and budget < self.prefs.min_budget:
            return False, f"Budget ${budget:.0f} below minimum ${self.prefs.min_budget:.0f}"

        # 2. Payment verification
        if self.prefs.require_payment_verified:
            client = self._coerce_dict(job.get("client_info"))
            verified = client.get("verificationStatus") or client.get("paymentVerified")
            if verified in (False, "UNVERIFIED", "false", 0):
                return False, "Payment not verified"

        # 3. Skill overlap
        job_skills = set(s.lower().strip() for s in (job.get("skills") or []))
        my_skills = set(s.lower().strip() for s in self.prefs.skills)
        if job_skills and my_skills:
            overlap = job_skills & my_skills
            if len(overlap) < self.prefs.min_skill_overlap:
                return False, f"Only {len(overlap)} matching skills (need {self.prefs.min_skill_overlap})"

        # 4. Blacklist keywords
        text = f"{job.get('title', '')} {job.get('description', '')}".lower()
        for word in self.prefs.blacklist_keywords:
            if word.lower() in text:
                return False, f"Blacklisted keyword: '{word}'"

        # 5. Existing proposals count
        proposals = self._parse_number(job.get("proposals_count") or job.get("proposals"))
        if proposals is not None and proposals > self.prefs.max_existing_proposals:
            return False, f"Already {proposals} proposals (max {self.prefs.max_existing_proposals})"

        # 6. Client spend minimum
        client = self._coerce_dict(job.get("client_info"))
        spent = self._parse_money(client.get("totalSpent") or client.get("clientSpent"))
        if spent is not None and spent < self.prefs.min_client_spent:
            return False, f"Client spent ${spent:.0f} (minimum ${self.prefs.min_client_spent:.0f})"

        return True, "Passed all filters"

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _parse_budget(self, budget) -> float | None:
        if not budget:
            return None
        if isinstance(budget, dict):
            return budget.get("amount") or budget.get("min")
        match = re.search(r'[\$]?([\d,]+)', str(budget))
        return float(match.group(1).replace(",", "")) if match else None

    def _parse_number(self, val) -> int | None:
        if not val:
            return None
        match = re.search(r"(\d+)", str(val))
        return int(match.group(1)) if match else None

    def _parse_money(self, val) -> float | None:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        text = str(val).lower().replace(",", "").replace("$", "").strip()
        if "k" in text:
            match = re.search(r"([\d.]+)", text)
            return float(match.group(1)) * 1000 if match else None
        match = re.search(r"([\d.]+)", text)
        return float(match.group(1)) if match else None

    @staticmethod
    def _coerce_dict(val) -> dict:
        if isinstance(val, dict):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                pass
        return {}
