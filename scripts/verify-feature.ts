/**
 * Run a feature's verification layers in order and record evidence (AGENTS.md → Verification
 * layers, Definition of done). This is the machine-checkable gate behind `/verify-feature`
 * and the loop driver: it exits 1 at the first failing layer and never marks `passing`
 * with a layer that did not run.
 *
 *   pnpm harness:verify <id> [--allow-manual] [--dry-run] [--file feature_list.json]
 *
 * Entry format: `L1: <command> (optional description)`. The command is everything before a
 * trailing parenthesised description. `manual:` entries fail closed unless `--allow-manual`
 * is given, in which case they are recorded as waived by the current user; `--manual-observed
 * "<what you saw>"` records the observation instead. Evidence names `commit <sha>` when the tree
 * is clean and `working tree on <sha>` when it is not, so the hash is never misleading. With
 * `CI` set, L3 evidence says so: Playwright then serves the last `pnpm build` through
 * `next start` and retries a failing test up to twice (`playwright.config.ts`).
 */
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

import {
  FEATURE_LIST_PATH,
  readFeatureList,
  today,
  writeFeatureList,
  type Feature,
  type FeatureList,
} from './validate-feature-list'

export type Layer = 'L1' | 'L2' | 'L3' | 'manual'

export interface VerificationStep {
  raw: string
  layer: Layer
  /** The shell command for L1–L3; the description for manual steps. */
  command: string
  description: string
}

const stepPattern = /^(L1|L2|L3|manual): (.*)$/

/** Split `L2: pnpm test:integration -- x.int.test.ts (what it proves)` into its parts. */
export function parseStep(raw: string): VerificationStep {
  const match = stepPattern.exec(raw)
  if (!match) throw new Error(`verification step has no layer prefix: ${raw}`)
  const layer = match[1] as Layer
  const rest = (match[2] ?? '').trim()
  if (layer === 'manual') return { raw, layer, command: rest, description: rest }
  const trailing = /\s\(([^()]*)\)$/.exec(rest)
  const command = trailing ? rest.slice(0, trailing.index).trim() : rest
  return { raw, layer, command, description: trailing?.[1] ?? '' }
}

export interface StepResult {
  step: VerificationStep
  status: 'pass' | 'fail' | 'waived' | 'not_run'
  exitCode?: number
}

export interface VerifyOptions {
  allowManual?: boolean
  /** What the human observed for the manual steps; implies allowManual. */
  manualObserved?: string
  dryRun?: boolean
  /** Whether the working tree has uncommitted changes; injected by tests. */
  treeDirty?: boolean
  /** Runs a shell command and returns its exit code; injected by tests. */
  run?: (command: string) => number
  /** Reports whether Docker is available (needed for L2/L3); injected by tests. */
  dockerAvailable?: () => boolean
  /** Whether `CI` is set (changes how L3 runs); injected by tests. */
  ci?: boolean
  commit?: string
  date?: string
  user?: string
  log?: (line: string) => void
}

export interface VerifyOutcome {
  ok: boolean
  results: StepResult[]
  evidence: string[]
  message: string
}

function defaultRun(command: string): number {
  const result = spawnSync('sh', ['-c', command], {
    cwd: path.dirname(FEATURE_LIST_PATH),
    stdio: 'inherit',
  })
  return result.status ?? 1
}

function defaultDockerAvailable(): boolean {
  return spawnSync('docker', ['info'], { stdio: 'ignore' }).status === 0
}

function treeIsDirty(): boolean {
  const out = spawnSync('git', ['status', '--porcelain'], { encoding: 'utf8' })
  return out.status === 0 && out.stdout.trim() !== ''
}

function headCommit(): string {
  const out = spawnSync('git', ['rev-parse', '--short', 'HEAD'], { encoding: 'utf8' })
  return out.status === 0 ? out.stdout.trim() : 'unknown'
}

/**
 * Pure-ish core: runs the steps of `feature`, mutates it to `passing` with evidence on success.
 * Does not write the file; callers persist the list.
 */
export function verifyFeature(feature: Feature, options: VerifyOptions = {}): VerifyOutcome {
  const run = options.run ?? defaultRun
  const dockerAvailable = options.dockerAvailable ?? defaultDockerAvailable
  const log = options.log ?? ((line: string) => console.log(line))
  const date = options.date ?? today()
  const commit = options.commit ?? headCommit()
  const dirty = options.treeDirty ?? treeIsDirty()
  const where = dirty ? `working tree on ${commit}` : `commit ${commit}`
  const ci = options.ci ?? Boolean(process.env.CI)
  const allowManual = options.allowManual || Boolean(options.manualObserved)
  const user = options.user ?? process.env.USER ?? 'unknown'
  const steps = feature.verification.map(parseStep)
  const results: StepResult[] = steps.map((step) => ({ step, status: 'not_run' }))

  const manual = steps.filter((s) => s.layer === 'manual')
  if (manual.length > 0 && !allowManual) {
    return {
      ok: false,
      results,
      evidence: [],
      message: `${feature.id} has ${manual.length} manual verification step(s); run them yourself and re-run with --allow-manual, or leave the feature to a human session`,
    }
  }
  if (
    steps.some((s) => s.layer === 'L2' || s.layer === 'L3') &&
    !options.dryRun &&
    !dockerAvailable()
  ) {
    return {
      ok: false,
      results,
      evidence: [],
      message: `${feature.id} needs Docker for L2/L3 and docker info failed; start Docker Desktop (pnpm db:up) first`,
    }
  }

  const evidence: string[] = []
  for (const [index, step] of steps.entries()) {
    const result = results[index]
    if (!result) continue
    if (step.layer === 'manual') {
      result.status = 'waived'
      if (options.manualObserved) {
        log(`[manual] ${step.description} → observed by ${user}: ${options.manualObserved}`)
        evidence.push(
          `${date} manual: ${step.description} → observed by ${user}: ${options.manualObserved} (${where})`,
        )
      } else {
        log(`[manual] ${step.description} → waived (--allow-manual by ${user})`)
        evidence.push(
          `${date} manual: ${step.description} → waived via --allow-manual by ${user} (${where})`,
        )
      }
      continue
    }
    if (options.dryRun) {
      log(`[${step.layer}] would run: ${step.command}`)
      continue
    }
    log(`\n==> [${step.layer}] ${step.command}`)
    const started = Date.now()
    const code = run(step.command)
    const seconds = ((Date.now() - started) / 1000).toFixed(0)
    result.exitCode = code
    if (code !== 0) {
      result.status = 'fail'
      return {
        ok: false,
        results,
        evidence: [],
        message: `${feature.id} failed at ${step.layer}: \`${step.command}\` exited ${code} after ${seconds}s; later layers were not run`,
      }
    }
    result.status = 'pass'
    log(`[${step.layer}] pass (${seconds}s)`)
    const docker = step.layer === 'L1' ? '' : ', Docker available'
    const mode = step.layer === 'L3' && ci ? ', CI=1: next start on the last build, retries 2' : ''
    evidence.push(`${date} ${step.command} → pass (${where}${docker}${mode})`)
  }

  if (options.dryRun) {
    return {
      ok: true,
      results,
      evidence: [],
      message: `${feature.id} dry run: ${steps.length} step(s) listed, nothing ran`,
    }
  }
  feature.evidence.push(...evidence)
  feature.status = 'passing'
  return {
    ok: true,
    results,
    evidence,
    message: `${feature.id} → passing (${evidence.length} evidence line(s) added)`,
  }
}

function report(outcome: VerifyOutcome): string {
  const rows = outcome.results.map((r) => `  ${r.status.padEnd(8)} ${r.step.raw}`)
  return [...rows, outcome.message].join('\n')
}

function main(argv: string[]): void {
  const { values, positionals } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      'allow-manual': { type: 'boolean', default: false },
      'manual-observed': { type: 'string' },
      'dry-run': { type: 'boolean', default: false },
      file: { type: 'string' },
    },
  })
  const [id] = positionals
  if (!id) {
    console.error(
      'usage: pnpm harness:verify <F-NNN> [--allow-manual | --manual-observed "…"] [--dry-run]',
    )
    process.exit(1)
  }
  const file = values.file ? path.resolve(values.file) : undefined
  const list: FeatureList = readFeatureList(file)
  const feature = list.features.find((f) => f.id === id)
  if (!feature) {
    const candidates = list.features
      .filter((f) => f.status === 'in_progress' || f.status === 'not_started')
      .map((f) => `${f.id} (${f.status})`)
    console.error(`unknown feature ${id}; candidates: ${candidates.join(', ') || 'none'}`)
    process.exit(1)
  }
  if (feature.status !== 'in_progress' && feature.status !== 'passing') {
    console.error(
      `${feature.id} is ${feature.status}; activate it first (pnpm harness:feature activate ${feature.id})`,
    )
    process.exit(1)
  }

  const outcome = verifyFeature(feature, {
    allowManual: values['allow-manual'],
    manualObserved: values['manual-observed'],
    dryRun: values['dry-run'],
  })
  console.log(`\n${report(outcome)}`)
  if (!outcome.ok) process.exit(1)
  if (values['dry-run']) return
  list.last_updated = today()
  writeFeatureList(list, { file })
  console.log('feature_list.json updated; /clock-out still has to update PROGRESS.md and commit')
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main(process.argv.slice(2))
  } catch (error) {
    console.error(error instanceof Error ? error.message : error)
    process.exit(1)
  }
}
