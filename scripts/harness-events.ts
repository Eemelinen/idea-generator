/**
 * Turns the `claude -p --output-format stream-json` event stream of a driver-run session into
 * readable log lines (scripts/harness-loop.ts, docs/harness/README.md → Reading a run).
 *
 * Pure: `describeEvent()` takes one parsed stream message and the per-session state and returns
 * the lines to print. It names every tool call (Bash description or command, file paths, skill
 * names), surfaces failed tool calls, permission denials and hook blocks with their reason, and
 * reports harness milestones (activate, verify, clean-state check, test layers, commits) with
 * their outcome.
 */
import path from 'node:path'

export interface StreamState {
  cwd: string
  startedAt: number
  lastEventAt: number
  turns: number
  outputTokens: number
  /** Tool calls waiting for their result, by tool_use id. */
  pending: Map<string, { name: string; milestone?: string }>
  seenMessages: Set<string>
}

export function newStreamState(cwd: string, now: number = Date.now()): StreamState {
  return {
    cwd,
    startedAt: now,
    lastEventAt: now,
    turns: 0,
    outputTokens: 0,
    pending: new Map(),
    seenMessages: new Set(),
  }
}

type Json = Record<string, unknown>

const oneLine = (text: string, max = 160): string => {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}

const str = (value: unknown): string => (typeof value === 'string' ? value : '')

/** Repo-relative path with forward slashes when the file is inside `cwd`. */
export function shortPath(file: string, cwd: string): string {
  if (!file) return '?'
  const rel = path.relative(cwd, path.resolve(cwd, file))
  const inside = rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel)
  return (inside ? rel : file).split(path.sep).join('/')
}

/**
 * Matches `body` only where a command starts (line start, after `;`, `&&`, `|`, `(`), optionally
 * after `VAR=value` prefixes, so `grep "pnpm test:e2e" PROGRESS.md` is not mistaken for a test run.
 */
const atCommandStart = (body: string) =>
  new RegExp(`(?:^|[;&|(\\n]\\s*)(?:[A-Z_]+=\\S*\\s+)*${body}`)

const VERB = atCommandStart(
  'pnpm (?:-s |--silent )?harness:feature (activate|block|unblock|attempt) (F-\\d{3})',
)
const VERIFY = atCommandStart('pnpm (?:-s |--silent )?harness:verify F-\\d{3}')
const CLEAN_STATE = atCommandStart(
  '(?:\\./)?(?:scripts/clean-state-check\\.sh|pnpm harness:clean-state)',
)
const COMMIT = atCommandStart('git commit\\b')
const CHECK = atCommandStart('pnpm check(?:\\s|$)')
const LAYER = atCommandStart('pnpm test:(unit|integration|e2e)\\b')

/** The harness step a Bash command represents, if any. */
export function milestoneOf(command: string): string | undefined {
  const verb = VERB.exec(command)
  if (verb) return `feature ${verb[1]} ${verb[2]}`
  if (VERIFY.test(command) && !/--dry-run/.test(command)) return 'harness:verify'
  if (CLEAN_STATE.test(command)) return 'clean-state check'
  if (COMMIT.test(command)) return 'git commit'
  if (CHECK.test(command)) return 'L1 pnpm check'
  const layer = LAYER.exec(command)
  if (layer)
    return { unit: 'L1', integration: 'L2', e2e: 'L3' }[layer[1] as 'unit'] + ` test:${layer[1]}`
  return undefined
}

/** One line naming what a tool call does. */
export function describeToolUse(name: string, input: Json, cwd: string): string {
  switch (name) {
    case 'Bash': {
      const command = oneLine(str(input.command), 120)
      const description = str(input.description)
      return description ? `bash: ${oneLine(description, 90)} · ${command}` : `bash: ${command}`
    }
    case 'Read':
    case 'Edit':
    case 'Write':
    case 'MultiEdit':
    case 'NotebookEdit':
      return `${name.toLowerCase()}: ${shortPath(str(input.file_path) || str(input.notebook_path), cwd)}`
    case 'Glob':
      return `glob: ${str(input.pattern)}${input.path ? ` in ${shortPath(str(input.path), cwd)}` : ''}`
    case 'Grep':
      return `grep: ${oneLine(str(input.pattern), 80)}${input.path ? ` in ${shortPath(str(input.path), cwd)}` : ''}`
    case 'Skill':
      return `skill: /${str(input.skill)}${input.args ? ` ${str(input.args)}` : ''}`
    case 'Agent':
    case 'Task':
      return `agent: ${oneLine(str(input.description) || str(input.prompt), 100)}`
    case 'WebFetch':
    case 'WebSearch':
      return `${name.toLowerCase()}: ${oneLine(str(input.url) || str(input.query), 100)}`
    default: {
      const first = Object.values(input).find((v) => typeof v === 'string')
      return `tool ${name}${first ? `: ${oneLine(String(first), 100)}` : ''}`
    }
  }
}

function resultText(content: unknown): string {
  if (typeof content === 'string') return content
  if (Array.isArray(content))
    return content
      .map((part) => (part && typeof part === 'object' ? str((part as Json).text) : ''))
      .join('\n')
  return ''
}

/** The lines of a milestone's output worth repeating: test totals, gate verdicts, the commit. */
export function summarizeOutput(milestone: string, output: string): string {
  const lines = output
    .replace(/\x1b\[[0-9;]*m/g, '')
    .split('\n')
    .map((l) => l.trim())
    // JSON log lines and Claude Code's own file-change notes are noise here.
    .filter((l) => l && !l.startsWith('{') && !l.startsWith('[This command modified'))
  if (milestone === 'git commit') {
    const head = lines.find((l) => /^\[[^\]]+ [0-9a-f]{7,}\]/.test(l))
    if (head) return head
  }
  const useful = lines.filter((l) =>
    /^(Test Files|Tests)\s|\d+ (passed|failed|flaky)\b|→ (pass|fail|in_progress|passing|blocked|not_started)\b|\[FAIL\]|^clean-state:|feature_list\.json OK|✖ \d+ problems?|exit=\d/.test(
      l,
    ),
  )
  return oneLine(useful.slice(-3).join(' · ') || lines.slice(-1)[0] || '', 220)
}

/** How a finished milestone went, judged from its output as well as its exit code (pipes hide failures). */
export function milestoneStatus(
  output: string,
  isError: boolean,
): 'failed' | 'background' | 'warning' | 'ok' {
  if (/moved to the background|running in background with ID/i.test(output)) return 'background'
  if (isError) return 'failed'
  if (
    /\b[1-9]\d* failed\b|\[FAIL\]|check\(s\) failed|✖ \d+ problems?|exit=[1-9]|ELIFECYCLE|Command failed with exit code [1-9]|Unhandled Errors?\b/.test(
      output,
    )
  )
    return 'warning'
  return 'ok'
}

function hookLines(msg: Json): string[] {
  if (msg.subtype !== 'hook_response') return []
  const hook = str(msg.hook_name) || 'hook'
  const stdout = str(msg.stdout)
  const stderr = str(msg.stderr)
  if (msg.exit_code === 2) return [`⛔ ${hook} blocked: ${oneLine(stderr || stdout, 200)}`]
  try {
    const out = JSON.parse(stdout) as Json
    const specific = (out.hookSpecificOutput ?? {}) as Json
    const decision = str(specific.permissionDecision)
    if (decision === 'deny' || decision === 'ask')
      return [`⛔ ${hook} ${decision}: ${oneLine(str(specific.permissionDecisionReason), 200)}`]
    if (out.decision === 'block')
      return [`⛔ ${hook} kept the session going: ${oneLine(str(out.reason), 200)}`]
  } catch {
    // not JSON: an informational hook (session start, formatter)
  }
  return []
}

/** Log lines for one stream-json message; updates `state`. */
export function describeEvent(msg: Json, state: StreamState, now: number = Date.now()): string[] {
  state.lastEventAt = now
  const lines: string[] = []
  if (msg.type === 'system') {
    if (msg.subtype === 'init')
      lines.push(
        `session started · model ${str(msg.model)} · permission mode ${str(msg.permissionMode)}`,
      )
    if (msg.subtype === 'permission_denied')
      lines.push(`⛔ permission denied: ${oneLine(JSON.stringify(msg.tool_input ?? msg), 200)}`)
    lines.push(...hookLines(msg))
    return lines
  }
  const message = (msg.message ?? {}) as Json
  const content = Array.isArray(message.content) ? (message.content as Json[]) : []
  if (msg.type === 'assistant') {
    const id = str(message.id)
    if (id && !state.seenMessages.has(id)) {
      state.seenMessages.add(id)
      state.turns += 1
    }
    const usage = (message.usage ?? {}) as Json
    if (typeof usage.output_tokens === 'number') state.outputTokens += usage.output_tokens
    for (const block of content) {
      if (block.type === 'text' && str(block.text))
        lines.push(`claude: ${oneLine(str(block.text), 200)}`)
      if (block.type === 'tool_use') {
        const name = str(block.name)
        const input = (block.input ?? {}) as Json
        const milestone = name === 'Bash' ? milestoneOf(str(input.command)) : undefined
        state.pending.set(str(block.id), { name, milestone })
        lines.push(describeToolUse(name, input, state.cwd))
        if (milestone) lines.push(`▶ ${milestone} started`)
      }
    }
    return lines
  }
  if (msg.type === 'user') {
    for (const block of content) {
      if (block.type !== 'tool_result') continue
      const call = state.pending.get(str(block.tool_use_id))
      state.pending.delete(str(block.tool_use_id))
      const output = resultText(block.content)
      if (call?.milestone) {
        const status = milestoneStatus(output, block.is_error === true)
        const summary = status === 'background' ? '' : summarizeOutput(call.milestone, output)
        const label = {
          ok: `✓ ${call.milestone} done`,
          warning: `⚠ ${call.milestone} reported failures`,
          failed: `✗ ${call.milestone} failed`,
          background: `… ${call.milestone} continues in the background`,
        }[status]
        lines.push(`${label}${summary ? `: ${summary}` : ''}`)
      } else if (block.is_error) {
        lines.push(`✗ ${call?.name ?? 'tool'} error: ${oneLine(output, 200)}`)
      }
    }
    return lines
  }
  return lines
}

/** Periodic progress line for long sessions. */
export function heartbeat(state: StreamState, now: number = Date.now()): string {
  const minutes = Math.round((now - state.startedAt) / 60000)
  const idle = Math.round((now - state.lastEventAt) / 1000)
  const running = [...state.pending.values()].map((p) => p.milestone ?? p.name)
  return `… ${minutes} min · ${state.turns} turns · ${Math.round(state.outputTokens / 1000)}k output tokens · last event ${idle} s ago${running.length ? ` · running: ${running.join(', ')}` : ''}`
}
