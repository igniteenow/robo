---
sidebar_position: 7
title: "Team mode"
description: "Two to four models work one goal together in the desktop app: the lead works, the others verify its options and vote, and a Final seat writes the outcome you can question"
---

# Team mode

Team mode is a desktop-only way to put several models on one goal at the same time. Open **Team** in the sidebar, pick a model for each seat, type the goal, and press **Start team**. Every seat is an ordinary Robo session with its own model and the full toolset, shown live, side by side, each a read-only view of its own work — so the panes never overlap. Under the seats sits the **Final outcome** pane: when the team is done, a separate seat reads the whole run and writes the one answer the team stands behind, and you can keep asking it questions. One message bar at the bottom talks to whichever seat you pick — a member or the Final — so you can read along and chime in while the team works, and dig into the outcome once it lands.

Nothing changes for the normal chat. Team mode only exists on the **Team** page; until you open it, Robo desktop is exactly what it was.

## How a team works

One seat is the **lead**; the others are **reviewers**; the **Final** waits until they are done.

1. **The lead works.** It gets the goal and does the work itself — researching, running commands, editing files — and stops at every real fork, or whenever it has a result worth checking, with two to four concrete options.
2. **The reviewers check, vote — and guide.** Each reviewer gets the same options, verifies them independently on its own model (reading the files the lead touched, running the tests, re-checking the sources), and ranks all of them with a reason. Options are shown to every reviewer in a different order so no position gets an advantage, and the lead never votes on its own options. Every review also carries **guidance for the lead**: what it missed or got wrong, the risks ahead, what the reviewer verified and how, and the concrete next steps it recommends. The reviewers are the lead's senior partners on the goal, not a scorecard.
3. **The most-voted option wins.** Rankings are tallied as a ranked vote (Borda count): an option everyone puts first or second beats one that a narrow majority puts first and the rest put last. A tie falls to the reviewers' confidence, then to the lead's own order. The lead is told which option won and why, gets every reviewer's guidance in full, and continues from there — fixing what was flagged, using what was verified, and saying in its next summary what it took and what it set aside.
4. **Side tasks run in parallel.** When the lead hands off an independent piece of work, an idle reviewer does it while the lead keeps going, and brings the result back. A result that itself has options gets the same review from the other idle reviewers — never from the member who produced it.
5. **The lead says done — and the reviewers check that it is.** When the lead reports the goal met, every free reviewer gets a **completion check**: the lead's result, the goal, and one question — does this meet the goal completely and verifiably? They check it with their tools and vote *Done* or *Not done*. *Not done* sends the lead back to work with their guidance as the work order, as the next round; this can happen up to three times per run, after which the result is accepted as it stands so a team that cannot agree still ends. (With a round cap set, reaching it asks the lead to wrap up instead.)
6. **The Final writes the outcome.** The Final seat — a session of its own, on the lead's model — is handed the goal, the lead's closing answer, every round's winner with the reviewers' reasons and every side-task result, and asked for one complete, verified answer: keep what the team got right, fix what the reviewers flagged, fill the gaps, and check anything uncertain with its tools. Its reply is the run's outcome: it sits in the Final pane and in the log with a copy button, and the Final stays open so you can ask it why, what else, or what next, with the whole run in its context.

Everything the team decides is kept in a shared notebook — the goal, each round's winner, every side-task result — and carried into every later prompt, so the members share what they learn. The notebook is never trimmed: on a long run the first decision is still in the last prompt. The Final seat gets the detailed version, with every reviewer's reason and guidance under its round.

## Working side by side without stepping on each other

The members are sessions on one backend, so they share the same home directory and working tree. Several models editing the same file at the same moment is the one thing that reliably breaks a run — it shows up as a tool error such as *could not find a match … the file has been updated by teammates already*, usually from two members patching the same skill or memory file. Two things keep that from happening:

**Team seats skip the automatic self-improvement review.** After a normal chat turn Robo may run a background review that saves what it learned into your skills and memory. With several seats finishing turns within seconds of each other, those reviews would all patch the same files at once, so every team seat is opened with that review switched off (the backend's `background_review` flag on the session; it is re-applied when a seat is resumed after a reconnect). Your ordinary chats are not affected, and nothing else about the seat changes.

**Team seats skip the per-answer fact check, too.** In a normal chat, Robo checks each answer against sources with its own research before the turn ends (see [Fact check](./fact-check.md)). A team verifies its own answers — the reviewers check the lead's options with their tools, and the completion check verifies the result against the goal — so running the checker after every turn of every seat only made each turn minutes longer: the answer was on screen, the pane still showed Robo working, and a question typed to the Final meanwhile waited until the check was over. Team seats are opened with the check switched off (`fact_check: false` on the session, re-applied on resume). Your ordinary chats keep it.

**Every team prompt carries a short set of team rules:**

- Robo's own shared state is read-only during a run — no editing, patching or creating skills, memory or config, and no self-improvement or skill-maintenance steps;
- the lead edits whatever project files the goal requires; a reviewer, while reviewing, changes no project file and puts findings or a proposed diff in its reply; a side-task worker touches only the files its task names or that it creates, never a file the lead is working in; scratch notes go in a file named for the seat;
- no destructive, global or long-lived commands (system-wide installs, resets, deletes outside the seat's own scratch files, servers, watchers, background jobs) — reading, searching, analysing, computing and running the project's own tests are unrestricted;
- effort goes into the goal: go deep, check facts against real evidence, be exact.

Together these keep the members from colliding while they work in parallel and keep the review noise out of the panes, while every seat can still do what it needs to reach the goal.

## The page

- **Members** — how many seats, 2 to 4. Seats are the lead (first) and the reviewers. The Final is an extra seat on top, always present; it is not counted here.
- **Model per seat** — the button on each seat opens the same model picker the chat uses, with every provider and model Robo offers elsewhere. A seat left on *Profile default* uses your profile's model. The Final runs on the lead's model and has no pick of its own.
- **Goal** — type it and press **Start team** (or Enter). The box clears as the goal is sent, like a chat composer, so the next goal can be typed once the run ends; the running goal stays readable in the status line and at the top of the log.
- **Rounds** — *Unlimited* by default: the team works until the lead reports done and the reviewers agree it is. Pick a cap (3 to 50) when you want a bound; when it is reached the lead is asked for a final answer.
- **The panes** — the members laid out in a clean grid (two side by side, three in a row, four as a 2×2), each a live read-only transcript of its session. Click a pane to select it; the selected pane is ringed.
- **Final outcome** — the full-width pane under the grid, with a star. Before the run ends it says what it is waiting for; while the outcome is being written it shows the brief and the answer streaming in; afterwards it is a transcript you can keep talking to.
- **Message a seat** — the single bar under the panes sends to the selected seat (switch with the name chips or by clicking a pane; the Final is one of the chips). Your message appears in that seat's pane the moment you send it — with the thinking indicator when the seat was idle — and the bar clears. It is a *queued* message, so it never cuts into a turn the seat is already running: a seat that is mid-turn shows your message at the end of its transcript and takes it up as its next turn. A seat that cannot take a message yet says why in the bar (it is still opening, it could not open, the Final has not been written).
- **Start team / Stop** — Stop interrupts every member mid-turn — the Final too, if it is writing — and ends the run.
- **Approvals in several panes** — when more than one seat is waiting on a command approval at the same time, the ⌘⏎ / Esc shortcuts answer only the approval in the pane that has the focus (click into it first); with a single approval on screen they work from anywhere, as in the main chat. The buttons on each card always answer that card alone.
- **Rounds & votes** — the log on the right: each round, every reviewer's ranking with its reason and guidance, the decision and how it was reached, side tasks, the completion checks (accepted, or sent back with the guidance), errors, and the final outcome (shown once, in the answer box with its copy button). The log follows new lines while you are at the bottom; scroll up to reread a decision and it stays put until you come back down. Hide it to give the panes the full width.
- **New team** — closes every seat's session, the Final included, so the next start opens fresh ones. The sessions themselves stay in your history like any other chat.

Members are reused between runs as long as their model picks do not change, so a second goal starts with everything the team already knows; the Final follows the lead's pick the same way. Changing a seat's model gives that seat a fresh session on the next start.

## What keeps it bounded

- One run at a time; a run never survives an app restart (its sessions do).
- **No clock on a turn.** A lead turn or a review takes as long as the work takes — hours, if the goal needs them; the team only moves on when the backend says the turn ended. A command approval or a clarifying question shows in that member's pane like in any chat, and the team waits for your answer. **Stop** is the cut-off: it interrupts every seat and ends the run. A reviewer that errors or sends no usable vote casts no ballot, and the run keeps moving; a seat whose turn fails outright (its session could not start, say) is counted at once. With no valid ballots at all, the lead's first option stands and the log says so. The one safety net: a seat that has gone idle with nothing written and whose turn end never arrives (a dropped connection mid-turn) is given up on after five minutes of silence, so a lost signal cannot hold the team forever.
- **No round cap unless you set one**, and at most three completion-check send-backs per run, so a run that reaches "done" always ends. On a capped run, "done" on the last round is not checked — the cap is the bound there. The log says how each check went: accepted, sent back, no usable verdict, send-backs used up, or skipped because no reviewer was free.
- A lead that forgets the structured block is asked once to restate it; a plain answer with no options is taken as the result.
- The Final can only improve a run, never cost it one: if its session could not open, it is stopped, it times out, or it returns nothing, the lead's answer stands as the outcome and the log says so. (If you cap concurrent sessions in `config.yaml`, remember the Final takes a slot of its own when it starts writing.)
- If the connection to Robo drops, the run fails and the members are resumed on the next start (each seat is re-attached through the backend, so a restarted backend is handled too). Switching profiles forgets the crew — the sessions stay in your history — and the next start opens fresh seats on the new profile.

## When to use it

Team mode is for work where a second opinion from a *different* model changes the outcome: design choices, research with conflicting sources, refactors with several plausible routes, long multi-step jobs where one early mistake would otherwise spread, anything where you would otherwise ask two assistants and compare. For a quick answer, a normal chat is faster and cheaper — every round costs one lead turn plus one review turn per reviewer, and the completion check costs one more review turn per reviewer. For the hardest goals: give each seat a model from a different provider, put the strongest one in the lead, and state in the goal what "done" means — that is what the reviewers hold the lead to.

## See also

- [Mixture of Agents](./mixture-of-agents.md) — several models inside one reply, where reference models inform an aggregator.
- [Delegation](./delegation.md) — subagents a single session spawns for parts of its own task.
- [Desktop app](../desktop.md)
