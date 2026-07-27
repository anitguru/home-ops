# PARA File Maintenance Implementation Plan

> **For Hermes:** Implement and verify this plan task-by-task; recurring execution must be deterministic and local-token-only.

**Goal:** Recover SVA's paused daily organizer, move root-level drift into PARA safely, and use local Qwen vision only to propose useful filenames and bounded destinations.

**Architecture:** Split the workflow into a local-model prep pass and a deterministic maintenance pass. Prep calls local Ollama and writes fingerprinted JSONL proposals without moving files. Maintenance verifies fingerprints, confidence, filename safety, destination allowlists, root containment, age, and action caps before moving; ambiguity lands under `03-Resources/File Intake`, never directly in the Obsidian vault.

**Tech Stack:** Python 3 standard library, Ollama OpenAI-style local API, Hermes no-agent cron, JSON/JSONL audit artifacts.

---

## Task 1: Restore version-controlled PARA policy

- Create `hermes/file-organizer/file-organization.json`.
- Keep all PARA roots and both current vault copies on the never-touch list.
- Permit only root-level intake from Desktop, Downloads, Documents, Movies, Pictures, and loose home files.
- Default ambiguity to `03-Resources/File Intake`.

## Task 2: Harden the deterministic organizer

- Modify `hermes/scripts/user_file_organizer.py`.
- Validate source/destination containment and proposal fingerprints.
- Make installer rules root-specific.
- Enforce a per-run action cap and collision-safe moves.
- Preserve JSONL manifests and Markdown reports.

## Task 3: Add local-Qwen naming prep

- Create `hermes/scripts/para_file_namer.py`.
- Process only old, root-level, generic-named supported images.
- Use `qwen3.6:35b-a3b` over local Ollama with a strict JSON schema.
- Write proposals only; never move or delete.

## Task 4: Add tests

- Create `hermes/scripts/tests/test_user_file_organizer.py`.
- Cover root-scoped rules, low-confidence rejection, changed-file rejection, allowlisted project placement, resource fallback, collision handling, and action caps.

## Task 5: Recover current drift safely

- Create runtime audit directories.
- Run syntax/tests.
- Run local naming prep and organizer dry-run.
- Inspect every planned mutation.
- Apply only if paths/actions are within policy and errors are zero.

## Task 6: Switch cron to maintenance mode

- Keep the existing default-profile organizer job ID.
- Convert it to a no-agent repo-backed launcher at 05:00.
- Add a separate no-agent local naming-prep job at 03:00, two hours before 05:00 maintenance.
- Use one atomic shared pipeline lock in both wrappers so maintenance exits safely rather than overlapping a still-running local vision pass.
- Keep healthy no-op and report-only runs silent; report real actions or errors to SVA's personal channel.

## Task 7: Verify and ship

- Run both launchers manually.
- Trigger both cron jobs and inspect saved output plus manifests.
- Confirm no permanent deletion, no recursion, and no writes inside protected PARA/vault roots.
- Commit and push home-ops changes.
