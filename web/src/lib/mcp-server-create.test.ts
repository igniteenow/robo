import { describe, expect, it } from "vitest";

import {
  buildMcpServerCreate,
  emptyMcpServerDraft,
  parseArgs,
  parseHeaders,
} from "./mcp-server-create";

describe("buildMcpServerCreate", () => {
  it("builds an HTTP Bearer request without stdio fields", () => {
    const server = buildMcpServerCreate({
      ...emptyMcpServerDraft(),
      name: " Linear ",
      url: " https://mcp.linear.app/mcp ",
      httpAuth: "header",
      bearerToken: "Bearer secret-token",
      command: "ignored",
      args: "--ignored",
      env: "IGNORED=value",
    });

    expect(server).toEqual({
      name: "Linear",
      url: "https://mcp.linear.app/mcp",
      auth: "header",
      bearer_token: "Bearer secret-token",
    });
  });

  it("builds OAuth and unauthenticated HTTP requests without a token", () => {
    expect(
      buildMcpServerCreate({
        ...emptyMcpServerDraft(),
        name: "oauth",
        url: "https://example.com/mcp",
        httpAuth: "oauth",
      }),
    ).toEqual({
      name: "oauth",
      url: "https://example.com/mcp",
      auth: "oauth",
    });

    expect(
      buildMcpServerCreate({
        ...emptyMcpServerDraft(),
        name: "public",
        url: "https://example.com/mcp",
      }),
    ).toEqual({
      name: "public",
      url: "https://example.com/mcp",
    });
  });

  it("parses stdio arguments and environment assignments", () => {
    const server = buildMcpServerCreate({
      ...emptyMcpServerDraft(),
      name: "local",
      transport: "stdio",
      command: " uvx ",
      args: "mcp-server, --debug",
      env: "API_KEY=secret\nURL=https://example.com?a=b\nINVALID",
    });

    expect(server).toEqual({
      name: "local",
      command: "uvx",
      args: ["mcp-server", "--debug"],
      env: {
        API_KEY: "secret",
        URL: "https://example.com?a=b",
      },
    });
  });

  it("rejects missing transport fields and Bearer tokens", () => {
    expect(() => buildMcpServerCreate(emptyMcpServerDraft())).toThrow(
      "Name required",
    );
    expect(() =>
      buildMcpServerCreate({
        ...emptyMcpServerDraft(),
        name: "remote",
      }),
    ).toThrow("URL required");
    expect(() =>
      buildMcpServerCreate({
        ...emptyMcpServerDraft(),
        name: "remote",
        url: "https://example.com/mcp",
        httpAuth: "header",
      }),
    ).toThrow("Bearer token required");
    expect(() =>
      buildMcpServerCreate({
        ...emptyMcpServerDraft(),
        name: "local",
        transport: "stdio",
      }),
    ).toThrow("Command required");
  });

  it("builds SSE servers with extra headers", () => {
    expect(
      buildMcpServerCreate({
        ...emptyMcpServerDraft(),
        name: "events",
        transport: "sse",
        url: "https://example.com/sse",
        headers: "X-API-Key: k-1\nX-Team=blue\n",
      }),
    ).toEqual({
      name: "events",
      url: "https://example.com/sse",
      transport: "sse",
      headers: { "X-API-Key": "k-1", "X-Team": "blue" },
    });
  });

  it("rejects a header line without a name", () => {
    expect(() =>
      buildMcpServerCreate({
        ...emptyMcpServerDraft(),
        name: "r",
        url: "https://example.com/mcp",
        headers: "just-a-value",
      }),
    ).toThrow("Header needs");
  });
});

describe("parseArgs", () => {
  it("keeps quoted Windows paths with spaces and backslashes whole", () => {
    expect(
      parseArgs('-y @modelcontextprotocol/server-filesystem "C:\\My Files\\docs"'),
    ).toEqual(["-y", "@modelcontextprotocol/server-filesystem", "C:\\My Files\\docs"]);
  });

  it("treats a trailing comma as a separator but keeps commas inside words", () => {
    expect(parseArgs("mcp-server, --dirs=a,b ,")).toEqual([
      "mcp-server",
      "--dirs=a,b",
    ]);
  });

  it("keeps an explicitly empty quoted argument", () => {
    expect(parseArgs('--name ""')).toEqual(["--name", ""]);
  });

  it("reports an unclosed quote", () => {
    expect(() => parseArgs('"oops')).toThrow("unclosed");
  });
});

describe("parseHeaders", () => {
  it("accepts colon and equals separators and keeps colons in values", () => {
    expect(parseHeaders("Authorization: Basic a:b\nX-A=1")).toEqual({
      Authorization: "Basic a:b",
      "X-A": "1",
    });
  });
});
