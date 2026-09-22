---
title: Knowledge base
description: Attach a file of any size, then ask Robo about it. Local, offline, on every surface.
---

# Knowledge base

Attach a document, and Robo can answer questions about it, however large it is.
A 900-page PDF, a 2 GB log, a spreadsheet with a million rows: Robo does not try
to read the whole thing into its context. It indexes the file into a local
search store and pulls out only the passages that matter for each question.

## What it handles

Text of any kind (plain text, Markdown, code, CSV, JSON, YAML, logs, HTML),
PDF, Word (`.docx`), PowerPoint (`.pptx`) and Excel (`.xlsx`). Images go to
Robo's vision tools instead.

## How to use it

- **TUI**: `/attach <path>` (also `/upload`, `/index`). Drag a file onto the
  terminal to paste its path, so `/attach ` plus a drag is the whole gesture.
  `/attach` on its own lists what is indexed. Then ask: "what does the contract
  say about termination?"
- **Web dashboard**: upload the file on the **Files** page (it is indexed on
  arrival), or type `/attach <path>` in the chat, which mirrors the TUI.
- **Desktop app**: attach the file in the composer. It is indexed on arrival.
- **Anywhere, by voice or text**: "index ~/reports/q3.pdf" or "remember this
  file", and Robo calls `knowledge_add`. Pasted text works too.
- Ask "what do you know about…" and Robo searches with `knowledge_search`,
  quoting the passages it used. "What have I given you?" lists the documents.
- "Forget the Q3 report" removes it.

Re-adding an unchanged file costs nothing; a changed file replaces its old
version.

## Where it lives, and privacy

Everything is stored in `<your Robo home>/knowledge/knowledge.db`, a SQLite
file using SQLite's own full-text engine. Nothing is uploaded, no model is
downloaded, and it works with no network at all. Delete the file to erase the
knowledge base.

## The tools

| Tool | What it does |
|---|---|
| `knowledge_add` | Index a file path or pasted text (any size) |
| `knowledge_search` | Return the most relevant passages for a question |
| `knowledge_list` | Show what is indexed, with size and part count |
| `knowledge_remove` | Remove a document |

They live in the `knowledge` toolset, which is on by default.
