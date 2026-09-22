# @igniteenow/ui

Robo's shared UI components. Written by Ignitee Now, from the interface
specification in [`docs/ui-kit/SPEC.md`](../../docs/ui-kit/SPEC.md).

- **No runtime dependencies** beyond React. No class-merging library, no
  headless-UI library, no icon set.
- **Self-styled.** Component rules live in `src/styles/globals.css` inside the
  `components` cascade layer, so any Tailwind utility passed via `className`
  overrides them, and nothing depends on Tailwind scanning this package.
- **Themed by the host.** Reads `--background-base`, `--midground` and the
  optional `--color-*` overrides the dashboard's ThemeProvider sets. Every read
  has an Ignitee Now brand fallback (`assets/brand/BRAND.md`).
- **Accessible by construction.** Checkbox and Select are native elements;
  Switch, Segmented and Tabs carry the right roles and keyboard behaviour;
  dialogs and the bottom sheet trap focus, close on Escape, restore focus to
  the opener and lock page scroll; one visible focus ring everywhere; motion
  respects `prefers-reduced-motion`.

## Use

```css
@import 'tailwindcss';
@import '@igniteenow/ui/styles/fonts.css';
@import '@igniteenow/ui/styles/globals.css';
```

```tsx
import { Button } from "@igniteenow/ui/ui/components/button";
import { useToast } from "@igniteenow/ui/hooks/use-toast";
```

## Test

```
npm test --workspace @igniteenow/ui
```

Renders every component with the props Robo's screens pass, checks each export
named in the spec exists, and checks the export map resolves each import path.
Interaction that needs a real browser (focus trap, Escape, clipboard) is covered
by the acceptance list at the end of the spec.

## Deliberate choices

- `Button` defaults to `type="button"`, so it never submits a form by accident.
- `ConfirmDialog` stays open when the action fails, so the person can retry.
- `SelectionSwitcher` records keyboard-vs-pointer input on `<html data-input>`
  for styling hooks and renders nothing.
- Extras beyond the spec, free to use: `CardFooter`, `TabsContent`,
  `Button suffix`, `dismissToast`, `Separator orientation`.
