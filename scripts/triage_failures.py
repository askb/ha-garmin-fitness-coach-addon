#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
"""Deterministic triage: read failure JSON and open deduped GitHub issues.

Replaces the LLM-based triage in the original Claude design. Avoids the
prompt-injection vector entirely by never feeding untrusted log text to
an LLM. Issues are labelled `ai-fix-me` which triggers fix.yml.

Reads failure list from stdin (JSON array). Uses the gh CLI for issue
operations - environment must have GH_TOKEN set with issues:write.

Behaviour:
- Search open issues for the failure signature in body marker
- If found, skip (deduplicated)
- Otherwise, create issue with `ai-fix-me` and `automated` labels
- Cap at MAX_NEW_ISSUES per invocation (defense L10)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

MAX_NEW_ISSUES = 5
SIG_MARKER = "<!-- failure-signature:"


def gh(*args: str, input_text: str | None = None) -> tuple[int, str]:
    res = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        input=input_text,
        check=False,
    )
    return res.returncode, (res.stdout + res.stderr)


def existing_signatures(repo: str) -> set[str]:
    code, out = gh(
        "issue", "list", "--repo", repo,
        "--label", "ai-fix-me", "--state", "open",
        "--limit", "100",
        "--json", "body",
    )
    if code != 0:
        return set()
    try:
        items = json.loads(out)
    except Exception:
        return set()
    sigs: set[str] = set()
    for it in items:
        body = it.get("body", "")
        idx = body.find(SIG_MARKER)
        if idx == -1:
            continue
        end = body.find("-->", idx)
        if end == -1:
            continue
        sigs.add(body[idx + len(SIG_MARKER):end].strip())
    return sigs


def create_issue(repo: str, failure: dict, run_url: str) -> None:
    body = (
        f"{SIG_MARKER} {failure['signature']} -->\n\n"
        f"## Failure\n\n"
        f"**Component:** `{failure['component']}`\n\n"
        f"**Key:** `{failure['key']}`\n\n"
        f"### Snippet\n\n"
        f"```\n{failure.get('snippet', '(no snippet)')}\n```\n\n"
        f"---\n\n"
        f"_Detected by [self-healing CI scan]({run_url}). "
        f"This issue has the `ai-fix-me` label which will trigger an "
        f"automated fix attempt. To opt out, remove the label._"
    )
    title = f"[auto] {failure['title']}"[:240]
    gh(
        "issue", "create", "--repo", repo,
        "--title", title,
        "--body", body,
        "--label", "ai-fix-me",
        "--label", "automated",
    )


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = os.environ.get("RUN_URL", "")
    if not repo:
        print("GITHUB_REPOSITORY not set", file=sys.stderr)
        return 1

    raw = sys.stdin.read().strip() or "[]"
    failures = json.loads(raw)
    if not failures:
        print("no failures to triage")
        return 0

    existing = existing_signatures(repo)
    created = 0
    for f in failures:
        if created >= MAX_NEW_ISSUES:
            break
        if f["signature"] in existing:
            print(f"skip duplicate: {f['signature']} ({f['title']})")
            continue
        create_issue(repo, f, run_url)
        created += 1
        print(f"created: {f['title']}")

    print(f"\ntriage complete: {created} new, {len(failures) - created} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
