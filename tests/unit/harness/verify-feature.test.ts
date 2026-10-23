import { describe, expect, it } from 'vitest'

import { parseStep, verifyFeature } from '../../../scripts/verify-feature'
import type { Feature } from '../../../scripts/validate-feature-list'

const feature = (verification: string[]): Feature => ({
  id: 'F-042',
  priority: 42,
  area: 'auth',
  title: 'Registration',
  user_visible_behavior: 'A visitor can register.',
  status: 'in_progress',
  depends_on: [],
  verification,
  evidence: [],
  attempts: 0,
  notes: '',
})

const quiet = {
  log: () => undefined,
  date: '2026-09-06',
  commit: 'abc1234',
  user: 'tester',
  treeDirty: false,
  ci: false,
}

describe('parseStep', () => {
  it('splits the layer, the command and a trailing description', () => {
    expect(
      parseStep('L2: pnpm test:integration -- tests/integration/auth.int.test.ts (user created)'),
    ).toEqual({
      raw: 'L2: pnpm test:integration -- tests/integration/auth.int.test.ts (user created)',
      layer: 'L2',
      command: 'pnpm test:integration -- tests/integration/auth.int.test.ts',
      description: 'user created',
    })
    expect(parseStep('L1: pnpm check').command).toBe('pnpm check')
    expect(
      parseStep('L3: pnpm test:e2e -- --project chromium tests/e2e/a.spec.ts (click map → ok)')
        .command,
    ).toBe('pnpm test:e2e -- --project chromium tests/e2e/a.spec.ts')
    expect(parseStep('manual: look at the page').command).toBe('look at the page')
  })
})

describe('verifyFeature', () => {
  it('runs layers in order and records evidence on success', () => {
    const ran: string[] = []
    const f = feature(['L1: pnpm check', 'L1: pnpm typecheck (types)'])
    const outcome = verifyFeature(f, { ...quiet, run: (cmd) => (ran.push(cmd), 0) })
    expect(outcome.ok).toBe(true)
    expect(ran).toEqual(['pnpm check', 'pnpm typecheck'])
    expect(f.status).toBe('passing')
    expect(f.evidence).toEqual([
      '2026-09-06 pnpm check → pass (commit abc1234)',
      '2026-09-06 pnpm typecheck → pass (commit abc1234)',
    ])
  })

  it('stops at the first failing layer and leaves the feature untouched', () => {
    const ran: string[] = []
    const f = feature(['L1: pnpm check', 'L2: pnpm test:integration', 'L3: pnpm test:e2e'])
    const outcome = verifyFeature(f, {
      ...quiet,
      dockerAvailable: () => true,
      run: (cmd) => (ran.push(cmd), cmd.includes('integration') ? 1 : 0),
    })
    expect(outcome.ok).toBe(false)
    expect(outcome.message).toMatch(/failed at L2/)
    expect(ran).toEqual(['pnpm check', 'pnpm test:integration'])
    expect(outcome.results.map((r) => r.status)).toEqual(['pass', 'fail', 'not_run'])
    expect(f.status).toBe('in_progress')
    expect(f.evidence).toEqual([])
  })

  it('fails closed on manual steps unless waived, and records the waiver', () => {
    const f = feature(['L1: pnpm check', 'manual: README row matches tsconfig'])
    expect(verifyFeature(f, { ...quiet, run: () => 0 }).ok).toBe(false)
    expect(f.status).toBe('in_progress')
    const waived = verifyFeature(f, { ...quiet, run: () => 0, allowManual: true })
    expect(waived.ok).toBe(true)
    expect(f.evidence[1]).toMatch(
      /manual: README row matches tsconfig → waived via --allow-manual by tester/,
    )
  })

  it('records the observation for manual steps and names a dirty tree honestly', () => {
    const f = feature(['L2: pnpm test:integration', 'manual: look at the page'])
    const outcome = verifyFeature(f, {
      ...quiet,
      treeDirty: true,
      dockerAvailable: () => true,
      run: () => 0,
      manualObserved: 'page renders in Figtree',
    })
    expect(outcome.ok).toBe(true)
    expect(f.evidence).toEqual([
      '2026-09-06 pnpm test:integration → pass (working tree on abc1234, Docker available)',
      '2026-09-06 manual: look at the page → observed by tester: page renders in Figtree (working tree on abc1234)',
    ])
  })

  it('says when L3 ran in CI mode (production build, retries)', () => {
    const f = feature(['L2: pnpm test:integration', 'L3: pnpm test:e2e'])
    verifyFeature(f, { ...quiet, ci: true, dockerAvailable: () => true, run: () => 0 })
    expect(f.evidence).toEqual([
      '2026-09-06 pnpm test:integration → pass (commit abc1234, Docker available)',
      '2026-09-06 pnpm test:e2e → pass (commit abc1234, Docker available, CI=1: next start on the last build, retries 2)',
    ])
  })

  it('refuses to run L2/L3 without Docker instead of skipping them', () => {
    const f = feature(['L1: pnpm check', 'L3: pnpm test:e2e'])
    const outcome = verifyFeature(f, { ...quiet, run: () => 0, dockerAvailable: () => false })
    expect(outcome.ok).toBe(false)
    expect(outcome.message).toMatch(/needs Docker/)
  })

  it('dry run lists steps without running or mutating anything', () => {
    let ran = 0
    const f = feature(['L1: pnpm check'])
    const outcome = verifyFeature(f, { ...quiet, dryRun: true, run: () => (ran++, 0) })
    expect(outcome.ok).toBe(true)
    expect(ran).toBe(0)
    expect(f.status).toBe('in_progress')
  })
})
