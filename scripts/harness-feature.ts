/**
 * Feature state transitions for `feature_list.json` (AGENTS.md → Working rules).
 * Every command re-validates the file and rewrites it through Prettier, so a human,
 * a skill (`/clock-in`) and the loop driver all change state the same way.
 *
 *   pnpm harness:feature next [--json] [--include-manual] [--exclude F-001,F-002]
 *   pnpm harness:feature show <id> [--json]
 *   pnpm harness:feature list [--status not_started]
 *   pnpm harness:feature activate <id>            not_started → in_progress (WIP=1, deps passing)
 *   pnpm harness:feature block <id> --reason "…"  any → blocked
 *   pnpm harness:feature unblock <id>             blocked → not_started
 *   pnpm harness:feature attempt <id> [--reason "…"]
 *        attempts += 1; auto-blocks at max_attempts (feature field or harness.config.json)
 */
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

import {
  FEATURE_LIST_PATH,
  featureStatuses,
  isHumanOnly,
  isReady,
  nextReadyFeature,
  readFeatureList,
  today,
  writeFeatureList,
  type Feature,
  type FeatureList,
  type FeatureStatus,
} from './validate-feature-list'

const DEFAULT_MAX_ATTEMPTS = 2

function defaultMaxAttempts(): number {
  const configPath = path.resolve(path.dirname(FEATURE_LIST_PATH), 'harness.config.json')
  if (!existsSync(configPath)) return DEFAULT_MAX_ATTEMPTS
  try {
    const config = JSON.parse(readFileSync(configPath, 'utf8')) as {
      caps?: { maxAttempts?: number }
    }
    return config.caps?.maxAttempts ?? DEFAULT_MAX_ATTEMPTS
  } catch {
    return DEFAULT_MAX_ATTEMPTS
  }
}

function fail(message: string): never {
  console.error(`harness-feature: ${message}`)
  process.exit(1)
}

function requireFeature(list: FeatureList, id: string | undefined): Feature {
  if (!id) fail('feature id is required (e.g. F-042)')
  const feature = list.features.find((f) => f.id === id)
  if (!feature) {
    const candidates = list.features
      .filter((f) => f.status === 'in_progress' || f.status === 'not_started')
      .map((f) => `${f.id} (${f.status})`)
    fail(`unknown feature ${id}; candidates: ${candidates.join(', ') || 'none'}`)
  }
  return feature
}

function save(list: FeatureList, file?: string): void {
  list.last_updated = today()
  writeFeatureList(list, { file })
}

function describe(feature: Feature, list: FeatureList): string {
  const lines = [
    `${feature.id} · ${feature.title} [${feature.status}] priority ${feature.priority} · area ${feature.area}`,
    `  behaviour: ${feature.user_visible_behavior}`,
  ]
  if (feature.ticket) lines.push(`  ticket: ${feature.ticket}`)
  if (feature.spec) lines.push(`  spec: ${feature.spec}`)
  if (feature.depends_on.length) {
    const byId = new Map(list.features.map((f) => [f.id, f]))
    lines.push(
      `  depends_on: ${feature.depends_on.map((d) => `${d} (${byId.get(d)?.status ?? '?'})`).join(', ')}`,
    )
  }
  lines.push(`  verification:`)
  for (const step of feature.verification) lines.push(`    - ${step}`)
  if (feature.evidence.length) {
    lines.push(`  evidence:`)
    for (const line of feature.evidence) lines.push(`    - ${line}`)
  }
  lines.push(
    `  attempts: ${feature.attempts}${feature.max_attempts ? `/${feature.max_attempts}` : ''}`,
  )
  lines.push(`  ready: ${isReady(feature, list)} · human-only: ${isHumanOnly(feature)}`)
  if (feature.notes) lines.push(`  notes: ${feature.notes}`)
  return lines.join('\n')
}

function appendNote(feature: Feature, note: string): void {
  feature.notes = feature.notes.trim() ? `${feature.notes.trim()} ${note}` : note
}

function main(argv: string[]): void {
  const { values, positionals } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      json: { type: 'boolean', default: false },
      'include-manual': { type: 'boolean', default: false },
      exclude: { type: 'string' },
      status: { type: 'string' },
      reason: { type: 'string' },
      file: { type: 'string' },
    },
  })
  const [command, id] = positionals
  const file = values.file ? path.resolve(values.file) : undefined
  const list = readFeatureList(file)

  switch (command) {
    case 'next': {
      const exclude = values.exclude ? values.exclude.split(',').map((s) => s.trim()) : []
      const feature = nextReadyFeature(list, {
        includeHumanOnly: values['include-manual'],
        exclude,
      })
      if (values.json) {
        console.log(JSON.stringify(feature ?? null))
      } else if (feature) {
        console.log(feature.id)
      }
      process.exit(feature ? 0 : 3)
      break
    }
    case 'show': {
      const feature = requireFeature(list, id)
      console.log(values.json ? JSON.stringify(feature, null, 2) : describe(feature, list))
      break
    }
    case 'list': {
      const status = values.status as FeatureStatus | undefined
      if (status && !featureStatuses.includes(status)) fail(`unknown status ${status}`)
      const rows = list.features
        .filter((f) => !status || f.status === status)
        .sort((a, b) => a.priority - b.priority)
        .map(
          (f) =>
            `${f.id}  ${f.status.padEnd(11)} p${String(f.priority).padStart(3)}  ${f.area.padEnd(12)} ${f.title}${
              isReady(f, list) ? (isHumanOnly(f) ? '  [ready, human-only]' : '  [ready]') : ''
            }`,
        )
      console.log(rows.join('\n'))
      break
    }
    case 'activate': {
      const feature = requireFeature(list, id)
      const active = list.features.find((f) => f.status === 'in_progress')
      if (active && active.id !== feature.id) {
        fail(`${active.id} is already in_progress (WIP=1); finish or block it first`)
      }
      if (feature.status === 'in_progress') {
        console.log(`${feature.id} is already in_progress`)
        break
      }
      if (feature.status !== 'not_started') {
        fail(
          `${feature.id} is ${feature.status}; only not_started features can be activated (unblock first)`,
        )
      }
      if (!isReady(feature, list)) {
        const byId = new Map(list.features.map((f) => [f.id, f]))
        const waiting = feature.depends_on.filter((d) => byId.get(d)?.status !== 'passing')
        fail(`${feature.id} depends on non-passing ${waiting.join(', ')}`)
      }
      feature.status = 'in_progress'
      save(list, file)
      console.log(`${feature.id} → in_progress`)
      break
    }
    case 'block': {
      const feature = requireFeature(list, id)
      if (!values.reason?.trim()) fail('--reason is required')
      feature.status = 'blocked'
      appendNote(feature, `Blocked ${today()}: ${values.reason.trim()}`)
      save(list, file)
      console.log(`${feature.id} → blocked`)
      break
    }
    case 'unblock': {
      const feature = requireFeature(list, id)
      if (feature.status !== 'blocked') fail(`${feature.id} is ${feature.status}, not blocked`)
      feature.status = 'not_started'
      appendNote(feature, `Unblocked ${today()}.`)
      save(list, file)
      console.log(`${feature.id} → not_started`)
      break
    }
    case 'attempt': {
      const feature = requireFeature(list, id)
      feature.attempts += 1
      const max = feature.max_attempts ?? defaultMaxAttempts()
      const reason = values.reason?.trim()
      if (reason) appendNote(feature, `Attempt ${feature.attempts} failed ${today()}: ${reason}`)
      let outcome = `${feature.id} attempts ${feature.attempts}/${max}`
      if (feature.attempts >= max && feature.status !== 'passing') {
        feature.status = 'blocked'
        appendNote(feature, `Auto-blocked after ${feature.attempts} attempts; needs a human.`)
        outcome += ' → blocked'
      }
      save(list, file)
      console.log(outcome)
      break
    }
    default:
      fail(`unknown command ${command ?? ''}; see the header of scripts/harness-feature.ts`)
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main(process.argv.slice(2))
  } catch (error) {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  }
}
