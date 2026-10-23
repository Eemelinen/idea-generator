const config = {
  '*.{ts,js,mjs,cjs,json,md,yml,yaml}': ['prettier --write --ignore-unknown'],
  'feature_list.json': ['tsx scripts/validate-feature-list.ts'],
}

export default config
