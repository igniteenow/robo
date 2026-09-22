import { cn } from '../lib/utils'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// Brand badge on a white tile, identical in light/dark. Same asset the
// desktop app's own BrandMark uses — a still rendered from the animated
// face at public/robo-face/cute-face.html.
// Ported from apps/desktop's BrandMark; asset lives in this app's public/.
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span className={cn('inline-flex size-14 shrink-0 items-center justify-center bg-white', className)} {...props}>
      <img alt="" className="size-full object-contain" src={assetPath('robo-face-icon.png')} />
    </span>
  )
}
