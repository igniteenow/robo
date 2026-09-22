import { pick } from '../lib/text.js'

export const PLACEHOLDERS = [
  'Describe the task — Robo plans, verifies, then acts…',
  'e.g. "map this codebase and find the auth flow"',
  'e.g. "reverse-engineer ./sample.bin and explain main"',
  'e.g. "write tests for the payment module, then run them"',
  'e.g. "audit this repo for secrets and risky configs"',
  '/model to switch models · /help for every command',
  'e.g. "why does the config loader ignore ROBO_HOME?"'
]

export const PLACEHOLDER = pick(PLACEHOLDERS)
