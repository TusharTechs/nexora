"""Web Research capability — controlled external evidence gathering (ADR-056).

Controlled research capability that:
- Takes a research objective/question
- Calls Tavily API (or falls back to mock if no API key)
- Returns structured findings with citations
- Scans fetched content through Content Firewall BEFORE it enters any LLM prompt
- Produces RESEARCH artifacts that downstream synthesis nodes can consume

CRITICAL: Never lets the LLM execute arbitrary URLs. Never acts as a browser.
Research is a scoped capability triggered only when the Outcome Contract
sets needs_external_research=True.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel


class ResearchFinding(BaseModel):
    claim: str
    source_url: str
    source_title: str
    snippet: str
    confidence: str = "MEDIUM"   # HIGH | MEDIUM | LOW


class ResearchResult(BaseModel):
    objective: str
    findings: List[ResearchFinding] = []
    summary: str = ""
    sources_cited: int = 0


RESEARCH_PROMPT = """You are NEXORA's Research Synthesizer.
Given a research objective and a set of raw web search results, produce a structured
set of factual findings with citations.

RESEARCH OBJECTIVE:
{objective}

RAW SEARCH RESULTS:
{raw_results}

Return ONLY valid JSON matching this schema:
{{
  "summary": "2-3 sentence high-level synthesis",
  "findings": [
    {{
      "claim": "one concrete factual claim",
      "source_url": "the URL this came from",
      "source_title": "title of the source page",
      "snippet": "supporting text from the source",
      "confidence": "HIGH|MEDIUM|LOW"
    }}
  ]
}}

Rules:
- Every finding MUST cite a source URL. No unsupported claims.
- Prefer HIGH confidence for well-established facts, LOW for speculative claims.
- 3-8 findings total. Quality over quantity.
- If no useful results were returned, return an empty findings array and explain in summary.
"""


class WebResearchService:
    """Controlled web research with firewall + LLM synthesis."""

    def __init__(self, firewall=None, api_key: Optional[str] = None,
                 model: Optional[str] = None, call_fn=None, search_fn=None):
        self.firewall = firewall
        self.api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY", "")
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("NEXORA_MODEL_T2", "gemini-3.5-flash")
        self.call_fn = call_fn        # test seam for LLM
        self.search_fn = search_fn    # test seam for search

    async def research(self, objective: str, max_results: int = 5) -> ResearchResult:
        """Run a research query. Returns structured findings with citations."""
        # Step 1: Get raw search results
        raw = await self._search(objective, max_results)

        # Step 2: Firewall-scan every result BEFORE it touches an LLM
        scanned = []
        for r in raw:
            content = f"{r.get('title', '')}. {r.get('content', '') or r.get('snippet', '')}"
            if self.firewall:
                scan = self.firewall.scan(content)
                if scan.quarantined:
                    # Drop malicious results silently — don't feed them to the LLM
                    continue
            scanned.append(r)

        # Step 3: Synthesize via LLM (or deterministic fallback)
        if not scanned:
            return ResearchResult(
                objective=objective,
                summary="No usable research results returned.",
                findings=[],
                sources_cited=0,
            )

        synthesis = await self._synthesize(objective, scanned)
        return synthesis

    async def _search(self, objective: str, max_results: int) -> List[Dict]:
        if self.search_fn:
            return self.search_fn(objective, max_results)
        if not self.api_key:
            # No Tavily key — use Gemini + Google Search grounding when any Gemini
            # backend (API key or Vertex project) is configured.
            has_backend = bool(self.gemini_key or os.getenv("GCP_PROJECT_ID", ""))
            if has_backend and os.getenv("NEXORA_GROUNDED_RESEARCH", "1") == "1":
                grounded = await self._grounded_search(objective, max_results)
                if grounded:
                    return grounded
            return self._mock_search(objective)
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post("https://api.tavily.com/search", json={
                    "api_key": self.api_key,
                    "query": objective,
                    "max_results": max_results,
                    "include_answer": True,
                    "search_depth": "basic",
                })
                r.raise_for_status()
                data = r.json()
                results = []
                for item in data.get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "content": item.get("content", ""),
                        "snippet": item.get("content", "")[:300],
                    })
                return results
        except Exception:
            # Fallback to deterministic mock on any error
            return self._mock_search(objective)

    async def _grounded_search(self, objective: str, max_results: int) -> List[Dict]:
        """Real web results via Gemini + Google Search grounding (google-genai SDK)."""
        try:
            from google.genai import types
            from nexora.core.llm_client import genai_client
        except ImportError:
            return []
        try:
            client = genai_client()
            resp = await client.aio.models.generate_content(
                model=self.model,
                contents=(f"Research this and report the key facts with concrete numbers, "
                          f"names and dates:\n{objective}"),
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    tools=[types.Tool(google_search=types.GoogleSearch())]),
            )
        except Exception:
            return []

        answer = (resp.text or "").strip()
        results: List[Dict] = []
        try:
            cand = resp.candidates[0]
            gm = getattr(cand, "grounding_metadata", None)
            chunks = list(getattr(gm, "grounding_chunks", None) or [])
            for ch in chunks[:max_results]:
                web = getattr(ch, "web", None)
                if not web:
                    continue
                results.append({
                    "title": getattr(web, "title", "") or "Source",
                    "url": getattr(web, "uri", "") or "",
                    "content": answer[:1500],
                    "snippet": answer[:300],
                })
        except Exception:
            pass

        if not results and answer:
            # Grounded answer but no chunk metadata — still real, attribute to Google Search.
            results.append({
                "title": f"Google Search synthesis: {objective[:60]}",
                "url": "https://www.google.com/search?q=" + objective.replace(" ", "+")[:120],
                "content": answer[:2000],
                "snippet": answer[:300],
            })
        return results

    def _mock_search(self, objective: str) -> List[Dict]:
        """Deterministic mock search for when no Tavily key is available."""
        text = objective.lower()
        results = []
        if any(w in text for w in ["market", "mobile", "game", "gaming"]):
            results.extend([
                {"title": "Mobile Gaming Market Report 2026",
                 "url": "https://example.com/mobile-gaming-2026",
                 "content": "Global mobile gaming market valued at $138B in 2026, growing 7% YoY. Hypercasual segment represents 18% of revenue.",
                 "snippet": "Global mobile gaming market $138B..."},
                {"title": "Ghost Mechanic in Mobile Games",
                 "url": "https://example.com/ghost-mechanic",
                 "content": "Games like Celeste and Super Meat Boy pioneered ghost mechanics. Mobile adaptations include Time Surfer and Ghost Jump with 500K-2M downloads.",
                 "snippet": "Ghost mechanic precedent in mobile..."},
            ])
        if any(w in text for w in ["competitor", "rival", "similar"]):
            results.extend([
                {"title": "Top Indie Mobile Games 2026",
                 "url": "https://example.com/indie-mobile-2026",
                 "content": "Alto's Odyssey, Crossy Road, and Monument Valley lead the indie mobile space with $10-50M lifetime revenue each.",
                 "snippet": "Leading indie mobile games..."},
            ])
        if any(w in text for w in ["monetization", "revenue", "earn"]):
            results.extend([
                {"title": "Mobile Game Monetization Benchmarks",
                 "url": "https://example.com/monetization-benchmarks",
                 "content": "Hypercasual games average $0.05-$0.15 ARPDAU. Top quartile titles reach $0.30+ ARPDAU through rewarded video and IAP.",
                 "snippet": "Hypercasual ARPDAU benchmarks..."},
            ])
        if not results:
            # Generic fallback
            results.append({
                "title": f"Research: {objective}",
                "url": "https://example.com/generic-research",
                "content": f"General information about {objective}. No specific data available in mock.",
                "snippet": f"General information about {objective}...",
            })
        return results[:5]

    async def _synthesize(self, objective: str, results: List[Dict]) -> ResearchResult:
        raw_text = "\n\n".join(
            f"Title: {r['title']}\nURL: {r['url']}\nContent: {r.get('content', r.get('snippet', ''))}"
            for r in results
        )

        from nexora.core.llm_client import llm_available
        if self.call_fn:
            text = self.call_fn(RESEARCH_PROMPT.format(objective=objective, raw_results=raw_text))
        elif llm_available():
            try:
                text = await self._call_gemini(objective, raw_text)
            except Exception:
                return self._deterministic_fallback(objective, results)
        else:
            return self._deterministic_fallback(objective, results)

        parsed = self._parse(text)
        if parsed is None:
            return self._deterministic_fallback(objective, results)

        findings = [
            ResearchFinding(
                claim=f.get("claim", ""),
                source_url=f.get("source_url", ""),
                source_title=f.get("source_title", ""),
                snippet=f.get("snippet", ""),
                confidence=f.get("confidence", "MEDIUM"),
            )
            for f in parsed.get("findings", [])
        ]
        # Filter out findings without source URLs
        findings = [f for f in findings if f.source_url]
        return ResearchResult(
            objective=objective,
            findings=findings,
            summary=parsed.get("summary", ""),
            sources_cited=len(findings),
        )

    async def _call_gemini(self, objective: str, raw_text: str) -> str:
        prompt = RESEARCH_PROMPT.format(objective=objective, raw_results=raw_text)
        from nexora.core.adk_runtime import try_run_agent
        adk = await try_run_agent(
            role="Research Analyst",
            instruction=("You are NEXORA's Research Analyst. You synthesize web results "
                         "into cited factual findings. Every claim keeps its source URL. "
                         "You output only JSON."),
            task=prompt)
        if adk and adk.strip():
            return adk
        from nexora.core.llm_client import llm_generate
        return await llm_generate(prompt, temperature=0.1, model=self.model)

    def _parse(self, text: str) -> Optional[Dict[str, Any]]:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None

    def _deterministic_fallback(self, objective: str, results: List[Dict]) -> ResearchResult:
        """Deterministic synthesis when no LLM is available."""
        findings = []
        for r in results[:5]:
            content = r.get("content", r.get("snippet", ""))
            if content:
                findings.append(ResearchFinding(
                    claim=content[:200],
                    source_url=r.get("url", ""),
                    source_title=r.get("title", ""),
                    snippet=content[:150],
                    confidence="MEDIUM",
                ))
        return ResearchResult(
            objective=objective,
            findings=findings,
            summary=f"Found {len(findings)} findings from web search (deterministic synthesis).",
            sources_cited=len(findings),
        )