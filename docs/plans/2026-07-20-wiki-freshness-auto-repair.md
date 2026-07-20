# Wiki Freshness Auto-Repair Implementation Plan

> **For Hermes:** Implement this plan task-by-task with tests before deployment.

**Goal:** Turn the existing weekly wiki freshness audit into a backup-first maintenance job that automatically repairs unambiguous structural problems, records every mutation, and continues reporting source reachability.

**Architecture:** Add a deterministic `wiki_repair.py` pass alongside the existing reachability checker. The repair pass reads `40-wiki/SCHEMA.md` conventions, infers missing curated metadata only from the current valid type folder, moves pages only when explicit frontmatter gives an unambiguous destination, repairs `index.md`, and backs up every changed source file outside the vault before mutation. Ambiguous classifications, path collisions, and dead URLs remain reported rather than guessed.

**Tech Stack:** Python 3 standard library, pytest, existing Bash/Hermes cron wrapper.

---

### Task 1: Define repair behavior with tests

**Files:**
- Modify: `hermes/wiki-freshness/tests/test_wiki_freshness.py`
- Create: `hermes/wiki-freshness/tests/test_wiki_repair.py`

Add fixture-vault tests for missing frontmatter/type repair, type-folder relocation, collision fail-safe behavior, imported-capture placement, index insertion/count/date updates, dry-run immutability, backup creation, and log entries.

### Task 2: Implement deterministic repair engine

**Files:**
- Create: `hermes/wiki-freshness/wiki_repair.py`

Implement audit/plan/apply phases, canonical type-folder mappings, safe frontmatter updates, kebab-case checks, backup manifest creation, move collision guards, index repairs, and append-only logging. Default to dry-run; require `--apply` for mutation.

### Task 3: Wire live repair into the existing cron

**Files:**
- Modify: `hermes/scripts/wiki_freshness_cron.sh`
- Modify: `hermes/wiki-freshness/README.md`
- Modify: `hermes/scripts/README.md`

Run `wiki_repair.py --apply` first, then `wiki_freshness.py --no-dry-run --no-llm`. Preserve the current cron ID and weekly schedule. Document that deterministic structural issues are fixed, while ambiguous moves and unresolvable dead sources fail safe and are reported.

### Task 4: Validate safely

Run the full test suite, shell syntax check, wrapper `--check`, and a live dry-run against the real vault. Create a real-vault backup, run one live repair cycle, inspect every changed path and log/index entry, then refresh and query CocoIndex on vectorsigma.

### Task 5: Deploy and verify

Update job `b4cff39d7b8e` in place if its scheduler metadata needs adjustment, manually run it once, inspect the delivered output and vault hashes, then commit and push the clean home-ops changes.
