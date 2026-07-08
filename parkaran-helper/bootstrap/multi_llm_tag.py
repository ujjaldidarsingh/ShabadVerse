"""Multi-LLM consensus tagging for SGGS shabads.

Replaces the single-LLM enrichment pipeline (enrich_sggs.py + tag_shabads.py)
with a four-LLM consensus pass. Each LLM tags every shabad independently;
final tags are the ones agreed by at least two LLMs. Full per-LLM reasoning
is preserved so the UI can later show "Tagged X because Y" tooltips.

LLM lineup:
  - qwen3:14b           (Ollama, local)         — strong general reasoner
  - deepseek-r1:14b     (Ollama, local)         — independent training family
  - gemma2:27b          (Ollama, local)         — Google family, larger context
  - claude-sonnet-4-5   (Anthropic API)         — most aligned with Sikh context
                                                  in our pilot tests; tiebreaker

Run order (each pass is resumable; stop and resume any time):

    python bootstrap/multi_llm_tag.py --llm qwen3:14b
    python bootstrap/multi_llm_tag.py --llm deepseek-r1:14b
    python bootstrap/multi_llm_tag.py --llm gemma2:27b
    python bootstrap/multi_llm_tag.py --llm claude-sonnet-4-5
    python bootstrap/multi_llm_tag.py --consensus

Each pass writes to data/tag_reasoning.json keyed by shabad_id → llm_name → result.
The final --consensus step merges results, applies the voting rule, and writes
the canonical tags back to data/sggs_all_shabads.json plus a new tag_vocabulary.json.

A single shabad costs roughly:
  - Ollama: free, ~5-15s per call depending on model size (M-series Mac)
  - Anthropic claude-sonnet-4-5: ~400 input + 300 output tokens
                                 → ~$0.0057 per shabad → ~$32 for 5,542 shabads

The consensus rule (--consensus pass):
  - A tag is canonical for a shabad if it appears in at least 2 of 4 LLM responses
    (case-insensitive comparison, simple morphological normalization for variants)
  - Singleton tags (only one LLM proposed) are dropped — pure noise reduction
  - Tied 2-2 splits keep both candidate tags; Claude's vote breaks ties only when
    the question is "which of two synonyms to keep" (handled in Phase C taxonomy
    build, not here)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

# ---- Paths ------------------------------------------------------------------

SGGS_PATH = Path(config.SGGS_DATA_PATH)
# Per-LLM reasoning files prevent the multi-process write race we hit when
# three runs shared a single tag_reasoning.json: each process held its own
# in-memory snapshot and overwrote the others' saves. The merged file is
# rebuilt by --consensus from the per-LLM shards.
REASONING_DIR = Path(config.DATA_DIR) / "tag_reasoning"
REASONING_MERGED_PATH = Path(config.DATA_DIR) / "tag_reasoning.json"
NEW_VOCAB_PATH = Path(config.DATA_DIR) / "tag_vocabulary.json"

# ---- LLM identifiers --------------------------------------------------------

# gemma2:27b kept as a permitted name even though we're not running it in this
# pass — leaves the option open without forcing a code change later.
OLLAMA_LLMS = {"qwen3:14b", "deepseek-r1:14b", "llama3.1:8b", "gemma2:27b"}
ANTHROPIC_LLMS = {"claude-sonnet-4-5"}
ALL_LLMS = sorted(OLLAMA_LLMS | ANTHROPIC_LLMS)
# The LLMs actually voting in the consensus pass. Four independent training
# families: Alibaba (qwen3), DeepSeek-AI (deepseek-r1), Meta (llama3.1),
# Anthropic (claude-sonnet-4-5). claude was paused at 3,428 entries when its
# credit balance hit zero; resumed after top-up. With four voters and
# min_votes=2 (default), a tag survives consensus if any half of the LLMs
# agree — a sensible noise floor with diverse-family redundancy.
CONSENSUS_LLMS = ["qwen3:14b", "deepseek-r1:14b", "llama3.1:8b", "claude-sonnet-4-5"]

# ---- Prompt -----------------------------------------------------------------

PROMPT_TEMPLATE = """You are tagging a Sikh Gurbani shabad from Sri Guru Granth Sahib Ji.

Translation:
{translation}

Rahao (core verse):
{rahao}

Return a JSON object with exactly these keys:

  "primary_theme":  one short phrase (2-4 words) capturing the dominant spiritual theme.
                    Use canonical Gurbani terms when applicable (e.g. "Hukam", "Naam Simran",
                    "Vichola", "Bhakti", "Vairag"). Avoid vague phrases like "Spiritual life".
  "mood":           one short phrase capturing emotional register (e.g. "Devotional longing",
                    "Joyful praise", "Contemplative peace", "Fearful surrender").
  "brief_meaning":  one sentence in plain English summarizing what the shabad teaches.
  "tags":           a JSON array of 3-6 short canonical tags. Use established Sikhi vocabulary
                    where possible. Common tags include: "Hukam", "Naam Simran", "Vairag",
                    "Bhakti", "Surrender", "Divine Grace", "Maya", "Birha", "Sangat",
                    "Guru's Wisdom", "Chardi Kala", "Anand", "Vichola", "Awe", "Humility".
                    Each tag should be 1-3 words.
  "reasoning":      one sentence explaining WHY you chose these tags. Reference specific
                    imagery, phrases, or arcs in the translation.

Return ONLY the JSON object — no preamble, no markdown fences, no commentary."""


# Constrained-prompt template for the non-AK pass. The vocabulary list is the
# AK-derived canonical taxonomy from Phase B.2 — LLMs are told to pick from
# that list and only invent a new tag when no listed tag fits, which sharply
# reduces tag noise across the full corpus (Flip A methodology).
CONSTRAINED_PROMPT_TEMPLATE = """You are tagging a Sikh Gurbani shabad from Sri Guru Granth Sahib Ji.

Translation:
{translation}

Rahao (core verse):
{rahao}

CANONICAL TAG VOCABULARY (derived from consensus tagging of canonically-recited Amrit Keertan shabads):
{tag_vocabulary}

Return a JSON object with exactly these keys:

  "primary_theme":  one short phrase (2-4 words) capturing the dominant spiritual theme.
                    Use canonical Gurbani terms when applicable (e.g. "Hukam", "Naam Simran",
                    "Vichola", "Bhakti", "Vairag"). Avoid vague phrases like "Spiritual life".
  "mood":           one short phrase capturing emotional register (e.g. "Devotional longing",
                    "Joyful praise", "Contemplative peace", "Fearful surrender").
  "brief_meaning":  one sentence in plain English summarizing what the shabad teaches.
  "tags":           a JSON array of 3-6 short canonical tags. PREFER tags from the canonical
                    vocabulary above. Only invent a new tag when none of the listed tags
                    fit the shabad's content. Each tag should be 1-3 words.
  "reasoning":      one sentence explaining WHY you chose these tags. Reference specific
                    imagery, phrases, or arcs in the translation. If you used any tag NOT
                    in the canonical vocabulary, name it explicitly and explain why no
                    listed tag fit.

Return ONLY the JSON object — no preamble, no markdown fences, no commentary."""


# ---- LLM dispatchers --------------------------------------------------------

def call_ollama(model: str, prompt: str, max_tokens: int = 800) -> dict:
    """Run a single Ollama generation. Raises on hard errors; caller decides retry."""
    import ollama as _ollama

    client = _ollama.Client(host=config.OLLAMA_BASE_URL)
    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format="json",
        options={"num_predict": max_tokens, "temperature": 0.2},
        think=False,
    )
    text = response.message.content.strip()
    return json.loads(text)


class AnthropicCreditExhausted(Exception):
    """Raised when the API rejects calls because the org's credit balance is too low.
    Surfaced to run_pass so it can stop the whole pass instead of churning through
    thousands of doomed-to-fail shabads.
    """


def call_anthropic(model: str, prompt: str, max_tokens: int = 800) -> dict:
    """Run a single Anthropic message generation. Retries on 429 with exponential backoff.

    Free-tier accounts hit 50 RPM and 8K output tokens/min limits quickly. We
    back off long enough to clear a fresh minute window rather than hammering.
    Credit-exhaustion 400s are treated as fatal and bubble up via
    AnthropicCreditExhausted so the caller can stop the whole pass.
    """
    import anthropic

    client = anthropic.Anthropic()
    last_err = None
    for attempt in range(6):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            # Strip any accidental markdown fences just in case.
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
            return json.loads(text)
        except anthropic.RateLimitError as err:
            last_err = err
            # 5s, 15s, 35s, 75s, 155s, 315s — covers up to ~10 minutes of backoff.
            wait = 5 * (2**attempt) + 5
            time.sleep(wait)
        except anthropic.BadRequestError as err:
            # Credit-balance-too-low and account-level usage-limit-reached both
            # surface as 400s. Treat both as fatal-for-this-pass so we don't
            # burn through thousands of doomed-to-fail calls. The user can
            # either top up credits, raise the monthly limit, or wait for the
            # limit to reset (msg includes the reset timestamp).
            msg_text = str(err).lower()
            fatal_markers = ("credit balance", "billing", "usage limits", "usage limit")
            if any(m in msg_text for m in fatal_markers):
                raise AnthropicCreditExhausted(str(err)) from err
            raise
        except anthropic.APIStatusError as err:
            # 5xx are worth retrying; 4xx other than 429 are fatal.
            if 500 <= err.status_code < 600:
                last_err = err
                time.sleep(5 * (attempt + 1))
            else:
                raise
    raise RuntimeError(f"anthropic exhausted retries: {last_err}")


def tag_one(llm: str, shabad: dict, vocabulary: list[str] | None = None) -> dict:
    """Tag a single shabad with a single LLM. Returns the parsed result + raw timing.

    When `vocabulary` is provided (Phase B.4 non-AK pass), the constrained prompt
    is used and the LLM is asked to prefer tags from that list. When None, the
    free-form prompt is used (Phase B.1 AK pass and the original full-corpus pass).
    """
    if vocabulary:
        prompt = CONSTRAINED_PROMPT_TEMPLATE.format(
            translation=(shabad.get("english_translation") or "")[:1200],
            rahao=(shabad.get("rahao_english") or "(no rahao)")[:400],
            tag_vocabulary=", ".join(vocabulary),
        )
    else:
        prompt = PROMPT_TEMPLATE.format(
            translation=(shabad.get("english_translation") or "")[:1200],
            rahao=(shabad.get("rahao_english") or "(no rahao)")[:400],
        )
    started = time.time()
    if llm in OLLAMA_LLMS:
        result = call_ollama(llm, prompt)
    elif llm in ANTHROPIC_LLMS:
        result = call_anthropic(llm, prompt)
    else:
        raise ValueError(f"Unknown LLM: {llm}")
    return {
        "primary_theme": result.get("primary_theme", ""),
        "mood": result.get("mood", ""),
        "brief_meaning": result.get("brief_meaning", ""),
        "tags": list(result.get("tags", [])) if isinstance(result.get("tags"), list) else [],
        "reasoning": result.get("reasoning", ""),
        "elapsed_s": round(time.time() - started, 2),
        "constrained": bool(vocabulary),
    }


# ---- Reasoning store --------------------------------------------------------

def _llm_to_filename(llm: str) -> str:
    """Convert LLM name to a safe filename (e.g. 'qwen3:14b' → 'qwen3_14b.json')."""
    return llm.replace(":", "_").replace("/", "_") + ".json"


def llm_reasoning_path(llm: str) -> Path:
    """Per-LLM reasoning file path (one file per LLM, no write contention)."""
    return REASONING_DIR / _llm_to_filename(llm)


def load_llm_reasoning(llm: str) -> dict:
    """Load this LLM's reasoning shard. Falls back to merged file for back-compat
    on the first run after the per-LLM split (so we don't lose existing data).
    """
    REASONING_DIR.mkdir(parents=True, exist_ok=True)
    p = llm_reasoning_path(llm)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    # Fallback: pull this LLM's slice out of the legacy merged file.
    if REASONING_MERGED_PATH.exists():
        legacy = json.loads(REASONING_MERGED_PATH.read_text(encoding="utf-8"))
        return {sid: r[llm] for sid, r in legacy.items() if isinstance(r, dict) and llm in r}
    return {}


def save_llm_reasoning(llm: str, shabad_to_result: dict) -> None:
    """Save this LLM's reasoning shard. {shabad_id: result}."""
    REASONING_DIR.mkdir(parents=True, exist_ok=True)
    llm_reasoning_path(llm).write_text(
        json.dumps(shabad_to_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_merged_reasoning() -> dict:
    """Merge all per-LLM shards into the consolidated {shabad_id: {llm: result}} shape.

    Used by the --consensus pass and by anything that wants the unified view.
    Always re-reads from disk so it sees the latest writes from any in-flight
    process.
    """
    merged: dict = {}
    if REASONING_DIR.exists():
        for p in REASONING_DIR.glob("*.json"):
            llm_name_from_file = p.stem.replace("_", ":", 1) if "_" in p.stem else p.stem
            # Recover original LLM names: 'qwen3_14b' → 'qwen3:14b',
            # 'claude-sonnet-4-5' → 'claude-sonnet-4-5'
            for known in ALL_LLMS:
                if _llm_to_filename(known) == p.name:
                    llm_name_from_file = known
                    break
            shard = json.loads(p.read_text(encoding="utf-8"))
            for sid, result in shard.items():
                merged.setdefault(sid, {})[llm_name_from_file] = result
    elif REASONING_MERGED_PATH.exists():
        # Legacy single-file fallback.
        merged = json.loads(REASONING_MERGED_PATH.read_text(encoding="utf-8"))
    return merged


# ---- Per-LLM pass -----------------------------------------------------------

# Filter modes for run_pass:
#   "all"     — every shabad with an english_translation (default, AK-first ordered)
#   "ak"      — Amrit Keertan shabads only (Phase B.1, when you want to finish AK fast)
#   "non-ak"  — only non-AK shabads (Phase B.4, paired with --vocabulary)
FilterMode = str  # "all" | "ak" | "non-ak"


def load_ak_set() -> set[str]:
    """Load the set of SGGS shabad IDs flagged as Amrit Keertan."""
    sources_path = Path(config.DATA_DIR) / "sggs_sources.json"
    if not sources_path.exists():
        return set()
    sources_data = json.loads(sources_path.read_text(encoding="utf-8"))
    return {sid for sid, fields in sources_data.items() if fields.get("amrit_keertan")}


def load_vocabulary_file(path: Path) -> list[str]:
    """Load a tag vocabulary file produced by --consensus.

    Accepts the tag_vocabulary.json shape ({theme_tags: {tag: {...}}}) or a
    plain JSON list of strings. Returns a deterministic sort order so the
    prompt is stable across runs (which lets prompt caching kick in for
    LLMs that support it).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        tags = [t for t in raw if isinstance(t, str)]
    elif isinstance(raw, dict) and "theme_tags" in raw:
        tags = list(raw["theme_tags"].keys())
    else:
        raise SystemExit(f"Vocabulary file at {path} not in a known shape.")
    return sorted(set(tags))


def run_pass(
    llm: str,
    max_concurrent: int,
    save_every: int,
    limit: int | None,
    filter_mode: FilterMode = "all",
    vocabulary_path: Path | None = None,
) -> None:
    if llm not in ALL_LLMS:
        raise SystemExit(f"Unknown LLM '{llm}'. Choose from: {', '.join(ALL_LLMS)}")
    if filter_mode not in ("all", "ak", "non-ak"):
        raise SystemExit(f"Unknown filter mode '{filter_mode}'. Choose: all, ak, non-ak.")

    print(f"Loading SGGS shabads from {SGGS_PATH}...")
    shabads = json.loads(SGGS_PATH.read_text(encoding="utf-8"))
    print(f"  {len(shabads)} shabads loaded.")

    shard = load_llm_reasoning(llm)

    # Load AK source map so we can prioritize / filter on AK membership.
    # Flip-the-script methodology: tag the 2,078 AK shabads first across all
    # LLMs so we can derive a tradition-grounded taxonomy from canon before
    # tagging the remaining 3,464 non-AK shabads with that taxonomy as a
    # constraint.
    ak_set = load_ak_set()

    vocabulary: list[str] | None = None
    if vocabulary_path is not None:
        vocabulary = load_vocabulary_file(vocabulary_path)
        print(f"  loaded {len(vocabulary)} tags from {vocabulary_path.name} for constrained prompt")

    pending = []
    skipped = 0
    filtered_out = 0
    for s in shabads:
        sid = str(s.get("banidb_shabad_id"))
        if not sid or not s.get("english_translation"):
            continue
        in_ak = sid in ak_set
        if filter_mode == "ak" and not in_ak:
            filtered_out += 1
            continue
        if filter_mode == "non-ak" and in_ak:
            filtered_out += 1
            continue
        prev = shard.get(sid)
        # Skip only successful results. Treat error rows as "not done" so resume retries them.
        if isinstance(prev, dict) and "tags" in prev and not prev.get("error"):
            skipped += 1
            continue
        pending.append(s)

    # AK-first ordering: process Amrit Keertan shabads before non-AK ones.
    # ang_number breaks ties so we still walk SGGS in a sensible reading order
    # within each group. (For filter_mode="ak" or "non-ak", every entry has the
    # same first key so the secondary keys do all the work.)
    pending.sort(key=lambda s: (
        0 if str(s.get("banidb_shabad_id")) in ak_set else 1,
        s.get("ang_number", 0),
        int(s.get("banidb_shabad_id", 0) or 0),
    ))
    ak_pending = sum(1 for s in pending if str(s.get("banidb_shabad_id")) in ak_set)
    if filter_mode == "all":
        print(f"  AK shabads pending: {ak_pending} (will be processed first)")
    else:
        print(f"  filter_mode={filter_mode}: filtered_out={filtered_out}")

    if limit is not None:
        pending = pending[:limit]

    print(f"  {skipped} already done with {llm}; {len(pending)} remaining.")
    if not pending:
        print("Nothing to do.")
        return

    # Concurrency:
    # - Ollama on a single local model: cap at 2 so the GPU isn't thrashed.
    #   Each in-flight call holds the model warm.
    # - Anthropic: paid Tier 1+ supports 1,000+ RPM, so we honor the requested
    #   concurrency directly. Free-tier (50 RPM) callers should pass --concurrency 2.
    if llm in OLLAMA_LLMS:
        concurrency = max(1, min(max_concurrent, 2))
    else:
        concurrency = max(1, max_concurrent)

    print(f"  Running with concurrency={concurrency}; saving every {save_every} shabads.")
    print()

    started = time.time()
    completed = 0
    failed = 0

    def submit(executor: ThreadPoolExecutor, item: dict):
        return executor.submit(tag_one, llm, item, vocabulary)

    bailed_out = False
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_shabad = {submit(executor, s): s for s in pending}
        for future in as_completed(future_to_shabad):
            shabad = future_to_shabad[future]
            sid = str(shabad["banidb_shabad_id"])
            try:
                result = future.result()
                shard[sid] = result
                completed += 1
            except AnthropicCreditExhausted as err:
                # Stop the whole pass — every remaining call will fail the same
                # way until credits are added. Don't write an error row; just save
                # what we have and bail.
                save_llm_reasoning(llm, shard)
                print()
                print("=" * 70)
                print(f"STOPPED: Anthropic credit balance exhausted.")
                print(f"  {err}")
                print(f"  add credit at https://console.anthropic.com/settings/billing")
                print(f"  then re-run this same command — it will resume from where it left off.")
                print("=" * 70)
                bailed_out = True
                # Cancel any not-yet-started futures.
                for f in future_to_shabad:
                    if not f.done():
                        f.cancel()
                break
            except Exception as err:
                failed += 1
                err_summary = str(err)[:200]
                shard[sid] = {"error": err_summary}
                print(f"  shabad {sid} failed: {err_summary}")

            if (completed + failed) % save_every == 0:
                save_llm_reasoning(llm, shard)
                rate = (completed + failed) / max(1, time.time() - started)
                eta_s = (len(pending) - completed - failed) / max(rate, 0.001)
                print(
                    f"  progress: {completed + failed}/{len(pending)} "
                    f"(ok={completed}, fail={failed}, "
                    f"rate={rate:.2f}/s, eta={eta_s/60:.1f} min)"
                )

    save_llm_reasoning(llm, shard)
    elapsed = time.time() - started
    if bailed_out:
        print(f"Partial pass for {llm}: ok={completed}, fail={failed}, elapsed={elapsed/60:.1f} min")
    else:
        print(f"\nDone with {llm}. ok={completed}, fail={failed}, elapsed={elapsed/60:.1f} min")


# ---- Consensus --------------------------------------------------------------

_TAG_NORM_RE = re.compile(r"[^a-z0-9]+")
_SYNONYMS_PATH = Path(config.DATA_DIR) / "tag_synonyms.json"

# Module-level cache. Lazily loaded the first time normalize_tag() is called.
_SYNONYM_MAP_CACHE: dict[str, str] | None = None
_CANONICAL_SURFACE_CACHE: dict[str, str] | None = None


def normalize_tag(tag: str) -> str:
    """Lowercase + strip non-alphanum so 'Naam Simran' == 'naam-simran' == 'NaamSimran'.
    Collapses obvious surface variants without fancy stemming.
    """
    return _TAG_NORM_RE.sub("", tag.lower()).strip()


def _load_synonym_indices() -> tuple[dict[str, str], dict[str, str]]:
    """Load data/tag_synonyms.json into two indices.

    Returns:
        synonym_to_canonical: {normalized_variant: normalized_canonical} — used
            to fold variants into the canonical bucket during consensus.
        canonical_surface: {normalized_canonical: canonical_surface_form} —
            used to render the canonical surface form when emitting consensus
            output.
    """
    global _SYNONYM_MAP_CACHE, _CANONICAL_SURFACE_CACHE
    if _SYNONYM_MAP_CACHE is not None and _CANONICAL_SURFACE_CACHE is not None:
        return _SYNONYM_MAP_CACHE, _CANONICAL_SURFACE_CACHE

    synonym_to_canonical: dict[str, str] = {}
    canonical_surface: dict[str, str] = {}
    if _SYNONYMS_PATH.exists():
        raw = json.loads(_SYNONYMS_PATH.read_text(encoding="utf-8"))
        for canonical_form, variants in raw.items():
            if canonical_form.startswith("_"):
                continue  # skip comment fields
            canonical_norm = normalize_tag(canonical_form)
            if not canonical_norm:
                continue
            canonical_surface[canonical_norm] = canonical_form
            # The canonical itself maps to itself so direct uses (no synonym
            # lookup needed) still emit the right surface form.
            synonym_to_canonical[canonical_norm] = canonical_norm
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, str):
                    continue
                variant_norm = normalize_tag(variant)
                if not variant_norm:
                    continue
                # Last-write-wins is acceptable here — if the same variant is
                # listed under two canonicals, that's a curation bug worth
                # surfacing during review, not silently muddling at consensus.
                synonym_to_canonical[variant_norm] = canonical_norm

    _SYNONYM_MAP_CACHE = synonym_to_canonical
    _CANONICAL_SURFACE_CACHE = canonical_surface
    return synonym_to_canonical, canonical_surface


def consensus_tags(per_llm_tags: dict[str, list[str]], min_votes: int = 2) -> tuple[list[str], dict]:
    """Apply the consensus rule with synonym-aware folding.

    Variants listed in data/tag_synonyms.json are folded into their canonical
    form BEFORE counting votes, so e.g. {"Ego", "Ego dissolution", "Haumai"}
    from three LLMs all count toward "Haumai" rather than each getting one
    vote and then being dropped as singletons.

    Returns:
        (canonical_tags, vote_detail)
        canonical_tags: ordered list of agreed tags. Surface form is taken from
                        the synonym map's canonical when applicable; otherwise
                        the first-seen surface form per normalized key.
        vote_detail: {normalized_tag: {votes, surface_forms, voters,
                       canonical_surface}}
    """
    synonym_to_canonical, canonical_surface = _load_synonym_indices()

    bucket: dict[str, dict] = {}
    for llm, tags in per_llm_tags.items():
        seen_in_this_llm: set[str] = set()
        for tag in tags or []:
            if not isinstance(tag, str):
                continue
            tag = tag.strip()
            if not tag:
                continue
            raw_key = normalize_tag(tag)
            if not raw_key:
                continue
            # Fold variant into its canonical's normalized key.
            key = synonym_to_canonical.get(raw_key, raw_key)
            if key in seen_in_this_llm:
                continue
            seen_in_this_llm.add(key)
            entry = bucket.setdefault(
                key,
                {"votes": 0, "surface_forms": [], "voters": [], "canonical_surface": None},
            )
            entry["votes"] += 1
            if tag not in entry["surface_forms"]:
                entry["surface_forms"].append(tag)
            entry["voters"].append(llm)
            if entry["canonical_surface"] is None and key in canonical_surface:
                entry["canonical_surface"] = canonical_surface[key]

    ordered = sorted(bucket.items(), key=lambda kv: (-kv[1]["votes"], kv[0]))
    canonical = [
        (b["canonical_surface"] or b["surface_forms"][0])
        for _, b in ordered
        if b["votes"] >= min_votes
    ]
    return canonical, bucket


# ---- Sharpening (undo prompt-example anchoring) -----------------------------
#
# The tagging PROMPT_TEMPLATE lists example tags ("Hukam", "Naam Simran",
# "Bhakti", "Divine Grace", ...). All four LLMs anchored on that list: 14 of the
# 15 most common consensus tags are verbatim prompt examples, "Divine Grace"
# landed on 85% of the corpus, and 40% of shabads ended up tagged ONLY with
# these structural mega-tags. Such a tag carries almost no navigational
# information — if nearly every shabad is "Divine Grace", the label cannot tell
# two shabads apart.
#
# Sharpening rescues discriminative power WITHOUT re-running any LLM: it re-reads
# the per-LLM proposals already stored in data/tag_reasoning/ and re-selects.

MEGA_COVERAGE = 0.25  # a tag on >25% of the corpus is structural, not distinctive
MEGA_CAP_RICH = 1  # shabad already has >=2 distinctive tags: one anchor is enough
MEGA_CAP_THIN = 2  # shabad has <=1 distinctive tag: allow a second anchor
MEGA_CAP_IF_NO_DISTINCTIVE = 3  # nothing distinctive survived: anchors are all we have
MAX_TAGS_PER_SHABAD = 6
MIN_RESCUE_PROPOSALS = 10  # a rescued singleton must be a recurring concept, not a hapax
TAIL_MIN_COUNT = 10  # a tag on <10 shabads can never form a cluster — drop it
MIN_TAGS_PER_SHABAD = 2


def _bucket_entries(bucket: dict) -> list[tuple[str, str, int]]:
    """Flatten a consensus_tags() bucket into (normalized_key, surface, votes)."""
    entries = []
    for key, b in bucket.items():
        surface = b["canonical_surface"] or b["surface_forms"][0]
        entries.append((key, surface, b["votes"]))
    return entries


def select_sharpened_tags(
    bucket: dict,
    min_votes: int,
    coverage: dict[str, float],
    idf: dict[str, float],
    proposal_counts: dict[str, int],
) -> tuple[list[str], list[str]]:
    """Pick a shabad's tags, favoring distinctive ones over structural mega-tags.

    Distinctive tags (coverage <= MEGA_COVERAGE) are kept first and lead the
    output list, so downstream cluster-label pickers naturally prefer them.
    Mega-tags are capped: a shabad keeps only its strongest few, which stops
    "Divine Grace" from riding along on 85% of the corpus.

    When a shabad has no distinctive consensus tag at all (40% of the corpus
    before sharpening), we rescue the highest-IDF single-vote proposal that
    recurs elsewhere — one LLM noticing "Haumai" is better signal than a
    fourth mega-tag that every shabad shares.

    Returns (chosen, reserve). `reserve` holds voted-but-unchosen tags (mostly
    capped-out mega-tags) that the tail fold can backfill with, so dropping a
    rare tag never leaves a shabad under-tagged.
    """
    entries = _bucket_entries(bucket)
    if not entries:
        return [], []

    def strength(e: tuple[str, str, int]) -> tuple[int, float]:
        # More votes wins; ties break toward the rarer (higher-IDF) tag.
        return (e[2], idf.get(e[0], 0.0))

    voted = [e for e in entries if e[2] >= min_votes]
    mega = sorted((e for e in voted if coverage.get(e[0], 0.0) > MEGA_COVERAGE), key=strength, reverse=True)
    distinctive = sorted((e for e in voted if coverage.get(e[0], 0.0) <= MEGA_COVERAGE), key=strength, reverse=True)

    if not distinctive:
        rescued = [
            e
            for e in entries
            if e[2] == 1
            and coverage.get(e[0], 0.0) <= MEGA_COVERAGE
            and proposal_counts.get(e[0], 0) >= MIN_RESCUE_PROPOSALS
        ]
        rescued.sort(key=lambda e: idf.get(e[0], 0.0), reverse=True)
        distinctive = rescued[:2]

    # A shabad with real distinctive tags needs only one structural anchor for
    # context; a thin one leans on anchors. This keeps any single mega-tag from
    # re-accumulating across the corpus.
    if not distinctive:
        mega_cap = MEGA_CAP_IF_NO_DISTINCTIVE
    elif len(distinctive) >= 2:
        mega_cap = MEGA_CAP_RICH
    else:
        mega_cap = MEGA_CAP_THIN

    kept_mega = mega[:mega_cap]
    kept_distinctive = distinctive[: max(0, MAX_TAGS_PER_SHABAD - len(kept_mega))]

    chosen = [e[1] for e in kept_distinctive] + [e[1] for e in kept_mega]
    if not chosen:
        # Never leave a shabad tagless — fall back to its strongest proposals.
        chosen = [e[1] for e in sorted(entries, key=strength, reverse=True)[:2]]

    # Everything voted-in but crowded out, strongest first. These are legitimate
    # tags (they cleared min_votes), just not this shabad's most telling ones.
    chosen_set = set(chosen)
    reserve = [e[1] for e in (mega + distinctive) if e[1] not in chosen_set]
    return chosen, reserve


def _compute_sharpening_stats(
    reasoning: dict, min_votes: int
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Pass 1 of sharpening: corpus-wide tag statistics from a provisional consensus.

    Returns (coverage, idf, proposal_counts) keyed by normalized tag.
    - coverage/idf come from the provisional (unsharpened) consensus, i.e. what
      a tag's real corpus footprint is under the current rule.
    - proposal_counts counts shabads where ANY LLM proposed the tag (including
      single-vote proposals), which is what makes a rescue candidate credible.
    """
    provisional_counts: dict[str, int] = {}
    proposal_counts: dict[str, int] = {}
    n_shabads = 0

    for _sid, llm_results in reasoning.items():
        per_llm_tags = {
            llm: r.get("tags", [])
            for llm, r in llm_results.items()
            if isinstance(r, dict) and "tags" in r
        }
        if len(per_llm_tags) < min_votes:
            continue
        n_shabads += 1
        _, bucket = consensus_tags(per_llm_tags, min_votes=min_votes)
        for key, b in bucket.items():
            proposal_counts[key] = proposal_counts.get(key, 0) + 1
            if b["votes"] >= min_votes:
                provisional_counts[key] = provisional_counts.get(key, 0) + 1

    n = max(1, n_shabads)
    coverage = {k: c / n for k, c in provisional_counts.items()}
    idf = {k: math.log(n / max(1, c)) for k, c in provisional_counts.items()}
    # Tags that never reached consensus still need an IDF for rescue ranking.
    for k, c in proposal_counts.items():
        idf.setdefault(k, math.log(n / max(1, c)))
    return coverage, idf, proposal_counts


def run_consensus(
    min_votes: int,
    ak_only: bool = False,
    output_vocab_path: Path | None = None,
    write_shabads: bool = True,
    sharpen: bool = False,
) -> None:
    """Apply multi-LLM consensus to per-LLM reasoning shards.

    Args:
        min_votes: tag must appear in at least this many LLMs to survive.
        ak_only: when True, restrict consensus to Amrit Keertan shabads only.
                 Used by Phase B.2 to derive the AK-grounded canonical taxonomy
                 that constrains the non-AK pass (Phase B.4).
        output_vocab_path: where to write the resulting vocabulary file. Default
                 is data/tag_vocabulary.json. Phase B.2 writes to a separate
                 ak_taxonomy.json so the full-corpus vocabulary isn't overwritten
                 mid-pipeline.
        write_shabads: when False (Phase B.2 mode), the consensus only emits
                 the vocabulary file and skips writing back to sggs_all_shabads.json.
        sharpen: when True, run the two-pass sharpening that caps prompt-anchored
                 mega-tags and rescues distinctive ones. See select_sharpened_tags.
    """
    if not REASONING_DIR.exists() and not REASONING_MERGED_PATH.exists():
        raise SystemExit(
            f"No reasoning data at {REASONING_DIR} or {REASONING_MERGED_PATH}. "
            f"Run per-LLM passes first."
        )

    print(f"Loading reasoning from {REASONING_DIR} (per-LLM shards)...")
    reasoning = load_merged_reasoning()
    # Persist the merged view alongside the shards for inspection / archive.
    REASONING_MERGED_PATH.write_text(
        json.dumps(reasoning, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Loading shabads from {SGGS_PATH}...")
    shabads = json.loads(SGGS_PATH.read_text(encoding="utf-8"))
    by_sid = {str(s["banidb_shabad_id"]): s for s in shabads}

    ak_set = load_ak_set()
    if ak_only:
        before = len(reasoning)
        reasoning = {sid: v for sid, v in reasoning.items() if sid in ak_set}
        print(f"  AK-only filter: {before} → {len(reasoning)} shabads")

    # Coverage report — counted against the LLMs we chose for consensus, not
    # every name the script knows about (e.g. gemma2:27b is permitted but not
    # currently part of the run; claude is parked).
    coverage = {llm: 0 for llm in CONSENSUS_LLMS}
    full_coverage = 0
    for sid, llm_results in reasoning.items():
        ok_llms = [
            llm for llm in CONSENSUS_LLMS
            if isinstance(llm_results.get(llm), dict) and "tags" in llm_results[llm]
        ]
        for llm in ok_llms:
            coverage[llm] += 1
        if len(ok_llms) == len(CONSENSUS_LLMS):
            full_coverage += 1

    label = "AK shabads" if ak_only else "shabads"
    print(f"Per-LLM coverage on {label}:")
    for llm, n in coverage.items():
        print(f"  {llm:<22} {n}")
    print(f"  with all {len(CONSENSUS_LLMS)} LLMs: {full_coverage}")
    print()

    sharp_coverage: dict[str, float] = {}
    sharp_idf: dict[str, float] = {}
    sharp_proposals: dict[str, int] = {}
    if sharpen:
        print("Sharpening pass 1: computing corpus tag statistics...")
        sharp_coverage, sharp_idf, sharp_proposals = _compute_sharpening_stats(reasoning, min_votes)
        mega = sorted(
            ((k, c) for k, c in sharp_coverage.items() if c > MEGA_COVERAGE),
            key=lambda kv: -kv[1],
        )
        print(f"  mega-tags (>{MEGA_COVERAGE:.0%} coverage): {len(mega)}")
        for k, c in mega[:10]:
            print(f"    {c:5.0%}  {k}")
        print()

    print(f"Applying consensus rule (min_votes={min_votes}, sharpen={sharpen})...")
    updated = 0
    skipped_partial = 0
    new_tag_counts: dict[str, int] = {}
    sid_to_tags: dict[str, list[str]] = {}
    sid_to_reserve: dict[str, list[str]] = {}

    for sid, llm_results in reasoning.items():
        per_llm_tags = {
            llm: r.get("tags", []) for llm, r in llm_results.items()
            if isinstance(r, dict) and "tags" in r
        }
        if len(per_llm_tags) < min_votes:
            skipped_partial += 1
            continue

        canonical, bucket = consensus_tags(per_llm_tags, min_votes=min_votes)
        if sharpen:
            canonical, reserve = select_sharpened_tags(
                bucket, min_votes, sharp_coverage, sharp_idf, sharp_proposals
            )
            sid_to_reserve[sid] = reserve
        sid_to_tags[sid] = canonical
        if write_shabads and sid in by_sid:
            shabad = by_sid[sid]
            shabad["tags"] = canonical
            shabad["tags_source"] = "multi_llm_consensus_v1"

            # Take primary_theme/mood/brief_meaning from the first available LLM
            # in priority order. Field-level fallback, not shabad-level.
            for preferred in ("claude-sonnet-4-5", "qwen3:14b", "gemma2:27b", "deepseek-r1:14b", "llama3.1:8b"):
                r = llm_results.get(preferred)
                if isinstance(r, dict) and r.get("primary_theme"):
                    shabad["primary_theme"] = r.get("primary_theme", shabad.get("primary_theme", ""))
                    shabad["mood"] = r.get("mood", shabad.get("mood", ""))
                    shabad["brief_meaning"] = r.get("brief_meaning", shabad.get("brief_meaning", ""))
                    break

            updated += 1
        for tag in canonical:
            new_tag_counts[tag] = new_tag_counts.get(tag, 0) + 1

    if write_shabads:
        print(f"  updated {updated} shabads; skipped {skipped_partial} with <{min_votes} LLM responses")
    else:
        print(f"  consensus on {len(reasoning) - skipped_partial} shabads (vocabulary-only mode)")

    if sharpen:
        # Tail fold: a tag on fewer than TAIL_MIN_COUNT shabads can never form a
        # cluster; it only bloats the Constellation Map. Drop it and backfill the
        # shabad from its reserve (voted-in tags that were crowded out) so nothing
        # falls below MIN_TAGS_PER_SHABAD. Removing tags changes counts, which can
        # push more tags into the tail — so iterate to a fixed point.
        for round_num in range(1, 6):
            tail = {t for t, c in new_tag_counts.items() if c < TAIL_MIN_COUNT}
            if not tail:
                break
            dropped = 0
            for sid, tags in sid_to_tags.items():
                if not any(t in tail for t in tags):
                    continue
                keep = [t for t in tags if t not in tail]
                for cand in sid_to_reserve.get(sid, []):
                    if len(keep) >= MIN_TAGS_PER_SHABAD:
                        break
                    if cand not in tail and cand not in keep:
                        keep.append(cand)
                if len(keep) < MIN_TAGS_PER_SHABAD:
                    # Nothing clean left; keep the strongest originals.
                    keep = tags[:MIN_TAGS_PER_SHABAD]
                dropped += len(tags) - len(keep)
                sid_to_tags[sid] = keep
            new_tag_counts = {}
            for tags in sid_to_tags.values():
                for t in tags:
                    new_tag_counts[t] = new_tag_counts.get(t, 0) + 1
            print(f"  tail fold round {round_num}: dropped {len(tail)} tags ({dropped} assignments)")

        if write_shabads:
            for sid, tags in sid_to_tags.items():
                if sid in by_sid:
                    by_sid[sid]["tags"] = tags

        n = max(1, len(sid_to_tags))
        top = sorted(new_tag_counts.items(), key=lambda kv: -kv[1])
        mega_left = [t for t, c in top if c / n > MEGA_COVERAGE]
        tail_left = [t for t, c in top if c < 10]
        band = [t for t, c in top if 20 <= c <= 500]
        print("\n  --- sharpened distribution ---")
        print(f"  tags: {len(new_tag_counts)}   top coverage: {top[0][1]/n:.0%} ({top[0][0]})")
        print(f"  mega-tags remaining (>{MEGA_COVERAGE:.0%}): {len(mega_left)}")
        print(f"  dead tail (<10): {len(tail_left)}   useful band (20-500): {len(band)}")
        print(f"  avg tags/shabad: {sum(len(t) for t in sid_to_tags.values())/n:.1f}")

    # Build new tag vocabulary.
    vocab_path = output_vocab_path or NEW_VOCAB_PATH
    print(f"\nWriting {vocab_path.name}...")
    theme_tags = {
        tag: {"description": "", "gurbani_term": "", "count": count}
        for tag, count in sorted(new_tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    }
    vocab_path.write_text(
        json.dumps({"theme_tags": theme_tags, "mood_tags": {}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  {len(theme_tags)} consensus theme tags.")

    if write_shabads:
        print(f"\nWriting updated {SGGS_PATH.name}...")
        SGGS_PATH.write_text(
            json.dumps(shabads, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  saved {len(shabads)} shabads.")

    # Top tags preview.
    print("\nTop 20 consensus tags:")
    for tag, count in sorted(new_tag_counts.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {count:>5}  {tag}")


# ---- CLI --------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--llm", help=f"Run a single-LLM tagging pass. One of: {', '.join(ALL_LLMS)}")
    p.add_argument("--consensus", action="store_true", help="Apply consensus rule and rebuild tags.")
    p.add_argument(
        "--filter",
        choices=("all", "ak", "non-ak"),
        default="all",
        help="Restrict the LLM pass to AK-only or non-AK shabads (default: all). "
        "Used by Phase B.4 with --vocabulary to tag the rest of the corpus "
        "after the AK-only consensus has been built.",
    )
    p.add_argument(
        "--vocabulary",
        type=Path,
        default=None,
        help="Path to a vocabulary JSON file (output of Phase B.2). When given, "
        "the LLM pass uses the constrained-prompt template that asks the model "
        "to prefer tags from this list (Phase B.4 non-AK tagging).",
    )
    p.add_argument(
        "--ak-only",
        action="store_true",
        help="Restrict --consensus to Amrit Keertan shabads only. Phase B.2: "
        "produces the AK-derived canonical taxonomy that Phase B.4's "
        "--vocabulary then constrains the non-AK pass with.",
    )
    p.add_argument(
        "--output-vocab",
        type=Path,
        default=None,
        help="Where --consensus writes the resulting vocabulary file. Defaults to "
        "data/tag_vocabulary.json. Phase B.2 should pass data/ak_taxonomy.json so "
        "the full-corpus vocabulary isn't overwritten mid-pipeline.",
    )
    p.add_argument(
        "--vocab-only",
        action="store_true",
        help="With --consensus, emit only the vocabulary file; do NOT modify "
        "sggs_all_shabads.json. Used by Phase B.2 (the AK-only consensus is "
        "an intermediate step, not the final tagging).",
    )
    p.add_argument(
        "--sharpen",
        action="store_true",
        help="With --consensus, cap prompt-anchored mega-tags (>25%% corpus "
        "coverage) at 2 per shabad, promote distinctive tags, rescue high-IDF "
        "singletons for shabads that would otherwise be all-mega, and drop the "
        "dead tail. Fixes the prompt-example anchoring collapse without re-running LLMs.",
    )
    p.add_argument("--min-votes", type=int, default=2, help="Minimum LLM votes to keep a tag (default 2).")
    p.add_argument("--limit", type=int, default=None, help="Stop after N shabads (debug).")
    p.add_argument("--concurrency", type=int, default=8, help="Max concurrent in-flight calls.")
    p.add_argument("--save-every", type=int, default=50, help="Save reasoning file every N completions.")
    args = p.parse_args()

    if args.consensus and args.llm:
        raise SystemExit("Pass either --llm or --consensus, not both.")
    if not args.consensus and not args.llm:
        p.print_help()
        return

    if args.llm:
        run_pass(
            args.llm,
            args.concurrency,
            args.save_every,
            args.limit,
            filter_mode=args.filter,
            vocabulary_path=args.vocabulary,
        )
    else:
        run_consensus(
            args.min_votes,
            ak_only=args.ak_only,
            output_vocab_path=args.output_vocab,
            write_shabads=not args.vocab_only,
            sharpen=args.sharpen,
        )


if __name__ == "__main__":
    main()
