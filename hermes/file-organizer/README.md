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
