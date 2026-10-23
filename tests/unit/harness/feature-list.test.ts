import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  FEATURE_LIST_PATH,
  isHumanOnly,
  isReady,
  nextReadyFeature,
  normalizeFeature,
  summarizeFeatureList,
  validateFeatureList,
  type Feature,
  type FeatureList,
} from '../../../scripts/validate-feature-list'

const committed = (): unknown => JSON.parse(readFileSync(FEATURE_LIST_PATH, 'utf8'))

const feature = (overrides: Partial<Feature> & Pick<Feature, 'id'>): Feature => ({
  priority: Number(overrides.id.slice(2)),
  area: 'test',
  title: overrides.id,
  user_visible_behavior: 'behaves',
  status: 'not_started',
  depends_on: [],
  verification: ['L1: pnpm check'],
  evidence: [],
  attempts: 0,
  notes: '',
  ...overrides,
})

const listWith = (features: Feature[]): FeatureList => ({
  project: 'test',
  last_updated: '2026-09-06',
  rules: {
    single_active_feature: true,
    passing_requires_evidence: true,
    do_not_skip_verification: true,
  },
  status_legend: { not_started: 'a', in_progress: 'b', blocked: 'c', passing: 'd' },
  features,
})

describe('feature_list.json (harness state)', () => {
  it('is valid: unique ids, WIP=1, passing has evidence, blocked has notes, deps resolve', () => {
    const list = validateFeatureList(committed())
    expect(list.features.length).toBeGreaterThan(0)
    expect(summarizeFeatureList(list)).toMatch(/VCR/)
    expect(summarizeFeatureList(list)).toMatch(/ready/)
  })

  it('rejects two in_progress features', () => {
    const list = validateFeatureList(committed())
    const [first, second] = list.features
    if (!first || !second) throw new Error('need at least two features')
    const broken = {
      ...list,
      features: list.features.map((f) =>
        f.id === first.id || f.id === second.id
          ? { ...f, status: 'in_progress', depends_on: [], evidence: f.evidence }
          : f,
      ),
    }
    expect(() => validateFeatureList(broken)).toThrow(/WIP=1/)
  })

  it('rejects passing without evidence and unlabelled verification steps', () => {
    const list = validateFeatureList(committed())
    const [first] = list.features
    if (!first) throw new Error('need at least one feature')
    const noEvidence = {
      ...list,
      features: [{ ...first, status: 'passing', evidence: [] }],
    }
    expect(() => validateFeatureList(noEvidence)).toThrow(/no evidence/)
    const unlabelled = {
      ...list,
      features: [{ ...first, verification: ['run the tests'] }],
    }
    expect(() => validateFeatureList(unlabelled)).toThrow(/L1: /)
  })

  it('rejects a "--" before the test file unless the feature already passed', () => {
    const step = 'L1: pnpm test:unit -- tests/unit/a.test.ts (it works)'
    expect(() =>
      validateFeatureList(listWith([feature({ id: 'F-001', verification: [step] })])),
    ).toThrow(/drop the "--"/)
    expect(() =>
      validateFeatureList(
        listWith([
          feature({ id: 'F-001', status: 'passing', verification: [step], evidence: ['ran'] }),
        ]),
      ),
    ).not.toThrow()
  })
})

describe('depends_on rules', () => {
  it('defaults depends_on and attempts when absent', () => {
    const raw = listWith([feature({ id: 'F-001' })]) as unknown as {
      features: Record<string, unknown>[]
    }
    const first = raw.features[0]
    if (!first) throw new Error('unreachable')
    delete first.depends_on
    delete first.attempts
    const list = validateFeatureList(raw)
    expect(list.features[0]?.depends_on).toEqual([])
    expect(list.features[0]?.attempts).toBe(0)
  })

  it('rejects unknown, self and cyclic dependencies', () => {
    expect(() =>
      validateFeatureList(listWith([feature({ id: 'F-001', depends_on: ['F-999'] })])),
    ).toThrow(/unknown feature F-999/)
    expect(() =>
      validateFeatureList(listWith([feature({ id: 'F-001', depends_on: ['F-001'] })])),
    ).toThrow(/depends on itself/)
    expect(() =>
      validateFeatureList(
        listWith([
          feature({ id: 'F-001', depends_on: ['F-002'] }),
          feature({ id: 'F-002', depends_on: ['F-003'] }),
          feature({ id: 'F-003', depends_on: ['F-001'] }),
        ]),
      ),
    ).toThrow(/cycle: F-001 → F-002 → F-003 → F-001/)
  })

  it('rejects in_progress while a dependency is not passing', () => {
    expect(() =>
      validateFeatureList(
        listWith([
          feature({ id: 'F-001' }),
          feature({ id: 'F-002', status: 'in_progress', depends_on: ['F-001'] }),
        ]),
      ),
    ).toThrow(/depends on non-passing F-001/)
  })

  it('computes readiness, human-only and the next feature by priority', () => {
    const list = validateFeatureList(
      listWith([
        feature({ id: 'F-001', status: 'passing', evidence: ['ok'] }),
        feature({ id: 'F-002', depends_on: ['F-001'], priority: 20 }),
        feature({ id: 'F-003', depends_on: ['F-004'], priority: 5 }),
        feature({ id: 'F-004', priority: 30 }),
        feature({
          id: 'F-005',
          priority: 1,
          verification: ['L1: pnpm check', 'manual: look at it'],
        }),
      ]),
    )
    const byId = (id: string) => list.features.find((f) => f.id === id) as Feature
    expect(isReady(byId('F-002'), list)).toBe(true)
    expect(isReady(byId('F-003'), list)).toBe(false)
    expect(isHumanOnly(byId('F-005'))).toBe(true)
    expect(nextReadyFeature(list)?.id).toBe('F-002')
    expect(nextReadyFeature(list, { includeHumanOnly: true })?.id).toBe('F-005')
    expect(nextReadyFeature(list, { exclude: ['F-002'] })?.id).toBe('F-004')
    expect(summarizeFeatureList(list)).toMatch(/3 ready \(2 unattended\)/)
  })

  it('normalises key order so every writer produces the same file', () => {
    const keys = Object.keys(
      normalizeFeature(feature({ id: 'F-001', ticket: 'MV-042', spec: 'x' })),
    )
    expect(keys.slice(0, 8)).toEqual([
      'id',
      'priority',
      'area',
      'title',
      'user_visible_behavior',
      'status',
      'depends_on',
      'ticket',
    ])
    expect(keys).not.toContain('epic')
  })
})
