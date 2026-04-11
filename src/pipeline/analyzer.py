import json
import logging
import re

import anthropic

from src.config import settings

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """Analyze this Upwork job posting for a freelancer.

FREELANCER PROFILE:
- Name: {name}
- Skills: {skills}
- Experience Summary: {experience}
- Hourly Rate Range: ${rate_min}-${rate_max}/hr

JOB POSTING:
- Title: {title}
- Description: {description}
- Budget: {budget}
- Skills Required: {required_skills}
- Experience Level: {experience_level}
- Project Type: {job_type}
- Duration: {duration}
- Client Info: Payment Verified: {verified}, Total Spent: {spent}
- Proposals So Far: {proposals}

Analyze deeply and return ONLY a valid JSON object with no additional text or markdown:
{{
  "opportunity_score": <0-100 integer>,
  "relevance_score": <0-100 integer>,
  "client_quality": <0-100 integer>,
  "key_requirements": ["requirement 1", "requirement 2", "requirement 3"],
  "hidden_requirements": ["implicit need 1", "implicit need 2"],
  "matching_experience": ["relevant experience 1", "relevant experience 2"],
  "suggested_angle": "The best strategic approach for this proposal",
  "key_selling_points": ["selling point 1", "selling point 2"],
  "red_flags": ["any concerns or warnings"],
  "client_intent": "ready_to_hire|exploring|unclear|tire_kicker",
  "complexity_estimate": "low|medium|high",
  "should_propose": true,
  "reasoning": "Brief explanation of the score"
}}"""


class DeepAnalyzer:
    """
    LLM-powered job analysis.
    ~15-30 seconds, ~$0.01-0.03 per analysis.
    Uses Claude Sonnet 4 for best speed/quality/cost ratio.
    """

    def __init__(self, min_score: int | None = None):
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.min_score = min_score or settings.min_opportunity_score

    async def analyze(self, job: dict, profile: dict) -> dict:
        client_info = job.get("client_info") or {}
        if isinstance(client_info, str):
            try:
                client_info = json.loads(client_info)
            except Exception:
                client_info = {}

        description = job.get("description") or "No description provided."
        if len(description) > 3000:
            description = description[:3000] + "..."

        prompt = ANALYSIS_PROMPT.format(
            name=profile.get("name", "Freelancer"),
            skills=", ".join(profile.get("skills", [])),
            experience=profile.get("experience_summary", "Not provided"),
            rate_min=profile.get("rate_min", "N/A"),
            rate_max=profile.get("rate_max", "N/A"),
            title=job.get("title", ""),
            description=description,
            budget=job.get("budget") or "Not specified",
            required_skills=", ".join(job.get("skills", [])),
            experience_level=job.get("experience_level") or job.get("experienceLevel") or "Not specified",
            job_type=job.get("job_type") or job.get("jobType") or "Not specified",
            duration=job.get("duration") or "Not specified",
            verified=client_info.get("verificationStatus") or client_info.get("paymentVerified", "Unknown"),
            spent=client_info.get("totalSpent") or client_info.get("clientSpent", "Unknown"),
            proposals=job.get("proposals_count") or job.get("proposals", "Unknown"),
        )

        response = await self.client.messages.create(
            model=settings.llm_model,
            max_tokens=900,
            temperature=settings.analysis_temperature,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)
        result["should_propose"] = result.get("opportunity_score", 0) >= self.min_score
        return result
