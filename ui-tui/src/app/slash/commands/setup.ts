import { withInkSuspended } from '@robo/ink'

import { CLI_NAME } from '../../../brand.js'
import { launchRoboCommand } from '../../../lib/externalCli.js'
import { runExternalSetup } from '../../setupHandoff.js'
import type { SlashCommand } from '../types.js'

export const setupCommands: SlashCommand[] = [
  {
    help: `run full setup wizard (launches \`${CLI_NAME} setup\`)`,
    name: 'setup',
    run: (arg, ctx) =>
      void runExternalSetup({
        args: ['setup', ...arg.split(/\s+/).filter(Boolean)],
        ctx,
        done: 'setup complete — starting session…',
        launcher: launchRoboCommand,
        suspend: withInkSuspended
      })
  }
]
