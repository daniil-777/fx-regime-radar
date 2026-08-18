# Start here — from download to building in 5 steps

This folder IS the project. Do not move files around inside it — the structure
is exactly what Claude Code expects.

1. Open this folder in VS Code: File → Open Folder → select `fx-regime-radar`.
   You will see every file in the sidebar, including the `.claude` folder —
   VS Code shows dot-folders by default (Finder and Windows Explorer hide them,
   which is why they seemed missing earlier).

2. Install Claude Code once, if you haven't:
   `npm install -g @anthropic-ai/claude-code`  (needs Node.js 18+)
   Install guide: https://docs.claude.com/en/docs/claude-code/overview
   Optional: also install the "Claude Code" extension from the VS Code
   marketplace for the in-editor experience.

3. Open the built-in terminal (Ctrl+` on Windows/Linux, Cmd+` on Mac) and run:
   `claude`
   The first run asks you to log in with your Anthropic account.

4. Type `/` — you should see the phase commands appear in the list.
   Run the first one:  `/phase-00-scaffold`

5. When its Verify block passes and it has quizzed you, continue in order:
   /phase-01-data → /phase-02-features → /phase-03-hmm →
   /phase-04-validate-hmm → /phase-05-dashboard → /phase-06-automation →
   /phase-07-forecaster → /phase-08-siren → /phase-09-narrator →
   /phase-10-polish

What the other files are:
- USAGE.md — the full workflow, rules of engagement, phase map, deploy notes.
  Read it before phase 00.
- CLAUDE.md — the project constitution. Claude Code reads it automatically at
  every session; read it once yourself so you know the ten golden rules.
- .claude/commands/ — the 11 phase prompts. You never need to open these
  manually, but you can: if a slash command ever fails to appear, open the
  file and paste its contents into Claude Code as a normal message. Identical
  result.

One rule above all: never skip a Verify block, and never let code you can't
explain pile up. The app gets you the interview; understanding it gets you
hired.
