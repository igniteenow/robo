const clean = (value: string | undefined, fallback: string) => value?.trim() || fallback

/** User-visible Robo product branding. */
export const PRODUCT_NAME = clean(process.env.ROBO_PRODUCT_NAME, 'Robo')
export const PRODUCT_SHORT_NAME = PRODUCT_NAME
export const CLI_NAME = clean(process.env.ROBO_CLI_NAME, 'robo')
export const PRODUCT_HOME = clean(process.env.ROBO_HOME, `~/.${CLI_NAME}`)
export const PRODUCT_ENV_FILE = `${PRODUCT_HOME.replace(/[\\/]$/, '')}/.env`
export const WAKE_PHRASE = clean(
  process.env.ROBO_WAKE_PHRASE_DISPLAY,
  'Hey Roh Boh'
)
