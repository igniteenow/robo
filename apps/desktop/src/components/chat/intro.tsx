import { useI18n } from '@/i18n'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

/**
 * A fresh chat opens like a blank page with a question on it: the Robo mark,
 * one heading, and the composer right below — the composer's placeholder
 * carries the rest.
 */
export function Intro() {
  const { t } = useI18n()

  return (
    <div
      className="pointer-events-none flex w-full min-w-0 flex-col items-center justify-center gap-5 px-0.5 py-8 text-center sm:px-6 lg:px-8"
      data-slot="aui_intro"
    >
      <img
        alt="Robo"
        className="mx-auto size-14 drop-shadow-[0_8px_24px_rgba(0,0,0,0.25)]"
        data-testid="intro-logo"
        draggable={false}
        src={assetPath('robo-face-icon.png')}
      />
      <h1 className="text-[1.875rem] leading-tight font-medium tracking-tight text-(--ui-text-primary)">
        {t.composer.freshChatHeading}
      </h1>
    </div>
  )
}
