const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

/**
 * A fresh chat opens on the Robo mark alone — the logo on the README, above
 * the composer, no tagline. The composer's placeholder is the prompt.
 */
export function Intro() {
  return (
    <div
      className="pointer-events-none flex w-full min-w-0 flex-col items-center justify-center px-0.5 py-6 text-center sm:px-6 lg:px-8"
      data-slot="aui_intro"
    >
      <img
        alt="Robo"
        className="mx-auto size-26 drop-shadow-[0_12px_32px_rgba(10,16,48,0.4)]"
        data-testid="intro-logo"
        draggable={false}
        src={assetPath('robo-face-icon.png')}
      />
    </div>
  )
}
