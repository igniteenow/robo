import type { McpHttpAuth, McpServerCreate } from "@/lib/api";

/** "http" = Streamable HTTP, "sse" = legacy HTTP+SSE, "stdio" = local command. */
export type McpTransport = "http" | "sse" | "stdio";

export interface McpServerDraft {
  name: string;
  transport: McpTransport;
  url: string;
  httpAuth: McpHttpAuth;
  bearerToken: string;
  /** Extra HTTP headers, one `Name: value` per line (remote servers). */
  headers?: string;
  command: string;
  args: string;
  env: string;
}

export function emptyMcpServerDraft(): McpServerDraft {
  return {
    name: "",
    transport: "http",
    url: "",
    httpAuth: "none",
    bearerToken: "",
    headers: "",
    command: "",
    args: "",
    env: "",
  };
}

export function isRemoteMcpTransport(transport: McpTransport): boolean {
  return transport !== "stdio";
}

/**
 * Split an argument line on whitespace. Quotes group words (so Windows paths
 * like "C:\Program Files\app" stay one argument) and backslashes are literal.
 * A comma directly before whitespace also separates ("a, b"), but commas
 * inside a word are kept ("--dirs=a,b").
 */
export function parseArgs(raw: string): string[] {
  const out: string[] = [];
  let current = "";
  let quote: string | null = null;
  let quoted = false;
  let lastUnquotedComma = false;
  const push = () => {
    // A separator comma ("a, b") isn't part of the argument.
    if (lastUnquotedComma) current = current.slice(0, -1);
    if (current || quoted) out.push(current);
    current = "";
    quoted = false;
    lastUnquotedComma = false;
  };
  for (const ch of raw) {
    if (quote) {
      if (ch === quote) quote = null;
      else current += ch;
      lastUnquotedComma = false;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
      quoted = true;
      lastUnquotedComma = false;
    } else if (/\s/.test(ch)) {
      push();
    } else {
      current += ch;
      lastUnquotedComma = ch === ",";
    }
  }
  if (quote) throw new Error(`Args: unclosed ${quote} quote`);
  push();
  return out;
}

function parseEnv(raw: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const rawLine of raw.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const separator = line.indexOf("=");
    if (separator === -1) continue;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    if (key) env[key] = value;
  }
  return env;
}

/** `Name: value` (or `Name=value`) per line. */
export function parseHeaders(raw: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const rawLine of raw.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const colon = line.indexOf(":");
    const equals = line.indexOf("=");
    const separator =
      colon === -1 ? equals : equals === -1 ? colon : Math.min(colon, equals);
    if (separator <= 0) throw new Error(`Header needs "Name: value": ${line}`);
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    if (key) headers[key] = value;
  }
  return headers;
}

export function buildMcpServerCreate(draft: McpServerDraft): McpServerCreate {
  const name = draft.name.trim();
  if (!name) throw new Error("Name required");

  if (isRemoteMcpTransport(draft.transport)) {
    const url = draft.url.trim();
    if (!url) throw new Error("URL required");
    if (draft.httpAuth === "header" && !draft.bearerToken.trim()) {
      throw new Error("Bearer token required");
    }

    const server: McpServerCreate = { name, url };
    if (draft.transport === "sse") server.transport = "sse";
    if (draft.httpAuth !== "none") server.auth = draft.httpAuth;
    if (draft.httpAuth === "header") {
      server.bearer_token = draft.bearerToken;
    }
    const headers = parseHeaders(draft.headers ?? "");
    if (Object.keys(headers).length) server.headers = headers;
    return server;
  }

  const command = draft.command.trim();
  if (!command) throw new Error("Command required");

  const server: McpServerCreate = { name, command };
  const args = parseArgs(draft.args);
  if (args.length) server.args = args;
  const env = parseEnv(draft.env);
  if (Object.keys(env).length) server.env = env;
  return server;
}
