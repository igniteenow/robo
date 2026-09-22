/* Smoke test for @igniteenow/ui. Run: `npm test --workspace @igniteenow/ui`
 *
 * No test framework and no DOM needed: components are rendered to static markup
 * with the same props Robo's screens pass, exports are checked against
 * docs/ui-kit/SPEC.md, and the package export map is checked to resolve every
 * import path the apps use. Interaction (focus trap, Escape, clipboard) needs a
 * browser and is covered by the acceptance list in the spec. */
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createElement as h } from "react";
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { useBelowBreakpoint } from "../src/hooks/use-below-breakpoint";
import { useConfirmDelete } from "../src/hooks/use-confirm-delete";
import { useToast } from "../src/hooks/use-toast";
import { cn } from "../src/lib/cn";
import { Badge } from "../src/ui/components/badge";
import { BottomSheet } from "../src/ui/components/bottom-sheet";
import { Button } from "../src/ui/components/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../src/ui/components/card";
import { Checkbox } from "../src/ui/components/checkbox";
import { CommandBlock, CopyButton } from "../src/ui/components/command-block";
import { ConfirmDialog } from "../src/ui/components/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../src/ui/components/dialog";
import { Input } from "../src/ui/components/input";
import { Label } from "../src/ui/components/label";
import { ListItem } from "../src/ui/components/list-item";
import { FilterGroup, Segmented } from "../src/ui/components/segmented";
import { Select, SelectOption } from "../src/ui/components/select";
import { SelectionSwitcher } from "../src/ui/components/selection-switcher";
import { Separator } from "../src/ui/components/separator";
import { Spinner } from "../src/ui/components/spinner";
import { Stats } from "../src/ui/components/stats";
import { Switch } from "../src/ui/components/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../src/ui/components/tabs";
import { Toast } from "../src/ui/components/toast";
import { H2 } from "../src/ui/components/typography/h2";
import { Typography, H2 as H2FromIndex } from "../src/ui/components/typography/index";

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..");
let passed = 0;
const failures: string[] = [];

function check(name: string, fn: () => void): void {
  try {
    fn();
    passed += 1;
  } catch (error) {
    failures.push(`${name}: ${(error as Error).message}`);
  }
}
function expect(condition: unknown, message: string): void {
  if (!condition) throw new Error(message);
}
const html = (el: ReactElement): string => renderToStaticMarkup(el);
const has = (markup: string, ...needles: string[]): void =>
  needles.forEach((n) => expect(markup.includes(n), `expected markup to contain ${JSON.stringify(n)}\n   got: ${markup.slice(0, 240)}`));

// --- cn ------------------------------------------------------------------
check("cn joins strings, arrays, maps and drops falsy", () => {
  expect(cn("a", false, null, undefined, ["b", ["c"]], { d: true, e: false }, 0) === "a b c d 0", cn("a", ["b"], { d: 1 }));
  expect(cn() === "", "empty");
});

// --- simple components, with the props the dashboard really passes ---------
check("Button: sizes, variants, prefix, safe default type", () => {
  const m = html(h(Button, { size: "sm", outlined: true, prefix: h("i", null, "+"), "aria-label": "Add", className: "w-full" }, "Add"));
  has(m, 'type="button"', 'data-size="sm"', 'data-variant="outlined"', "rui-btn w-full", "<i>+</i>Add", 'aria-label="Add"');
  has(html(h(Button, { type: "submit" }, "Go")), 'type="submit"', 'data-size="md"', 'data-variant="solid"');
  has(html(h(Button, { ghost: true, destructive: true, size: "icon", disabled: true })), 'data-variant="ghost"', 'data-destructive="true"', "disabled");
  expect(!html(h(Button, null, "x")).includes("prefix="), "prefix must not leak to the DOM");
});
check("Badge tones", () => {
  for (const tone of ["outline", "secondary", "success", "warning", "destructive"] as const) has(html(h(Badge, { tone, title: "t" }, tone)), `data-tone="${tone}"`, 'title="t"');
  has(html(h(Badge, null, "x")), 'data-tone="default"');
});
check("Card family", () => {
  const m = html(h(Card, { id: "c", className: "p-0" }, h(CardHeader, null, h(CardTitle, null, "T"), h(CardDescription, null, "D")), h(CardContent, { className: "space-y-2" }, "body")));
  has(m, 'id="c"', "rui-card p-0", "<h3", "rui-card__desc", "rui-card__content space-y-2", "body");
});
check("Input + Label", () => {
  has(html(h(Input, { id: "n", value: "5", onChange: () => {}, type: "number", min: 0, max: 9, step: 1, placeholder: "p", "aria-invalid": true, autoComplete: "off", spellCheck: false })), 'type="number"', 'min="0"', 'max="9"', 'aria-invalid="true"', "rui-input");
  has(html(h(Input, { value: "", onChange: () => {} })), 'type="text"');
  has(html(h(Label, { htmlFor: "n", className: "text-xs" }, "Name")), 'for="n"', "rui-label text-xs");
});
check("Checkbox is a native checkbox and reports booleans", () => {
  has(html(h(Checkbox, { checked: true, onCheckedChange: () => {}, id: "k", "aria-label": "Pick" })), 'type="checkbox"', "checked", 'id="k"');
  let got: boolean | null = null;
  const el = (Checkbox as unknown as { render: (p: object, r: null) => ReactElement<{ onChange: (e: unknown) => void }> }).render({ checked: false, onCheckedChange: (v: boolean) => (got = v) }, null);
  el.props.onChange({ target: { checked: true } });
  expect(got === true, "onCheckedChange(true) not called");
});
check("Switch toggles and respects preventDefault", () => {
  has(html(h(Switch, { checked: true, onCheckedChange: () => {}, disabled: true })), 'role="switch"', 'aria-checked="true"', "disabled");
  const render = (Switch as unknown as { render: (p: object, r: null) => ReactElement<{ onClick: (e: unknown) => void }> }).render;
  let got: boolean | null = null;
  render({ checked: false, onCheckedChange: (v: boolean) => (got = v) }, null).props.onClick({ defaultPrevented: false });
  expect(got === true, "did not toggle on");
  got = null;
  render({ checked: true, onCheckedChange: (v: boolean) => (got = v) }, null).props.onClick({ defaultPrevented: true });
  expect(got === null, "toggled despite preventDefault");
});
check("Select + SelectOption + placeholder", () => {
  const m = html(h(Select, { value: "b", onValueChange: () => {}, id: "s", disabled: false, placeholder: "Pick" }, h(SelectOption, { value: "a" }, "A"), h(SelectOption, { value: "b" }, "B")));
  has(m, "<select", 'id="s"', "rui-select", 'value="b" selected', "Pick");
  let got = "";
  const el = (Select as unknown as { render: (p: object, r: null) => ReactElement<{ onChange: (e: unknown) => void }> }).render({ value: "a", onValueChange: (v: string) => (got = v) }, null);
  el.props.onChange({ target: { value: "z" } });
  expect(got === "z", "onValueChange not called with value");
});
check("ListItem", () => has(html(h(ListItem, { active: true, role: "option", "aria-selected": true, className: "px-3" }, "x")), 'data-active="true"', 'role="option"', 'type="button"', "rui-item px-3"));
check("Separator, Spinner, Stats, H2, Typography", () => {
  has(html(h(Separator, null)), 'data-orientation="horizontal"', 'role="none"');
  has(html(h(Separator, { orientation: "vertical", decorative: false })), 'role="separator"', 'aria-orientation="vertical"');
  has(html(h(Spinner, { className: "text-2xl text-primary" })), 'role="status"', "rui-spinner text-2xl");
  has(html(h(Spinner, { label: "" })), 'aria-hidden="true"');
  has(html(h(Stats, { items: [{ label: "Tokens", value: "1.2M" }, { label: "Cost", value: "$3" }], className: "mb-4" })), "<dl", "rui-stats mb-4", "Tokens", "1.2M", "Cost");
  has(html(h(H2, { variant: "sm", id: "h", className: "mb-2" }, "Title")), "<h2", 'data-variant="sm"', 'id="h"');
  expect(H2 === H2FromIndex, "typography/index must re-export H2");
  has(html(h(Typography, { className: "font-bold uppercase" }, "Robo", h("br"), "Agent")), "rui-type font-bold", "<br/>");
});
check("Segmented is a radio group with one tab stop; FilterGroup labels it", () => {
  const m = html(h(FilterGroup, { label: "File", className: "gap-2" }, h(Segmented, { value: "b", onChange: () => {}, size: "md", options: [{ value: "a", label: "A" }, { value: "b", label: "B" }, { value: "c", label: "C", disabled: true }] })));
  has(m, 'role="group"', "File", 'role="radiogroup"', 'data-size="md"', 'aria-checked="true"');
  expect((m.match(/tabindex="0"/g) ?? []).length === 1, "exactly one option should be tabbable");
  expect((m.match(/role="radio"/g) ?? []).length === 3, "three radios");
});
check("Tabs", () => {
  const m = html(h(Tabs, { defaultValue: "two" }, h(TabsList, null, h(TabsTrigger, { value: "one" }, "One"), h(TabsTrigger, { value: "two" }, "Two")), h(TabsContent, { value: "one" }, "P1"), h(TabsContent, { value: "two" }, "P2")));
  has(m, 'role="tablist"', 'aria-selected="true"', 'role="tabpanel"', "P2");
  expect(!m.includes("P1"), "inactive panel must not render");
});

// --- overlays: closed renders nothing, open renders an accessible dialog ------
check("Dialog closed / open", () => {
  const tree = (open: boolean) => h(Dialog, { open, onOpenChange: () => {} }, h(DialogContent, { className: "max-w-lg" }, h(DialogHeader, null, h(DialogTitle, null, "Title"), h(DialogDescription, null, "Desc")), h(DialogFooter, null, h(Button, null, "OK"))));
  expect(html(tree(false)) === "", "closed dialog must render nothing");
  const m = html(tree(true));
  has(m, 'role="dialog"', 'aria-modal="true"', "rui-dialog max-w-lg", "Title", "Desc");
  const id = /aria-labelledby="([^"]+)"/.exec(m)?.[1];
  expect(id && m.includes(`id="${id}"`), "aria-labelledby must point at the title");
});
check("DialogTitle outside Dialog fails loudly", () => {
  let threw = false;
  try { html(h(DialogTitle, null, "x")); } catch { threw = true; }
  expect(threw, "expected a clear error");
});
check("ConfirmDialog", () => {
  expect(html(h(ConfirmDialog, { open: false, onConfirm: () => {}, onCancel: () => {} })) === "", "closed");
  const m = html(h(ConfirmDialog, { open: true, onConfirm: () => {}, onCancel: () => {}, title: "Remove server?", description: "This cannot be undone.", confirmLabel: "Remove", cancelLabel: "Keep", loading: true }));
  has(m, 'role="alertdialog"', "Remove server?", "This cannot be undone.", "Remove", "Keep", 'data-destructive="true"', "rui-spinner");
  expect((m.match(/disabled=""/g) ?? []).length === 2, "both buttons disabled while loading");
});
check("BottomSheet", () => {
  expect(html(h(BottomSheet, { open: false, onClose: () => {} })) === "", "closed");
  has(html(h(BottomSheet, { open: true, onClose: () => {}, title: "Theme", backdropDismissLabel: "Close" }, "opts")), 'data-sheet="true"', 'aria-label="Close"', "Theme", "opts", 'role="dialog"');
});
check("Toast", () => {
  expect(html(h(Toast, { toast: null })) === "", "null toast renders nothing");
  has(html(h(Toast, { toast: { message: "Saved", type: "success", id: 1 } })), 'role="status"', 'data-type="success"', "Saved");
  has(html(h(Toast, { toast: { message: "Failed", type: "error", id: 2 } })), 'role="alert"');
  // Screens that keep their own { message, type } state (no id) must work too.
  has(html(h(Toast, { toast: { message: "Own state", type: "success" } })), "Own state", 'data-type="success"');
});
check("CommandBlock + CopyButton", () => {
  has(html(h(CommandBlock, { label: "Install", code: "robo setup --yes" })), "Install", "<code>robo setup --yes</code>", "Copy");
  has(html(h(CopyButton, { text: "x", label: "Copy id", copiedLabel: "Done" })), "Copy id", 'data-size="xs"');
});
check("SelectionSwitcher renders nothing", () => expect(html(h(SelectionSwitcher)) === "", "should be empty"));

// --- hooks: initial state (effects need a browser) --------------------------------
check("hooks: initial shapes match how the dashboard destructures them", () => {
  let seen: Record<string, unknown> = {};
  function Probe(): null {
    const { toast, showToast } = useToast();
    const del = useConfirmDelete<string>({ onDelete: async () => {}, onSuccess: () => {}, onError: () => {} });
    seen = { toast, showToast, below: useBelowBreakpoint(1024), ...del };
    return null;
  }
  html(h(Probe));
  expect(seen.toast === null && typeof seen.showToast === "function", "useToast shape");
  expect(seen.below === false, "useBelowBreakpoint is false without a window");
  expect(seen.isOpen === false && seen.pendingId === null && seen.isDeleting === false, "useConfirmDelete initial state");
  for (const k of ["requestDelete", "cancel", "confirm"]) expect(typeof seen[k] === "function", `useConfirmDelete.${k}`);
});

// --- contract: every module + export in the spec exists and resolves ---------------
check("every spec module resolves through package.json exports, with every named export", () => {
  const spec = readFileSync(resolve(pkgRoot, "../../docs/ui-kit/SPEC.md"), "utf8");
  const pkg = JSON.parse(readFileSync(join(pkgRoot, "package.json"), "utf8")) as { exports: Record<string, string> };
  const resolveExport = (sub: string): string | null => {
    for (const [pattern, target] of Object.entries(pkg.exports)) {
      const [pre, post = ""] = pattern.split("*");
      if (sub.startsWith(pre) && sub.endsWith(post) && sub.length >= pre.length + post.length) {
        return join(pkgRoot, target.replace("*", sub.slice(pre.length, sub.length - post.length)));
      }
    }
    return null;
  };
  const sections = spec.split(/^### `@igniteenow\/ui\//m).slice(1);
  expect(sections.length >= 25, `expected 25 modules in spec, found ${sections.length}`);
  let exportsChecked = 0;
  for (const section of sections) {
    const sub = "./" + section.slice(0, section.indexOf("`"));
    const file = resolveExport(sub);
    expect(file && existsSync(file), `${sub} does not resolve to a file (${file})`);
    const source = readFileSync(file as string, "utf8");
    for (const match of section.matchAll(/^- \*\*`(\w+)`\*\*/gm)) {
      const name = match[1];
      expect(new RegExp(`export (?:const|function|type|interface) ${name}\\b|export \\{[^}]*\\b${name}\\b`).test(source), `${sub} is missing export ${name}`);
      exportsChecked += 1;
    }
  }
  expect(exportsChecked >= 39, `expected 39 exports, checked ${exportsChecked}`);
  for (const css of ["./styles/globals.css", "./styles/fonts.css"]) expect(existsSync(resolveExport(css) as string), `${css} missing`);
});
check("globals.css supplies every Tailwind token the dashboard uses from the kit", () => {
  const css = readFileSync(join(pkgRoot, "src/styles/globals.css"), "utf8");
  for (const token of ["--color-background:", "--color-background-base:", "--color-midground:", "--color-text-secondary:", "--color-text-tertiary:", "--color-text-disabled:", "--font-display:", "--font-courier:", "@utility text-display"]) expect(css.includes(token), `missing ${token}`);
  expect(css.includes("@layer components"), "component rules must sit in the components layer so utilities win");
  const open = (css.match(/\{/g) ?? []).length, close = (css.match(/\}/g) ?? []).length;
  expect(open === close, `unbalanced braces in globals.css (${open} vs ${close})`);
});

console.log(`${passed} passed, ${failures.length} failed`);
if (failures.length) {
  for (const f of failures) console.error("FAIL " + f);
  process.exit(1);
}
