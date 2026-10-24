# Similar projects

Existing tools and repositories that overlap with Ideaforge, collected during planning (research
report of October 2026, before [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) was written).
None covers the whole Ideaforge flow (Finland-aware research, a verified claim ledger, scoring in
Python and a debate stage), so the plan borrows ideas from them rather than building on one.

Stars, prices and features were taken from the report and change often; check the repository
before copying code or relying on a licence.

## Open-source idea validators

| Repository                                                                                    | Stack                                | What Ideaforge took from it                                                                                                                                                                                   |
| --------------------------------------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [mikamika06/idea-evaluator](https://github.com/mikamika06/idea-evaluator)                     | Claude Code plugin                   | The closest match. The kill-cause scout (`research-killcause`), verified quotes, the author-blind judge, the `INSUFFICIENT_DATA` verdict, the `AS_OF` back-test (`--as-of`, IF-503) and the local page cache. |
| [shamiquekhan/Startup-idea-validator](https://github.com/shamiquekhan/Startup-idea-validator) | Python, MIT, optional Ollama         | Every claim linked to a URL; scoring with kill criteria.                                                                                                                                                      |
| [martian7777/Startup-Idea-Validator](https://github.com/martian7777/Startup-Idea-Validator)   | Google ADK, FastAPI, Next.js, MIT    | A deterministic Python scorer ("Python decides, the model proposes"). Its source-age decay and diminishing returns are not built.                                                                             |
| [Lilli-Ai/startup-idea-validator](https://github.com/Lilli-Ai/startup-idea-validator)         | LangGraph, Qdrant, Tavily, Langfuse  | Competitor lookup over the yc-oss list of Y Combinator companies: the Phase 6 local competitor index (not built).                                                                                             |
| [ferdinandobons/startup-skill](https://github.com/ferdinandobons/startup-skill)               | Claude Code skills, MIT              | Market and competitor research packaged as skills.                                                                                                                                                            |
| samch0203/ai-startup-idea-validator                                                           | React + Python                       | Separate agents for market, competitors, SWOT/risk, MVP and report.                                                                                                                                           |
| PreuveAI/startup-idea-validation-mcp                                                          | MCP server of a commercial validator | Nothing: tied to a paid service.                                                                                                                                                                              |

## Commercial validators

Hosted and closed, with no evidence chain and no Finnish rules. Listed for comparison only.

| Tool        | What it is                                          | Worth borrowing                      |
| ----------- | --------------------------------------------------- | ------------------------------------ |
| ValidatorAI | Conversational advisor with a 0–100 score           | The "brutal honesty" tone            |
| DimeADozen  | Long-form cited report                              | Report structure, citation density   |
| IdeaBuddy   | Planning workspace: canvas, financial plan, BP      | The business-plan section skeleton   |
| IdeaProof   | Validation, business plan and branding              | Nothing (unpublished accuracy claim) |
| Preuve AI   | "Source-linked" validation; publishes an MCP server | See PreuveAI above                   |
| FounderPal  | Marketing-strategy generator with a free validator  | Little                               |
| VenturusAI  | Business-plan-style analysis (SWOT etc.)            | Little                               |

## Deep-research agents

The architecture pattern: a lead agent plans, parallel subagents research with fresh contexts, and
a separate pass checks citations.

| Project                                                                                                                     | Lesson for Ideaforge                                                                                         |
| --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| [Anthropic multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system) (write-up) | One subagent per rubric dimension, a dedicated verification pass, a small eval set (the golden set, IF-501). |
| [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research)                                       | A model per stage, and a pause for approval after planning (stage 1 plan approval).                          |
| GPT Researcher                                                                                                              | Planner → executors → publisher with depth and breadth settings (the presets in `config/budget.yaml`).       |
| Stanford STORM / Co-STORM                                                                                                   | Research questions generated from perspectives (customer, regulator, competitor).                            |
| Local Deep Research                                                                                                         | Fully offline runs; not relevant while Ideaforge runs on Claude.                                             |

## Not used

The report also listed search and scraping MCP servers (Brave Search, Tavily, Exa, Firecrawl) and
the MCP reference servers. Ideaforge uses none of them: the paid ones break the no-paid-services
rule (§0), and Claude Code's built-in WebSearch and WebFetch plus the `ideaforge.fi` clients cover
the rest.
