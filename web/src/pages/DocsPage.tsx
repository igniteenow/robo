import { useLayoutEffect } from "react";
import { BookOpen, ExternalLink } from "lucide-react";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";

// The guides live in the repository; GitHub renders them. There is no docs
// website, and GitHub does not allow framing, so this page links out rather
// than embedding anything.
export const ROBO_DOCS_URL =
  "https://github.com/igniteenow/robo/tree/main/website/docs";

const DS_BUTTON_OUTLINED_LINK_CN = cn(
  "group relative inline-grid grid-cols-[auto_1fr_auto] items-center",
  "px-[.9em_.75em] py-[1.25em] gap-2",
  "leading-0 font-bold tracking-[0.2em] uppercase",
  "text-midground bg-transparent shadow-midground",
  "shadow-[inset_-1px_-1px_0_0_#00000080,inset_1px_1px_0_0_#ffffff80]",
);

export default function DocsPage() {
  const { t } = useI18n();
  const { setEnd } = usePageHeader();

  useLayoutEffect(() => {
    setEnd(
      <a
        href={ROBO_DOCS_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={DS_BUTTON_OUTLINED_LINK_CN}
      >
        <ExternalLink className="size-3.5" />
        {t.app.openDocumentation}
      </a>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, t]);

  return (
    <div
      className={cn(
        "flex min-h-0 w-full min-w-0 flex-1 flex-col",
        "pt-1 sm:pt-2",
      )}
    >
      <PluginSlot name="docs:top" />
      <div className="flex flex-1 items-center justify-center">
        <a
          href={ROBO_DOCS_URL}
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "flex max-w-md flex-col items-center gap-4 rounded-sm border border-current/20 px-10 py-12 text-center",
            "transition-colors hover:border-current/50",
          )}
        >
          <BookOpen className="size-10 opacity-80" aria-hidden="true" />
          <span className="text-lg font-semibold">
            {t.app.nav.documentation}
          </span>
          <span className="inline-flex items-center gap-2 text-sm opacity-80">
            <ExternalLink className="size-3.5" aria-hidden="true" />
            {t.app.openDocumentation}
          </span>
        </a>
      </div>
      <PluginSlot name="docs:bottom" />
    </div>
  );
}
