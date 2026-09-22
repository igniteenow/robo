# `@igniteenow/ui` — first-party build specification

This is the complete interface Robo's dashboard, desktop app and installer use from the
shared UI package, extracted mechanically from **Robo's own call sites**. It is the contract a
from-scratch Ignitee Now implementation is written against.

`packages/ui` implements this contract. `packages/ui/test/smoke.test.tsx` checks that every
module and export listed here exists and resolves through the package export map, so this
document and the code cannot drift apart.

Surface: **39 exports** in **25 modules**, plus 2 stylesheets.

## Stylesheets

| Import | Must provide |
|---|---|
| `@igniteenow/ui/styles/globals.css` | Tailwind v4 theme tokens the apps reference: `--background`, `--foreground`, `--midground` (+ `-base` / `-alpha`), `--card`, `--popover`, `--border`, `--input`, `--primary`, `--secondary`, `--accent`, `--muted-foreground`, `--ring`, `--destructive`, `--success`, `--warning`, `--radius`; base element resets. Values come from `assets/brand/BRAND.md`. |
| `@igniteenow/ui/styles/fonts.css` | `@font-face` for the brand face. Poppins is already declared by each app, so this may be empty. |

## Components and hooks

Props are listed with the number of call sites that pass them, most used first.

### `@igniteenow/ui/hooks/use-below-breakpoint`

- **`useBelowBreakpoint`** (hook, imported by 3 files)
  - call shape ×2: `narrowViewport  <=  useBelowBreakpoint(640)`
  - call shape ×1: `isMobile  <=  useBelowBreakpoint(1024)`

### `@igniteenow/ui/hooks/use-confirm-delete`

- **`useConfirmDelete`** (hook, imported by 8 files)
  - call shape ×1: `keyClear  <=  useConfirmDelete({ onDelete: useCallback( async (key: string)`
  - call shape ×1: `serverDelete  <=  useConfirmDelete({ onDelete: useCallback( async (serverName: string)`
  - call shape ×1: `memoryReset  <=  useConfirmDelete({ onDelete: useCallback( async (target: string)`
  - call shape ×1: `credDelete  <=  useConfirmDelete({ onDelete: useCallback( async (key: string)`
  - call shape ×1: `checkpointsPrune  <=  useConfirmDelete({ onDelete: useCallback(async ()`
  - call shape ×1: `hookDelete  <=  useConfirmDelete({ onDelete: useCallback( async (key: string)`

### `@igniteenow/ui/hooks/use-toast`

- **`useToast`** (hook, imported by 16 files)
  - call shape ×16: `{ toast, showToast }  <=  useToast()`

### `@igniteenow/ui/ui/components/badge`

- **`Badge`** (component, imported by 23 files)
  - props used: `tone` ×112, `className` ×45, `key` ×7, `title` ×5

### `@igniteenow/ui/ui/components/bottom-sheet`

- **`BottomSheet`** (component, imported by 2 files)
  - props used: `backdropDismissLabel` ×2, `onClose` ×2, `open` ×1, `title` ×1

### `@igniteenow/ui/ui/components/button`

- **`Button`** (component, imported by 33 files)
  - props used: `size` ×209, `onClick` ×208, `className` ×121, `disabled` ×62, `prefix` ×56, `aria-label` ×46, `title` ×24, `type` ×18, `outlined` ×8, `key` ×3, `ghost` ×1, `destructive` ×1, `aria-pressed` ×1, `installingName` ×1, `style` ×1, `copiedLabel` ×1, `aria-haspopup` ×1, `aria-expanded` ×1

### `@igniteenow/ui/ui/components/card`

- **`Card`** (component, imported by 22 files)
  - props used: `className` ×28, `key` ×10, `id` ×3
- **`CardContent`** (component, imported by 21 files)
  - props used: `className` ×66
- **`CardDescription`** (component, imported by 2 files)
  - props used: `className` ×2
- **`CardHeader`** (component, imported by 11 files)
  - props used: `className` ×12
- **`CardTitle`** (component, imported by 11 files)
  - props used: `className` ×18

### `@igniteenow/ui/ui/components/checkbox`

- **`Checkbox`** (component, imported by 6 files)
  - props used: `checked` ×9, `onCheckedChange` ×7, `id` ×5, `disabled` ×3, `onClick` ×2, `aria-label` ×1

### `@igniteenow/ui/ui/components/command-block`

- **`CommandBlock`** (component, imported by 1 file)
  - props used: `label` ×1, `code` ×1
- **`CopyButton`** (component, imported by 2 files)
  - props used: `text` ×2, `label` ×1, `copiedLabel` ×1

### `@igniteenow/ui/ui/components/confirm-dialog`

- **`ConfirmDialog`** (component, imported by 6 files)
  - props used: `onCancel` ×8, `open` ×6, `cancelLabel` ×4, `confirmLabel` ×4, `description` ×4, `loading` ×3, `title` ×2, `onConfirm` ×1

### `@igniteenow/ui/ui/components/dialog`

- **`Dialog`** (component, imported by 4 files)
  - props used: `onOpenChange` ×5, `open` ×4
- **`DialogContent`** (component, imported by 4 files)
  - props used: `className` ×5
- **`DialogDescription`** (component, imported by 4 files)
  - props used: `className` ×1
- **`DialogFooter`** (component, imported by 2 files)
- **`DialogHeader`** (component, imported by 4 files)
- **`DialogTitle`** (component, imported by 4 files)
  - props used: `className` ×1

### `@igniteenow/ui/ui/components/input`

- **`Input`** (component, imported by 21 files)
  - props used: `value` ×63, `onChange` ×63, `placeholder` ×40, `id` ×39, `type` ×15, `className` ×6, `min` ×4, `max` ×3, `autoComplete` ×2, `step` ×1, `spellCheck` ×1, `autoFocus` ×1, `aria-invalid` ×1

### `@igniteenow/ui/ui/components/label`

- **`Label`** (component, imported by 17 files)
  - props used: `htmlFor` ×74, `className` ×21

### `@igniteenow/ui/ui/components/list-item`

- **`ListItem`** (component, imported by 8 files)
  - props used: `onClick` ×11, `active` ×9, `key` ×8, `aria-selected` ×4, `className` ×4, `role` ×1, `onMouseEnter` ×1

### `@igniteenow/ui/ui/components/segmented`

- **`FilterGroup`** (component, imported by 1 file)
  - props used: `label` ×4, `className` ×4
- **`Segmented`** (component, imported by 3 files)
  - props used: `value` ×7, `onChange` ×7, `className` ×6, `options` ×5, `size` ×2

### `@igniteenow/ui/ui/components/select`

- **`Select`** (component, imported by 12 files)
  - props used: `value` ×20, `onValueChange` ×20, `id` ×16, `className` ×5, `disabled` ×3, `role` ×1, `placeholder` ×1
- **`SelectOption`** (component, imported by 12 files)
  - props used: `value` ×43, `key` ×15

### `@igniteenow/ui/ui/components/selection-switcher`

- **`SelectionSwitcher`** (component, imported by 1 file)

### `@igniteenow/ui/ui/components/separator`

- **`Separator`** (component, imported by 1 file)

### `@igniteenow/ui/ui/components/spinner`

- **`Spinner`** (component, imported by 25 files)
  - props used: `className` ×36

### `@igniteenow/ui/ui/components/stats`

- **`Stats`** (component, imported by 2 files)
  - props used: `items` ×2, `className` ×1

### `@igniteenow/ui/ui/components/switch`

- **`Switch`** (component, imported by 7 files)
  - props used: `checked` ×9, `onCheckedChange` ×9, `id` ×1, `disabled` ×1

### `@igniteenow/ui/ui/components/tabs`

- **`Tabs`** (component, imported by 1 file)
- **`TabsList`** (component, imported by 1 file)
- **`TabsTrigger`** (component, imported by 1 file)

### `@igniteenow/ui/ui/components/toast`

- **`Toast`** (component, imported by 17 files)
  - props used: `toast` ×17

### `@igniteenow/ui/ui/components/typography/h2`

- **`H2`** (component, imported by 8 files)
  - props used: `variant` ×16, `className` ×16, `id` ×1

### `@igniteenow/ui/ui/components/typography/index`

- **`Typography`** (component, imported by 5 files)
  - props used: `className` ×13

## Acceptance

A replacement is done when, with `packages/ui` in place of the npm alias:

1. `npm run check` passes with no type errors in `web`, `apps/desktop`, `apps/bootstrap-installer`.
2. `npm run build --workspace web` and the desktop build succeed.
3. Every page renders in both the default and light themes with keyboard focus visible on every control.
4. Dialogs, bottom sheets and selects trap focus, close on Escape, and restore focus on close.
