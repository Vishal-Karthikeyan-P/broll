"""Scene planner: turns narration text into footage search queries plus safety flags.

HeuristicPlanner needs no API key. OpenAICompatPlanner (Gemini/OpenAI/any chat-completions server) can improve the
queries, but the safety rules below always run on top of it, and it falls back to the heuristic planner on any error.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import httpx

STOP = set("""a an the and or but if then of to in on at by for with from as is are was were be been being it its this
that these those i you he she we they them his her our your their my me us do does did have has had will would can
could should may might not no so than too very just about into over after before up down out more most less many much
some any each every all also how what which who whom whose why when where there here""".split())

# Words with several meanings: cue words in the surrounding text pick the sense. First tuple = default sense.
SENSES: dict[str, tuple[str, list[tuple[set, str, str]]]] = {
    "bank": ("bank building exterior finance", [
        ({"river", "water", "shore", "fishing", "stream", "flood", "mud"}, "river bank nature water", "river"),
        ({"money", "loan", "account", "deposit", "savings", "interest", "credit", "cash", "finance", "financial",
          "branch", "atm", "mortgage", "invest"}, "bank building exterior finance", "finance")]),
    "cloud": ("clouds in blue sky", [
        ({"computing", "server", "servers", "data", "software", "storage", "aws", "azure", "saas", "app", "apps",
          "migrate", "deploy", "infrastructure", "devops", "backup", "platform"}, "data center server room", "computing"),
        ({"sky", "rain", "weather", "storm", "sun", "forecast", "fog", "fluffy"}, "clouds in blue sky", "weather")]),
    "mouse": ("computer mouse on desk", [
        ({"click", "cursor", "computer", "pc", "laptop", "scroll", "keyboard", "screen", "wireless", "desk"},
         "computer mouse on desk", "computer"),
        ({"cheese", "cat", "tiny", "squeak", "rodent", "trap", "pet", "hole", "trapped"}, "small mouse animal", "animal")]),
    "python": ("programming code on laptop screen", [
        ({"code", "coding", "programming", "developer", "developers", "script", "software", "library", "libraries",
          "language", "data", "pip", "django", "flask", "ai", "machine", "learning", "engineer"},
         "programming code on laptop screen", "programming"),
        ({"snake", "reptile", "jungle", "constrictor", "slither", "zoo", "wild", "venom"}, "python snake wildlife", "snake")]),
    "value": ("team brainstorming whiteboard", [
        ({"money", "price", "cost", "worth", "dollar", "dollars", "rupees", "investment", "invest", "savings", "stock",
          "stocks", "market"}, "calculator and coins finance", "money"),
        ({"customer", "customers", "brand", "company", "team", "trust", "principles", "core", "values", "culture",
          "mission"}, "team collaboration office meeting", "business")]),
}

# Abstract ideas have no literal footage: map to a visual metaphor.
ABSTRACT = {
    "trust": "hands shaking close up", "success": "mountain summit sunrise", "growth": "plant sprouting time lapse",
    "freedom": "open road driving landscape", "patience": "slow clock time lapse", "courage": "rock climbing wall",
    "creativity": "paint brush colorful strokes", "innovation": "light bulb glowing abstract", "future": "futuristic city skyline night",
    "change": "seasons changing time lapse", "focus": "macro lens focus close up", "slowly": "slow motion water drops",
    "teamwork": "hands stacking together team", "quality": "craftsman hands detail work", "hope": "sunrise over horizon",
    "risk": "tightrope balance walking", "loyalty": "dog and owner walking", "wisdom": "old books library shelves",
    "peace": "calm lake reflection morning", "time": "clock ticking close up", "earned": "hard work sweat effort",
    "consistency": "steady waves on beach", "discipline": "morning routine alarm clock",
}

SENSITIVE = set("""died death dead killed kill murder shooting shot victims victim funeral tragedy tragic attack attacks
accident crash crashed fatal suicide cancer grief mourning war bombing explosion earthquake flood disaster abuse
tortured missing""".split())
SENSITIVE_VISUALS = ["candle flame dark", "rain on window", "calm ocean horizon", "empty road fog morning"]

BRANDS = set("""google apple amazon microsoft tesla nike adidas coca-cola pepsi mcdonald's netflix meta facebook instagram
youtube tiktok samsung openai spotify uber airbnb walmart starbucks disney toyota ford bmw whatsapp twitter linkedin
paypal nvidia intel ibm oracle""".split())
NOT_ENTITIES = set("""I January February March April May June July August September October November December Monday Tuesday
Wednesday Thursday Friday Saturday Sunday India Singapore America English Hindi Tamil Europe Asia Africa Australia
Canada Christmas Diwali""".split())
PEOPLE_WORDS = {"person", "people", "man", "woman", "men", "women", "girl", "boy", "face", "faces", "portrait", "child",
                "children", "kid", "kids", "crowd", "smiling", "couple", "family"}
AVOID_EXPAND = {"alcohol": {"alcohol", "beer", "wine", "whiskey", "cocktail", "drinking", "liquor", "vodka"},
                "faces": PEOPLE_WORDS, "people": PEOPLE_WORDS, "face": PEOPLE_WORDS,
                "violence": {"violence", "gun", "weapon", "fight", "blood"}, "smoking": {"smoking", "cigarette", "tobacco"}}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


WEAK = set("""said say says told tell grew grow grows made make makes opened open sat watched watch means mean moving move
cannot overstated early late next last new one two three four five get got goes went going come came""".split())


def _singular(w: str, table) -> str | None:
    if w in table:
        return w
    if w.endswith("s") and w[:-1] in table:
        return w[:-1]
    return None


def content_words(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in STOP and t not in WEAK and len(t) > 2 and not t.isdigit()]


def avoid_tokens(avoid: list[str]) -> set[str]:
    out: set[str] = set()
    for a in avoid:
        for t in tokens(a):
            out |= AVOID_EXPAND.get(t, {t})
        out |= AVOID_EXPAND.get(a.lower().strip(), set())
    return out


def find_entities(text: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(r"\b([A-Z][a-zA-Z'’\-]+(?:\s+[A-Z][a-zA-Z'’\-]+)*)\b", text):
        ent = m.group(1)
        at_start = m.start() == 0 or text[:m.start()].rstrip().endswith((".", "!", "?", "\n"))
        words = ent.split()
        if ent in NOT_ENTITIES or ent.lower() in STOP:
            continue
        if len(words) >= 2 or (not at_start and len(ent) > 2):
            found.append(ent)
    for t in tokens(text):
        if t in BRANDS and not any(t == e.lower() for e in found):
            found.append(t.capitalize())
    return found


@dataclass
class ScenePlan:
    queries: list[str]
    keywords: list[str]
    reason: str
    sense: str | None = None
    abstract: bool = False
    sensitive: bool = False
    entities: list[str] = field(default_factory=list)
    avoid: set = field(default_factory=set)
    flags: list[dict] = field(default_factory=list)
    llm_used: bool = False


class HeuristicPlanner:
    name = "heuristic"
    model = "rules-v1"

    def plan(self, text: str, visual_hint: str | None, context: str, style: str, avoid: list[str]) -> ScenePlan:
        flags: list[dict] = []
        avoid_set = avoid_tokens(avoid)
        words = content_words(text)
        ctx = set(content_words(context)) | set(words)
        reason_parts: list[str] = []
        queries: list[str] = []
        sense = None
        deferred_metaphor = None

        entities = find_entities(text)
        ent_tokens = {t for e in entities for t in tokens(e)}
        if entities:
            flags.append({"code": "NAMED_ENTITY_GENERIC_FOOTAGE",
                          "message": f"Named person/brand ({', '.join(entities)}): using generic footage, "
                                     "no likeness or logo of the named entity."})
            reason_parts.append("named entity removed from search")
            words = [w for w in words if w not in ent_tokens]

        sensitive = bool(SENSITIVE & set(tokens(text)))
        if sensitive:
            queries = list(SENSITIVE_VISUALS)
            reason_parts.append("sensitive topic: calm, respectful visuals, no people")
            flags.append({"code": "SENSITIVE_TOPIC_RESPECTFUL_FOOTAGE",
                          "message": "Sensitive subject: muted, respectful footage without people."})
            avoid_set |= PEOPLE_WORDS
        else:
            if visual_hint and visual_hint.strip():
                queries.append(" ".join(content_words(visual_hint)[:5]) or visual_hint.strip())
                reason_parts.append("visual_hint supplied")
            # ambiguous words: pick the sense from the surrounding text
            for w0 in words:
                w = _singular(w0, SENSES)
                if w:
                    default, options = SENSES[w]
                    best, best_n, label = default, 0, "default"
                    for cues, q, lab in options:
                        n = len(cues & ctx)
                        if n > best_n:
                            best, best_n, label = q, n, lab
                    queries.append(best)
                    sense = f"{w}={label}"
                    reason_parts.append(f"'{w}' disambiguated as {label}")
                    break
            # abstract concepts: use a visual metaphor, but only when the line is mostly abstract
            # ("Trust is earned slowly"), never for concrete instructions that happen to contain one such word
            ab = [_singular(w, ABSTRACT) for w in words if _singular(w, ABSTRACT)]
            ab_ratio = len(ab) / max(len(words), 1)
            if ab and ab_ratio >= 0.34:
                metaphor = ABSTRACT[ab[0]]
                if ab_ratio >= 0.5:
                    queries.append(metaphor)  # metaphor first
                else:
                    deferred_metaphor = metaphor  # keyword query first, metaphor as the second choice
                reason_parts.append(f"abstract idea '{ab[0]}' shown as a visual metaphor")
            else:
                ab = []
            # numbers and statistics: show a chart, never search for the number itself
            if re.search(r"\d", text):
                topic = " ".join([w for w in words if not _singular(w, ABSTRACT)][:2])
                queries.append(f"{topic} business growth chart graph".strip())
                reason_parts.append("statistic shown as chart footage; the figure is in the captions")
            kw = [w for w in words if not _singular(w, SENSES) and not _singular(w, ABSTRACT)][:4]
            if kw:
                queries.append(" ".join(kw))
                if len(kw) > 2:
                    queries.append(" ".join(kw[:2]))
            if deferred_metaphor:
                queries.append(deferred_metaphor)
            if not queries:
                queries = ["city skyline office buildings" if entities else "abstract light background"]
                reason_parts.append("no concrete subject")
        if avoid_set & PEOPLE_WORDS:
            flags.append({"code": "AVOID_PEOPLE_BEST_EFFORT",
                          "message": "Clips are filtered by provider tags; faces cannot be ruled out from tags alone."})
        # de-duplicate, keep order
        seen, uniq = set(), []
        for q in queries:
            q = q.strip()
            if q and q not in seen:
                seen.add(q)
                uniq.append(q)
        return ScenePlan(queries=uniq, keywords=words, reason="; ".join(reason_parts) or "keywords from narration",
                         sense=sense, abstract=bool(ab) if not sensitive else False, sensitive=sensitive,
                         entities=entities, avoid=avoid_set, flags=flags)


class OpenAICompatPlanner:
    """Any OpenAI-compatible chat endpoint (OpenAI, Gemini's OpenAI-compat URL, local servers)."""
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float):
        self.base, self.key, self.model, self.timeout = base_url.rstrip("/"), api_key, model, timeout
        self.fallback = HeuristicPlanner()

    def plan(self, text: str, visual_hint: str | None, context: str, style: str, avoid: list[str]) -> ScenePlan:
        base = self.fallback.plan(text, visual_hint, context, style, avoid)  # safety rules always apply
        if base.sensitive:
            return base  # never let a model override the respectful-footage rule
        prompt = (
            "You choose stock-footage search queries for one line of a voiceover. Return JSON only: "
            '{"queries": ["3 short stock-footage queries, most specific first"], "reason": "one sentence"}. '
            "Rules: pick the meaning that fits the context (bank, cloud, mouse, python, value are ambiguous); "
            "abstract ideas become a concrete visual metaphor; never search for a named real person or brand; "
            "never search for a number; avoid close-ups of faces.\n"
            f"Context: {context}\nLine: {text}\nStyle: {style}\nAvoid: {avoid}\nVisual hint: {visual_hint or ''}")
        try:
            r = httpx.post(f"{self.base}/chat/completions", timeout=self.timeout,
                           headers={"Authorization": f"Bearer {self.key}"},
                           json={"model": self.model, "temperature": 0,
                                 "response_format": {"type": "json_object"},
                                 "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            data = json.loads(r.json()["choices"][0]["message"]["content"])
            qs = [q for q in data.get("queries", []) if isinstance(q, str) and q.strip()][:3]
            if not qs:
                raise ValueError("no queries")
            if base.entities:  # strip any entity the model may have echoed
                ent = {t for e in base.entities for t in tokens(e)}
                qs = [" ".join(w for w in q.split() if w.lower() not in ent) for q in qs]
            base.queries = [q for q in qs if q] + [q for q in base.queries if q not in qs]
            base.reason = f"LLM: {data.get('reason', '')}; safety rules: {base.reason}"
            base.llm_used = True
        except Exception as e:  # resilience: keep working without the model
            base.flags.append({"code": "PLANNER_LLM_FALLBACK",
                               "message": f"LLM planner failed ({e.__class__.__name__}); used rules."})
        return base


def build_planner(settings):
    if settings.planner_provider == "openai_compat" and settings.llm_base_url:
        return OpenAICompatPlanner(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.http_timeout)
    return HeuristicPlanner()
