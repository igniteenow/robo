export const TOOL_VERBS: Record<string, string> = {
  browser: 'browsing',
  clarify: 'asking',
  create_file: 'creating',
  delegate_task: 'delegating',
  delete_file: 'deleting',
  execute_code: 'executing',
  image_generate: 'generating',
  list_files: 'listing',
  memory: 'remembering',
  patch: 'patching',
  read_file: 'reading',
  run_command: 'running',
  search_code: 'searching',
  search_files: 'searching',
  terminal: 'terminal',
  web_extract: 'extracting',
  web_search: 'searching',
  write_file: 'writing'
}

export const VERBS = [
  'analyzing',
  'planning',
  'reasoning',
  'verifying',
  'building',
  'testing',
  'inspecting',
  'coordinating'
]

// Historical transcripts may contain status fragments produced by older
// builds. Keep them recognizable for cleanup without showing them in Robo's
// current command deck.
export const THINKING_STATUS_VERBS = [
  ...VERBS,
  'pondering',
  'contemplating',
  'musing',
  'cogitating',
  'ruminating',
  'deliberating',
  'mulling',
  'reflecting',
  'processing',
  'computing',
  'synthesizing',
  'formulating',
  'brainstorming'
]
