# PARA file maintenance

This automation has two stages:

1. `para_file_namer.py` calls local Ollama for supported, old, root-level, generic-named images and writes fingerprinted proposals under `~/File Inbox/proposals/`. It never moves files.
2. `user_file_organizer.py` performs deterministic maintenance. It accepts only fresh high-confidence proposals whose source fingerprint still matches and whose destination is allowlisted. Exact project/area rules win over model placement; a validated model name can still be reused. Ambiguous `resource:review` proposals are report-only by default (`auto_apply_review: false`) because model self-confidence is not proof against hallucinated names. Generic material falls back to `~/03-Resources/File Intake/`.

Safety boundaries:

- root-level only; no recursive source traversal
- files newer than 60 minutes are ignored
- PARA roots, both current `02-Areas/personal*` vault trees, `/Users/sva/dotfiles`, Hermes, Library, Applications, repos, and hidden files are protected
- allowlisted exact rules route active assets to projects and ongoing work/home-lab material to Areas; unmatched directories are report-only
- no permanent deletion; old downloaded installers move to macOS Trash
- maximum 40 automatic actions per run
- destination collision renaming, source/destination containment checks, JSONL manifests, Markdown reports
- local model never writes directly; deterministic code validates and applies

Manual verification:

```bash
python3 -m pytest hermes/scripts/tests/test_user_file_organizer.py -q
python3 hermes/scripts/para_file_namer.py --config hermes/file-organizer/file-organization.json
python3 hermes/scripts/user_file_organizer.py --config hermes/file-organizer/file-organization.json --dry-run
```

Apply only after inspecting the newest proposal, manifest, and report:

```bash
python3 hermes/scripts/user_file_organizer.py --config hermes/file-organizer/file-organization.json --apply
```

Cron runs local Qwen prep at 03:00 and deterministic maintenance at 05:00. Both wrappers acquire the same atomic `/tmp/hermes-para-file-pipeline.lock`; if prep is still running, maintenance exits silently and cannot consume a partially generated proposal or mutate files concurrently.

## Opt-in image renaming in place

The daily job scans only immediate children of its configured roots; it does not recurse into `Pictures/stash`. For an explicit opaque-filename cleanup, point the local multimodal pass directly at that directory:

```bash
python3 hermes/scripts/para_file_namer.py \
  --config hermes/file-organizer/file-organization.json \
  --root /Users/sva/Pictures/stash \
  --include-opaque-ids \
  --max-items 54

python3 hermes/scripts/user_file_organizer.py \
  --config hermes/file-organizer/file-organization.json \
  --rename-root /Users/sva/Pictures/stash \
  --dry-run
```

Qwen receives each image directly as a multimodal Ollama attachment. The deterministic apply path rechecks size, mtime, SHA-256, extension, sanitized filename, source-root containment, collision safety, and the action cap. `--rename-root` can only rename immediate-child files inside the same directory; it cannot move them into PARA destinations. After inspecting the dry-run, replace `--dry-run` with `--apply`.
