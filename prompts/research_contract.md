## Output contract (validated by a hook when you finish)

Write `runs/<run_id>/02_research/{{ agent.dimension }}.md` with exactly these parts:

1. `# {{ agent.dimension }}` and a 2–3 sentence summary of what the evidence says.
2. `## Findings`: one short paragraph per research question.
   - **Every factual sentence ends with `[src: <url>]`.**
   - **Every number** is immediately followed by a block quote from the source, verbatim, at most 60 words:
     ```
     The municipality had 1 900 residents in 2024 [src: https://pxdata.stat.fi/...].
     > Rääkkylä väkiluku 31.12.2024: 1 900
     ```
3. `## Candidate claims`: one or more ```json fenced blocks, each holding a JSON list of claim objects:
   ```json
   [
     {
       "claim_id": "{{ agent.dimension }}-001",
       "dimension": "{{ agent.dimension }}",
       "statement": "One atomic, checkable statement.",
       "value": 1900,
       "unit": "persons",
       "source_url": "https://…",
       "source_title": "Page title",
       "quote": "Verbatim quote of at most 60 words that contains the value.",
       "published_date": "2025-03-01",
       "source_type": "official",
       "confidence": 0.8,
       "flags": []
     }
   ]
   ```
   - `claim_id`: `{{ agent.dimension }}-NNN`, numbered from 001, unique.
   - `value`/`unit`: `null` when the claim isn't numeric. Use units such as `EUR`, `EUR/month`, `EUR/unit`, `persons`, `companies`, `%`.
   - `published_date`: ISO date, or `null` if the page doesn't show one.
   - `source_type`: one of `official`, `api`, `industry`, `news`, `forum`, `vendor`.
   - `confidence`: 0–1, how well the source supports the statement.
   - `flags`: kill-trigger names, only when the quote directly supports them: {% for t in kill_triggers %}`{{ t }}`{% if not loop.last %}, {% endif %}{% endfor %}.
   - Don't include `retrieved_at` or `verification`; the verifier fills them in.
4. `## Gaps`: a bullet list of questions you couldn't answer and what source would answer them.
