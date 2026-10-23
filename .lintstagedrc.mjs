const config = {
  '*.{ts,js,mjs,cjs,json,md,yml,yaml}': ['prettier --write --ignore-unknown'],
  'feature_list.json': ['harness check'],
}

export default config
