import json
import logging
import re

import anthropic

from src.config import settings

logger = logging.getLogger(__name__)

GENERATION_PROMPT = """Write an Upwork proposal for {name}.

VOICE GUIDE:
{tone_description}

EXAMPLE WINNING PROPOSALS (match this style and tone):
---
{sample_proposals}
---

THE JOB:
Title: {title}
Key Requirements:
{requirements}
Hidden Requirements:
{hidden_requirements}
Client Intent: {intent}
Complexity: {complexity}

YOUR MATCHING EXPERIENCE:
{experience}

BEST STRATEGIC ANGLE: {angle}
KEY SELLING POINTS:
{selling_points}

RULES:
1. Open by referencing a SPECIFIC detail from the job — never "I'm excited about" or "I'd love to"
2. Show you understand their REAL problem, not just what they listed
3. Connect 2-3 past experiences with concrete results (numbers, outcomes)
4. Suggest a specific first step that shows you've already started thinking about their problem
5. End with a low-pressure call to action + 1 thoughtful question demonstrating expertise
6. Under {max_words} words — every word must earn its place
7. Sound like {name}, not a robot — use the example proposals above as your style guide
8. FORBIDDEN phrases: "I'd love to", "I'm the perfect fit", "I believe I can",
   "Dear Hiring Manager", "With X years of experience", "I am very interested"
9. Short paragraphs. No bullet points unless the client's post heavily uses them.
10. Build trust through specificity, not through claims about yourself.

Write ONLY the proposal text, nothing else:"""

QUALITY_CHECK_PROMPT = """Rate this Upwork proposal on a scale of 1-10.

Job Title: {title}
Proposal:
{proposal}

Evaluate these three dimensions:
1. SPECIFICITY — Does it reference specific details from the job? (not generic)
2. PERSUASIVENESS — Does it make the client want to respond?
3. AUTHENTICITY — Does it sound like a real human, not AI?

Return ONLY a valid JSON object:
{{"score": <1-10 average>, "specificity": <1-10>, "persuasiveness": <1-10>,
  "authenticity": <1-10>, "feedback": "What to improve"}}"""


class ProposalGenerator:
    """
    Generates personalized proposals using the freelancer's voice.
    ~30-60 seconds, ~$0.02-0.04 per proposal.
    Includes quality self-check with regeneration.
    """

    def __init__(self, min_quality: float | None = None):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.min_quality = min_quality or settings.min_proposal_quality

    async def generate(self, job: dict, analysis: dict, profile: dict) -> dict:
        prompt = GENERATION_PROMPT.format(
            name=profile.get("name", "Freelancer"),
            tone_description=profile.get("tone_description", "Professional, concise, confident."),
            sample_proposals="\n---\n".join((profile.get("sample_proposals") or [])[:3]) or "No examples provided.",
            title=job.get("title", ""),
            requirements="\n".join(f"- {r}" for r in analysis.get("key_requirements", [])) or "- (none listed)",
            hidden_requirements="\n".join(f"- {r}" for r in analysis.get("hidden_requirements", [])) or "- (none)",
            intent=analysis.get("client_intent", "unknown"),
            complexity=analysis.get("complexity_estimate", "medium"),
            experience="\n".join(f"- {e}" for e in analysis.get("matching_experience", [])) or "- (none specified)",
            angle=analysis.get("suggested_angle", ""),
            selling_points="\n".join(f"- {p}" for p in analysis.get("key_selling_points", [])) or "- (none listed)",
            max_words=profile.get("max_proposal_words", 200),
        )

        response = await self.client.messages.create(
            model=settings.llm_model,
            max_tokens=1200,
            temperature=settings.generation_temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        proposal_text = response.content[0].text.strip()

        # Quality self-check
        quality = await self._quality_check(proposal_text, job)

        # Regenerate once if below threshold
        if quality["score"] < self.min_quality:
            logger.info(f"Proposal quality {quality['score']:.1f} < {self.min_quality} — regenerating")
            proposal_text = await self._regenerate(proposal_text, quality["feedback"], job, analysis, profile)
            quality = await self._quality_check(proposal_text, job)

        return {
            "text": proposal_text,
            "quality_score": quality["score"],
            "quality_detail": quality,
            "word_count": len(proposal_text.split()),
        }

    async def _quality_check(self, proposal: str, job: dict) -> dict:
        response = await self.client.messages.create(
            model=settings.llm_model,
            max_tokens=200,
            temperature=settings.quality_check_temperature,
            messages=[{"role": "user", "content": QUALITY_CHECK_PROMPT.format(
                title=job.get("title", ""), proposal=proposal
            )}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except Exception:
            return {"score": 0, "feedback": "Quality check parse failed"}

    async def _regenerate(self, original: str, feedback: str, job: dict, analysis: dict, profile: dict) -> str:
        response = await self.client.messages.create(
            model=settings.llm_model,
            max_tokens=1200,
            temperature=settings.generation_temperature,
            messages=[{"role": "user", "content": f"""Rewrite this Upwork proposal.

FEEDBACK TO ADDRESS: {feedback}

ORIGINAL PROPOSAL:
{original}

JOB TITLE: {job.get('title', '')}
KEY REQUIREMENTS: {', '.join(analysis.get('key_requirements', []))}

Keep under {profile.get('max_proposal_words', 200)} words.
Write in {profile.get('name', 'Freelancer')}'s voice.
Write ONLY the improved proposal:"""}],
        )
        return response.content[0].text.strip()
