import { attachCommands } from './commands/attach.js'
import { coreCommands } from './commands/core.js'
import { debugCommands } from './commands/debug.js'
import { opsCommands } from './commands/ops.js'
import { sessionCommands } from './commands/session.js'
import { setupCommands } from './commands/setup.js'
import { wakeCommands } from './commands/wake.js'
import type { SlashCommand } from './types.js'

// Ignitee Now billing was removed, so the /topup and /subscription commands
// (commands/topup.ts, commands/subscription.ts) are no longer registered:
// there is nothing for them to show or change.
export const SLASH_COMMANDS: SlashCommand[] = [
  ...coreCommands,
  ...sessionCommands,
  ...opsCommands,
  ...wakeCommands,
  ...attachCommands,
  ...setupCommands,
  ...debugCommands
]

const byName = new Map<string, SlashCommand>(
  SLASH_COMMANDS.flatMap(cmd => [cmd.name, ...(cmd.aliases ?? [])].map(name => [name, cmd] as const))
)

export const findSlashCommand = (name: string) => byName.get(name.toLowerCase())
