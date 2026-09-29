import { Button } from "@igniteenow/ui/ui/components/button";
import { Checkbox } from "@igniteenow/ui/ui/components/checkbox";
import { ListItem } from "@igniteenow/ui/ui/components/list-item";
import { Spinner } from "@igniteenow/ui/ui/components/spinner";
import { Input } from "@igniteenow/ui/ui/components/input";
import { Label } from "@igniteenow/ui/ui/components/label";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { GatewayClient } from "@/lib/gatewayClient";
import { api } from "@/lib/api";
import { Check, Plus, RefreshCw, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn, themedBody } from "@/lib/utils";
import { fuzzyRank } from "@/lib/fuzzy";
import { queryMatchesProviderOnly } from "@/lib/model-picker-filter";
import { modelSearchText } from "@/lib/model-search-text";

/**
 * Two-stage model picker modal.
 *
 * Mirrors ui-tui/src/components/modelPicker.tsx:
 *   Stage 1: pick provider (authenticated providers only)
 *   Stage 2: pick model within that provider
 *
 * Two invocation modes:
 *
 * 1. Chat-session mode (ChatSidebar) — pass `gw` + `sessionId`. The picker
 *    loads options via `model.options` JSON-RPC and applies the choice via
 *    `config.set`, so expensive-model confirmation can happen before switch.
 *
 * 2. Standalone mode (ModelsPage, Config settings) — pass a `loader` and
 *    `onApply`. The picker fetches options via the REST endpoint and calls
 *    `onApply(provider, model, persistGlobal)` instead of emitting a slash
 *    command.  This lets the Models page reuse the same UI without
 *    requiring an open chat PTY.
 */

interface ModelOptionProvider {
  name: string;
  slug: string;
  models?: string[];
  total_models?: number;
  is_current?: boolean;
  warning?: string;
  /** false = listed but not set up yet (see auth_type / key_env). */
  authenticated?: boolean;
  auth_type?: string;
  key_env?: string;
}

/** Pseudo-provider row that opens the custom-endpoint form. */
const CUSTOM_ENDPOINT_SLUG = "__custom_endpoint__";

interface ModelOptionsResponse {
  model?: string;
  provider?: string;
  providers?: ModelOptionProvider[];
}

interface ExpensiveModelConfirmResponse {
  confirm_message?: string;
  confirm_required?: boolean;
  warning?: string;
}

interface ConfigSetResponse extends ExpensiveModelConfirmResponse {
  value?: string;
}

interface PendingExpensiveConfirm {
  message: string;
  model: string;
  persistGlobal: boolean;
  provider: string;
}

interface Props {
  /** Chat-mode: when present, picker emits a slash command via onSubmit. */
  gw?: GatewayClient;
  sessionId?: string;
  onSubmit?(slashCommand: string): void;

  /** Standalone-mode: when present (and onSubmit absent), picker calls onApply. */
  loader?(options?: { refresh?: boolean }): Promise<ModelOptionsResponse>;
  onApply?(args: {
    confirmExpensiveModel?: boolean;
    provider: string;
    model: string;
    persistGlobal: boolean;
  }):
    | Promise<ExpensiveModelConfirmResponse | void>
    | ExpensiveModelConfirmResponse
    | void;

  onClose(): void;
  title?: string;
  /** If true, hides "Persist globally" checkbox — always saves to config.yaml. */
  alwaysGlobal?: boolean;
  /**
   * Standalone only: offer "Custom endpoint" (any OpenAI-compatible URL —
   * LM Studio, Ollama, vLLM, a hosted API). Saving it makes it the main
   * model, then this is called instead of onApply.
   */
  onCustomEndpointSaved?(args: { provider: string; model: string }): void;
}

export function ModelPickerDialog(props: Props) {
  const {
    gw,
    sessionId,
    onSubmit,
    loader,
    onApply,
    onClose,
    title = "Switch Model",
    alwaysGlobal = false,
    onCustomEndpointSaved,
  } = props;
  const standalone = !!loader && !!onApply;
  const allowCustomEndpoint = standalone && !!onCustomEndpointSaved;

  const [providers, setProviders] = useState<ModelOptionProvider[]>([]);
  const [currentModel, setCurrentModel] = useState("");
  const [currentProviderSlug, setCurrentProviderSlug] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSlug, setSelectedSlug] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [query, setQuery] = useState("");
  const [persistGlobal, setPersistGlobal] = useState(alwaysGlobal);
  const [applying, setApplying] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [pendingConfirm, setPendingConfirm] =
    useState<PendingExpensiveConfirm | null>(null);
  const closedRef = useRef(false);

  const applyOptions = (r: ModelOptionsResponse) => {
    const next = r?.providers ?? [];
    setProviders(next);
    setCurrentModel(String(r?.model ?? ""));
    setCurrentProviderSlug(String(r?.provider ?? ""));
    setSelectedSlug((prev) => {
      if (prev && next.some((p) => p.slug === prev)) return prev;
      return (next.find((p) => p.is_current) ?? next[0])?.slug ?? "";
    });
    setSelectedModel("");
  };

  const requestOptions = (refresh = false) =>
    standalone
      ? (loader as (options?: { refresh?: boolean }) => Promise<ModelOptionsResponse>)({
          refresh,
        })
      : (gw as GatewayClient).request<ModelOptionsResponse>(
          "model.options",
          {
            ...(sessionId ? { session_id: sessionId } : {}),
            ...(refresh ? { refresh: true } : {}),
            // Dashboard picker mirrors the TUI: full provider universe with
            // setup warnings. The backend now defaults to the configured
            // subset (#56974), so opt into unconfigured rows explicitly.
            include_unconfigured: true,
          },
        );

  // ``bust`` re-fetches every provider's live catalogue ("Refresh Models");
  // after saving one provider's key a plain reload is enough (its list isn't
  // cached yet) and much faster.
  const refreshOptions = (bust = true) => {
    setError(null);
    setRefreshing(true);

    requestOptions(bust)
      .then((r) => {
        if (closedRef.current) return;
        applyOptions(r);
      })
      .catch((e) => {
        if (closedRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (closedRef.current) return;
        setRefreshing(false);
      });
  };

  // Load providers + models on open.
  useEffect(() => {
    closedRef.current = false;

    requestOptions()
      .then((r) => {
        if (closedRef.current) return;
        applyOptions(r);
      })
      .catch((e) => {
        if (closedRef.current) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (closedRef.current) return;
        setLoading(false);
      });

    return () => {
      closedRef.current = true;
    };
    // Deliberately omit props from deps — stable for the dialog's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Esc closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const selectedProvider = useMemo(
    () => providers.find((p) => p.slug === selectedSlug) ?? null,
    [providers, selectedSlug],
  );

  const models = useMemo(
    () => selectedProvider?.models ?? [],
    [selectedProvider],
  );

  const trimmedQuery = query.trim();

  // Fuzzy-ranked providers: match on name + slug + the provider's model ids so
  // typing a model name surfaces its provider (preserves the prior behaviour
  // where a model match also revealed its provider).
  //
  // With no query, float providers that actually have models to the top
  // (stable within each group). A fresh install lists ~40 providers and only
  // a couple are configured — burying "OpenRouter · 37 models" under a wall
  // of "0 models" rows made the picker feel broken.
  const filteredProviders = useMemo(() => {
    const ranked = fuzzyRank(
      providers,
      trimmedQuery,
      (p) => `${p.name} ${p.slug} ${(p.models ?? []).join(" ")}`,
    ).map((r) => r.item);
    if (trimmedQuery) return ranked;
    const withModels = ranked.filter((p) => (p.models ?? []).length > 0);
    const withoutModels = ranked.filter((p) => (p.models ?? []).length === 0);
    return [...withModels, ...withoutModels];
  }, [providers, trimmedQuery]);

  // A query that matched the SELECTED provider by name/slug (not its models)
  // located that provider — it shouldn't also hide that provider's models
  // just because their ids don't share a substring with the provider name
  // (e.g. typing "aws" to find "AWS Build" then finding zero of its Claude
  // model ids contain "aws"). Fall back to an unfiltered model list in that
  // case; a query that also matches a model id keeps filtering normally.
  const queryMatchesSelectedProviderOnly = useMemo(
    () => queryMatchesProviderOnly(selectedProvider, models, trimmedQuery),
    [trimmedQuery, selectedProvider, models],
  );

  // Fuzzy-ranked models carrying the matched character positions so the model
  // list can highlight why each entry matched. modelSearchText adds aliases
  // for brand-less wire ids (e.g. Kimi Coding `k3` ↔ search "kimi").
  const filteredModels = useMemo(
    () =>
      fuzzyRank(
        models,
        queryMatchesSelectedProviderOnly ? "" : trimmedQuery,
        modelSearchText,
      ).map((r) => ({
        model: r.item,
        // Positions may land in alias suffixes — keep only in-id highlights.
        positions: r.positions.filter((i) => i >= 0 && i < r.item.length),
      })),
    [models, trimmedQuery, queryMatchesSelectedProviderOnly],
  );

  const canConfirm = !!selectedProvider && !!selectedModel && !applying;

  const applySelection = async (
    confirmExpensiveModel = false,
    forced?: PendingExpensiveConfirm,
  ) => {
    const providerSlug = forced?.provider ?? selectedProvider?.slug ?? "";
    const model = forced?.model ?? selectedModel;
    const shouldPersistGlobal = forced?.persistGlobal ?? persistGlobal;

    if (!providerSlug || !model || applying) return;

    if (standalone && onApply) {
      setApplying(true);
      try {
        const result = await onApply({
          confirmExpensiveModel,
          provider: providerSlug,
          model,
          persistGlobal: shouldPersistGlobal,
        });
        if (result?.confirm_required) {
          setPendingConfirm({
            provider: providerSlug,
            model,
            persistGlobal: shouldPersistGlobal,
            message:
              result.confirm_message ||
              result.warning ||
              "This model has unusually high known pricing.",
          });
          return;
        }
        onClose();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setApplying(false);
      }
    } else if (gw && sessionId) {
      setApplying(true);
      try {
        const global = shouldPersistGlobal ? " --global" : "";
        const result = await gw.request<ConfigSetResponse>("config.set", {
          confirm_expensive_model: confirmExpensiveModel,
          key: "model",
          session_id: sessionId,
          value: `${model} --provider ${providerSlug}${global}`,
        });
        if (result?.confirm_required) {
          setPendingConfirm({
            provider: providerSlug,
            model,
            persistGlobal: shouldPersistGlobal,
            message:
              result.confirm_message ||
              result.warning ||
              "This model has unusually high known pricing.",
          });
          return;
        }
        onClose();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setApplying(false);
      }
    } else if (onSubmit) {
      const global = shouldPersistGlobal ? " --global" : "";
      onSubmit(`/model ${model} --provider ${providerSlug}${global}`);
      onClose();
    }
  };

  const confirm = () => {
    if (!canConfirm) return;
    void applySelection();
  };

  // Portal to document.body: the main dashboard column in App.tsx is
  // `relative z-2`, which creates a stacking context that traps fixed
  // descendants below the app sidebar (z-50). Without the portal this
  // modal's z-[100] is scoped to z-2 and the sidebar covers its left
  // edge — visible especially in the Large theme variants where the
  // larger root font widens the dialog into the sidebar's column. See
  // Toast.tsx for the same pattern.
  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="model-picker-title"
    >
      <div className={cn(themedBody, "relative w-full max-w-3xl max-h-[80vh] border border-border bg-card shadow-2xl flex flex-col")}>
        <Button
          ghost
          size="icon"
          onClick={onClose}
          className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
          aria-label="Close"
        >
          <X />
        </Button>

        <header className="p-5 pb-3 border-b border-border">
          <h2
            id="model-picker-title"
            className="font-display text-display text-base tracking-wider"
          >
            {title}
          </h2>
          <p className="text-xs text-muted-foreground mt-1 font-mono">
            current: {currentModel || "(unknown)"}
            {currentProviderSlug && ` · ${currentProviderSlug}`}
          </p>
        </header>

        <div className="px-5 pt-3 pb-2 border-b border-border">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              autoFocus
              placeholder="Filter providers and models…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-7 h-8 text-sm"
            />
          </div>
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-[200px_1fr] overflow-hidden">
          <ProviderColumn
            loading={loading}
            error={error}
            providers={filteredProviders}
            total={providers.length}
            selectedSlug={selectedSlug}
            query={trimmedQuery}
            allowCustomEndpoint={allowCustomEndpoint}
            onSelect={(slug) => {
              setSelectedSlug(slug);
              setSelectedModel("");
            }}
          />

          {allowCustomEndpoint && selectedSlug === CUSTOM_ENDPOINT_SLUG ? (
            <CustomEndpointForm
              onSaved={(args) => {
                onCustomEndpointSaved?.(args);
                onClose();
              }}
            />
          ) : (
            <ModelColumn
              provider={selectedProvider}
              models={filteredModels}
              allModels={models}
              selectedModel={selectedModel}
              currentModel={currentModel}
              currentProviderSlug={currentProviderSlug}
              onSelect={setSelectedModel}
              onKeySaved={() => refreshOptions(false)}
              onConfirm={(m) => {
                setSelectedModel(m);
                void applySelection(false, {
                  provider: selectedProvider?.slug ?? "",
                  model: m,
                  persistGlobal,
                  message: "",
                });
              }}
            />
          )}
        </div>

        <footer className="border-t border-border p-3 flex items-center justify-between gap-3 flex-wrap">
          {alwaysGlobal ? (
            <span className="text-xs text-muted-foreground">
              Saves to config.yaml — applies to new sessions.
            </span>
          ) : (
            <div className="flex items-center gap-2">
              <Checkbox
                checked={persistGlobal}
                id="model-picker-persist-global"
                onCheckedChange={(checked) =>
                  setPersistGlobal(checked === true)
                }
              />

              <Label
                className="font-display normal-case tracking-normal text-xs text-muted-foreground cursor-pointer"
                htmlFor="model-picker-persist-global"
              >
                Persist globally (otherwise this session only)
              </Label>
            </div>
          )}

          <div className="flex items-center gap-2 ml-auto">
            <Button
              outlined
              onClick={() => refreshOptions()}
              disabled={applying || loading || refreshing}
            >
              {refreshing ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
              Refresh Models
            </Button>
            <Button outlined onClick={onClose} disabled={applying}>
              Cancel
            </Button>
            <Button onClick={confirm} disabled={!canConfirm}>
              {applying ? <Spinner /> : "Switch"}
            </Button>
          </div>
        </footer>
      </div>
      <ConfirmDialog
        open={!!pendingConfirm}
        title="Expensive Model Warning"
        description={pendingConfirm?.message}
        destructive
        confirmLabel="Switch anyway"
        cancelLabel="Cancel"
        loading={applying}
        onCancel={() => setPendingConfirm(null)}
        onConfirm={() => {
          const pending = pendingConfirm;
          if (!pending) return;
          setPendingConfirm(null);
          void applySelection(true, pending);
        }}
      />
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ */
/*  Provider column                                                    */
/* ------------------------------------------------------------------ */

function ProviderColumn({
  loading,
  error,
  providers,
  total,
  selectedSlug,
  query,
  allowCustomEndpoint = false,
  onSelect,
}: {
  loading: boolean;
  error: string | null;
  providers: ModelOptionProvider[];
  total: number;
  selectedSlug: string;
  query: string;
  allowCustomEndpoint?: boolean;
  onSelect(slug: string): void;
}) {
  return (
    <div className="border-r border-border overflow-y-auto">
      {loading && (
        <div className="flex items-center gap-2 p-4 text-xs text-muted-foreground">
          <Spinner className="text-xs" /> loading…
        </div>
      )}

      {error && <div className="p-4 text-xs text-destructive">{error}</div>}

      {!loading && !error && providers.length === 0 && (
        <div className="p-4 text-xs text-muted-foreground italic">
          {query
            ? "no matches"
            : total === 0
              ? "no authenticated providers"
              : "no matches"}
        </div>
      )}

      {providers.map((p) => {
        const active = p.slug === selectedSlug;
        return (
          <ListItem
            key={p.slug}
            active={active}
            onClick={() => onSelect(p.slug)}
            className={`items-start text-xs border-l-2 ${
              active ? "border-l-primary" : "border-l-transparent"
            }`}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="font-medium truncate">{p.name}</span>
                {p.is_current && <CurrentTag />}
              </div>
              <div className="text-xs text-text-secondary font-mono truncate">
                {p.slug} ·{" "}
                {p.authenticated === false
                  ? "not set up"
                  : `${p.total_models ?? p.models?.length ?? 0} models`}
              </div>
            </div>
          </ListItem>
        );
      })}

      {allowCustomEndpoint && !loading && (
        <ListItem
          active={selectedSlug === CUSTOM_ENDPOINT_SLUG}
          onClick={() => onSelect(CUSTOM_ENDPOINT_SLUG)}
          className={`items-start text-xs border-l-2 border-t border-t-border ${
            selectedSlug === CUSTOM_ENDPOINT_SLUG
              ? "border-l-primary"
              : "border-l-transparent"
          }`}
        >
          <Plus className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="font-medium">Custom endpoint</div>
            <div className="text-xs text-text-secondary truncate">
              any OpenAI-compatible URL
            </div>
          </div>
        </ListItem>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Model column                                                       */
/* ------------------------------------------------------------------ */

function ModelColumn({
  provider,
  models,
  allModels,
  selectedModel,
  currentModel,
  currentProviderSlug,
  onSelect,
  onConfirm,
  onKeySaved,
}: {
  provider: ModelOptionProvider | null;
  models: { model: string; positions: number[] }[];
  allModels: string[];
  selectedModel: string;
  currentModel: string;
  currentProviderSlug: string;
  onSelect(model: string): void;
  onConfirm(model: string): void;
  onKeySaved?(): void;
}) {
  if (!provider) {
    return (
      <div className="overflow-y-auto">
        <div className="p-4 text-xs text-muted-foreground italic">
          pick a provider →
        </div>
      </div>
    );
  }

  const needsSetup = provider.authenticated === false;
  const needsKey =
    needsSetup && provider.auth_type === "api_key" && !!provider.key_env;

  return (
    <div className="overflow-y-auto">
      {needsKey ? (
        <ProviderKeySetup
          key={provider.slug}
          provider={provider}
          onSaved={() => onKeySaved?.()}
        />
      ) : needsSetup ? (
        <div className="p-3 text-xs text-muted-foreground border-b border-border">
          {provider.name} signs in with an account instead of an API key.
          Connect it under <span className="font-medium">Keys → OAuth
          logins</span> in the sidebar, then press Refresh Models.
        </div>
      ) : (
        provider.warning && (
          <div className="p-3 text-xs text-destructive border-b border-border">
            {provider.warning}
          </div>
        )
      )}

      {needsSetup && models.length === 0 ? null : models.length === 0 ? (
        <div className="p-4 text-xs text-muted-foreground italic">
          {allModels.length
            ? "no models match your filter"
            : "no models listed for this provider"}
        </div>
      ) : (
        models.map(({ model: m, positions }) => {
          const active = m === selectedModel;
          const isCurrent =
            m === currentModel && provider.slug === currentProviderSlug;

          return (
            <ListItem
              key={m}
              active={active}
              onClick={() => onSelect(m)}
              onDoubleClick={() => onConfirm(m)}
              className="px-3 py-1.5 text-xs font-mono"
            >
              <Check
                className={`h-3 w-3 shrink-0 ${active ? "text-primary" : "text-transparent"}`}
              />
              <span className="flex-1 truncate">
                <HighlightedText text={m} positions={positions} />
              </span>
              {isCurrent && <CurrentTag />}
            </ListItem>
          );
        })
      )}
    </div>
  );
}

function CurrentTag() {
  return (
    <span className="text-display text-xs tracking-wider text-primary shrink-0">
      current
    </span>
  );
}

/**
 * Render `text` with the characters at `positions` emphasised, so users can
 * see which characters their fuzzy query matched. Positions are indices into
 * `text`; out-of-range indices are ignored.
 */
function HighlightedText({
  text,
  positions,
}: {
  text: string;
  positions: number[];
}) {
  if (!positions.length) {
    return <>{text}</>;
  }

  const hit = new Set(positions);

  return (
    <>
      {Array.from(text).map((ch, i) =>
        hit.has(i) ? (
          <mark
            key={i}
            className="bg-transparent text-primary font-semibold underline underline-offset-2"
          >
            {ch}
          </mark>
        ) : (
          <span key={i}>{ch}</span>
        ),
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Provider key setup (unconfigured API-key providers)                */
/* ------------------------------------------------------------------ */

function ProviderKeySetup({
  provider,
  onSaved,
}: {
  provider: ModelOptionProvider;
  onSaved(): void;
}) {
  const keyEnv = provider.key_env ?? "";
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const save = async () => {
    const trimmed = value.trim();
    if (!trimmed || saving) return;
    setSaving(true);
    setMessage(null);
    try {
      // Reject a key the provider says is wrong; an unreachable check (offline,
      // no probe for this provider) doesn't block saving.
      const check = await api
        .validateProviderCredential(keyEnv, trimmed)
        .catch(() => null);
      if (check && !check.ok && check.reachable) {
        setMessage(check.message || "That API key was rejected.");
        return;
      }
      await api.setEnvVar(keyEnv, trimmed);
      setValue("");
      onSaved();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      className="p-3 grid gap-2 border-b border-border"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <Label
        htmlFor={`provider-key-${provider.slug}`}
        className="font-display normal-case tracking-normal text-xs"
      >
        Paste your {provider.name} API key to use it
      </Label>
      <div className="flex items-center gap-2">
        <Input
          id={`provider-key-${provider.slug}`}
          type="password"
          autoComplete="off"
          placeholder={keyEnv}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="h-8 text-sm font-mono"
        />
        <Button type="submit" size="sm" disabled={!value.trim() || saving}>
          {saving ? <Spinner /> : "Save key"}
        </Button>
      </div>
      {message ? (
        <p className="text-xs text-destructive">{message}</p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Saved as {keyEnv} in this profile&apos;s .env (also editable on the
          Keys page). The model list loads once the key is saved.
        </p>
      )}
    </form>
  );
}

/* ------------------------------------------------------------------ */
/*  Custom OpenAI-compatible endpoint                                  */
/* ------------------------------------------------------------------ */

function CustomEndpointForm({
  onSaved,
}: {
  onSaved(args: { provider: string; model: string }): void;
}) {
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [found, setFound] = useState<string[]>([]);
  const [busy, setBusy] = useState<"find" | "save" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  const input = () => ({
    name: name.trim() || "Custom endpoint",
    base_url: baseUrl.trim(),
    model: model.trim(),
    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
  });

  const findModels = async () => {
    if (!baseUrl.trim() || busy) return;
    setBusy("find");
    setMessage(null);
    try {
      const r = await api.validateCustomEndpoint(input());
      const ids = r.models ?? [];
      setFound(ids);
      if (!r.ok) {
        setMessage({ ok: false, text: r.message || "Could not reach it." });
      } else if (ids.length) {
        if (!model.trim()) setModel(ids[0]);
        setMessage({ ok: true, text: `Found ${ids.length} model(s).` });
      } else {
        setMessage({
          ok: true,
          text: "Reachable, but it lists no models — type the model name.",
        });
      }
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    const body = input();
    if (!body.base_url || !body.model || busy) return;
    setBusy("save");
    setMessage(null);
    try {
      const r = await api.saveCustomEndpoint({
        ...body,
        models: found.length ? found : [body.model],
        make_default: true,
      });
      onSaved({ provider: r.id, model: body.model });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <form
      className="overflow-y-auto p-4 grid gap-3 content-start"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <p className="text-xs text-muted-foreground">
        Use any server that speaks the OpenAI API — LM Studio, Ollama, vLLM,
        llama.cpp, LiteLLM or a hosted provider. The key (if any) is stored in
        .env.
      </p>
      <div className="grid gap-1.5">
        <Label htmlFor="custom-ep-name">Name</Label>
        <Input
          id="custom-ep-name"
          placeholder="My local model"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-8 text-sm"
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="custom-ep-url">Base URL</Label>
        <Input
          id="custom-ep-url"
          placeholder="http://localhost:11434/v1"
          value={baseUrl}
          onChange={(e) => {
            setBaseUrl(e.target.value);
            setFound([]);
          }}
          className="h-8 text-sm font-mono"
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="custom-ep-key">API key (optional)</Label>
        <Input
          id="custom-ep-key"
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="h-8 text-sm font-mono"
        />
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="custom-ep-model">Model</Label>
        <div className="flex items-center gap-2">
          <Input
            id="custom-ep-model"
            list="custom-ep-models"
            placeholder="model id"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="h-8 text-sm font-mono"
          />
          <datalist id="custom-ep-models">
            {found.map((id) => (
              <option key={id} value={id} />
            ))}
          </datalist>
          <Button
            type="button"
            size="sm"
            outlined
            onClick={() => void findModels()}
            disabled={!baseUrl.trim() || busy !== null}
          >
            {busy === "find" ? <Spinner /> : "Find models"}
          </Button>
        </div>
      </div>
      {message && (
        <p
          className={cn(
            "text-xs",
            message.ok ? "text-muted-foreground" : "text-destructive",
          )}
        >
          {message.text}
        </p>
      )}
      <div className="flex justify-end">
        <Button
          type="submit"
          size="sm"
          disabled={!baseUrl.trim() || !model.trim() || busy !== null}
        >
          {busy === "save" ? <Spinner /> : "Save & use as main model"}
        </Button>
      </div>
    </form>
  );
}
