import { cn } from '@/lib/utils'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// Robo brand badge: a still rendered from the same animated face used by the
// live desktop robot. Size is controlled by className (default size-14).
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'inline-flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-md bg-[#11182a]',
        className
      )}
      {...props}
    >
      <img alt="" className="size-full object-contain" src={assetPath('robo-face-icon.png')} />
    </span>
  )
}
