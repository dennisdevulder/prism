#!/usr/bin/env python3
"""Categorize plugin-hub rejected PRs into PRISM-relevant buckets.

Reads corpus/plugin_hub_rejected_prs.jsonl and writes
corpus/eval_rejections.jsonl with one record per PR plus a labeled bucket.

Buckets:
  saturation     - duplicate / functionality exists / superseded
  policy         - cites Rejected-or-Rolled-Back-Features or wiki rule
  build          - build failure / doesn't compile / commit hash issue
  invalid        - submission invalid / readme not followed / empty
  procedural     - dupe-of-own-PR, self-replaced, push-to-existing-branch
  unclear        - has maintainer comment but doesn't match patterns
  no_signal      - no human comments at all
  no_maintainer  - only non-maintainer comments (could still be self-close)

Categorization is regex-based against the lowercased concatenation of
comment bodies. Maintainer comments weight higher; the bucket is set
when at least one maintainer comment matches a pattern.
"""

import json
import re
from collections import Counter
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
IN_PATH = PRISM_ROOT / "corpus" / "plugin_hub_rejected_prs.jsonl"
OUT_PATH = PRISM_ROOT / "corpus" / "eval_rejections.jsonl"

KNOWN_MAINTAINERS = {
    "riktenx", "tylerwgrass", "raiyni", "1Defence", "cdfisher",
    "pajlada", "Felanbird", "LlemonDuck", "abextm",
    "deathbeam", "hexagonscape", "iProdigy", "Adamcake",
    "max-weber", "loldudester", "Zoinkwiz",
}
BOT_ACCOUNTS = {"runelite-github-app", "github-actions"}

# Patterns checked in priority order. First match wins.
PATTERNS = [
    ("saturation", [
        r"\bduplicat(?:e|ing)\b",
        r"\bdupe of\b",
        r"\bdupe pr\b",
        r"already (?:has|covered|exists|in)",
        r"already (?:supported|done|merged)",
        r"present in (?:the )?(?:idle notifier|core plugin|vanilla|.+ plugin)",
        r"(?:similar|same|equivalent) plugin (?:already )?exists",
        r"this (?:is|exists|functionality) (?:in|already)",
        r"functionality (?:is|already|present) (?:in|covered)",
        r"prefer (?:the |that )?\S+ plugin",
        r"feature(?:s)? (?:are |is )?(?:already )?(?:in|present)",
        r"covered by vanilla",
        r"use the .+ plugin instead",
        r"(?:use|consider using) \S+ instead",
        r"there are already multiple .+ plugins",
        r"there'?s (?:also )?(?:a |an )?\S+ plugin",
        r"should (?:just )?be (?:a feature|part) (?:added |of |in )",
        r"more suited as (?:a |an )?contribution",
        r"(?:doesn'?t|does)\s+\w+\s+(?:do|have|already)\s+(?:this|that)",
        r"the (?:other|existing) plugin (?:fits|covers|does)",
        r"(?:other|existing) plugin fits your needs",
        r"\w+ has support for (?:generic|this)",
        r"contribution to the core",
        r"merge(?:d)? (?:in|with) (?:the )?\w+ plugin",
        r"this is (?:already )?(?:available|done) (?:in|via|by)",
        # Soft-rejection language from second-pass review:
        r"redundant given",
        r"covered by (?:several|many|multiple) other",
        r"covered by .+ such as",
        r"prefer (?:you|that) (?:contribute|collab|merge|PR|push) (?:it )?(?:there|to)",
        r"(?:would you mind|why not) (?:PR|push|add|submit)(?:ing)? (?:it|this|these) (?:there|to|in)",
        r"(?:rather|i'?d (?:prefer|rather)) not have duplicates",
        r"\d+ (?:other|more|existing) (?:flipping|tracking|notifier|alert|timer) plugins",
        r"is there a reason you can'?t use",
        r"(?:extend|replace) the existing plugin",
        r"(?:put|add) (?:these|this|that) (?:kind of |type of )?(?:things|features|options|content) into (?:the )?existing",
        r"PR(?:ing)? (?:it )?there\?",
        r"collab(?:orate)? with (?:them|the (?:author|maintainer)|the existing)",
        r"(?:try|please) (?:and )?(?:collab|contribute|push|merge) (?:to|with|into)",
        r"work bits into that plugin",
        r"work with (?:the )?(?:existing|original) (?:author|maintainer|plugin)",
        r"in the form of \[",  # form of [Existing Plugin Name](url)
        r"feature already exists",
        r"these features already",
        r"runelite\.net/plugin-hub/show/[a-z0-9_-]+\s*\?",  # just a URL ending in ? — implicit saturation
        r"\?\s*\nyou can (?:check|use)",
    ]),
    ("policy", [
        r"rejected[- ]or[- ]rolled[- ]back",
        r"runelite/runelite/wiki/rejected",
        r"\bid based plugins?\b",
        r"\bid-based plugins?\b",
        r"player provided ids",
        r"reflection is not allowed",
        r"forbidden[- ]language[- ]features",
        r"plugins that simulate content",
        r"player scouting",
        r"third[- ]party[- ]client[- ]guidelines",
        r"\b3pc\b",
        r"jagex.+rules",
        r"breaks a rejected feature",
        r"violates (?:several |the )?(?:pvp|jagex|following rules)",
        r"violates the following",
        r"definition of botting",
        r"faking a (?:keyboard|mouse) event",
        r"third[- ]party client(?:\s|$)",
        r"sensitive apis?",
        # Crypto/RWT/abusive content categories:
        r"play[- ]to[- ]earn",
        r"crypto (?:project|points|rewards)",
        r"\bnft(?:s)?\b",
        r"\brug pull\b",
        r"promoting rwt",
        r"real world trading",
        r"data farming",
    ]),
    ("not_interested", [
        r"not interested in hosting",
        r"won'?t be hosting",
        r"will not (?:host|accept)",
        r"don'?t want to host",
    ]),
    ("takeover", [
        r"plugin[- ]takeover[- ]policy",
        r"runelite/wiki/plugin-takeover",
        r"looking to collaborate with you on your plugin",
        r"existing repo .+ instead",
        r"(?:^|\s)takeover(?:\s|$)",
    ]),
    ("build", [
        r"doesn'?t build",
        r"fail(?:s|ed) to build",
        r"build (?:is )?(?:still |currently )?(?:broken|failing)",
        r"unresolved build errors?",
        r"compilation (?:error|fail)",
        r"update your commit hash",
        r"\bcommit hash\b.*\b(?:wrong|invalid|update)",
        r"plugin fails to build",
        r"this submission is still broken",
        r"ci build failed",
        r"branch conflicts",
        r"repository is not public",
        r"build (?:errors|failures)",
        # Newly-added third pass:
        r"does not (?:currently |yet )?build",
        r"plugin uses terminally deprecated apis",
        r"deprecated apis?",
        r"needs (?:a )?rebase",
        r"still has conflicts",
        r"branch.+conflicts",
        r"actions/runs/\d+",  # CI failure URL
    ]),
    ("invalid", [
        r"submission is (?:invalid|empty)",
        r"follow the steps in the readme",
        r"please follow the readme",
        r"this submission is still invalid",
        r"empty (?:pr|submission)",
        r"didn'?t submit the plug-?in properly",
    ]),
    ("code_quality", [
        # New bucket: maintainer asked for code change, author didn't address
        r"closing because (?:the )?above (?:has not been |hasn'?t been |is )(?:un)?addressed",
        r"closing because above (?:is )?unaddressed",
        r"closing because the above wasn'?t addressed",
        r"comments have not been resolved",
        r"please remove (?:the )?changes",
        r"^you should check (?:whether|that)",
        r"on the client thread",
    ]),
    ("procedural", [
        r"don'?t (?:open|make) new prs",
        r"please do not (?:open |make )?new prs",
        r"push (?:any )?(?:changes|updates) to your (?:existing |current )?(?:pr|branch)",
        r"keep pushing to this branch",
        r"close (?:this )?in favor of",
        r"superseded by #?\d+",
        r"replaced by #?\d+",
        r"merged in #?\d+",
        r"merged by the original author",
        r"closing this. ?(?:i|we) ",
        r"rebase your plugin-hub branch",
        r"need to fix the branch conflicts",
    ]),
]

COMPILED = [
    (label, [re.compile(p, re.IGNORECASE) for p in patterns])
    for label, patterns in PATTERNS
]


def is_maintainer(login):
    return login and login in KNOWN_MAINTAINERS


def categorize(pr):
    comments = pr.get("comments", {}).get("nodes", [])
    human = [
        c for c in comments
        if c.get("author") and c["author"].get("login") not in BOT_ACCOUNTS
    ]
    if not human:
        return "no_signal", None, None

    maintainer_comments = [
        c for c in human if is_maintainer((c.get("author") or {}).get("login"))
    ]
    if not maintainer_comments:
        # Try classifying author-only comments — sometimes authors self-close
        # citing maintainer feedback they got elsewhere.
        for label, patterns in COMPILED:
            for c in human:
                body = c["body"]
                for pat in patterns:
                    if pat.search(body):
                        return label, "self-acknowledged", body[:200]
        return "no_maintainer", None, None

    for label, patterns in COMPILED:
        for c in maintainer_comments:
            body = c["body"]
            for pat in patterns:
                if pat.search(body):
                    login = (c.get("author") or {}).get("login")
                    return label, login, body[:200]

    return "unclear", None, None


def changed_plugin_slug(pr):
    """Try to extract the plugin slug from changed file paths."""
    files = (pr.get("files") or {}).get("nodes") or []
    for f in files:
        path = f.get("path", "")
        m = re.match(r"plugins/([^/]+)\.(?:properties|yaml|yml)$", path)
        if m:
            return m.group(1)
    return None


def main():
    prs = [json.loads(line) for line in open(IN_PATH) if line.strip()]
    bucket_counts = Counter()
    examples = {}

    with open(OUT_PATH, "w") as out:
        for pr in prs:
            label, by, snippet = categorize(pr)
            bucket_counts[label] += 1
            slug = changed_plugin_slug(pr)
            record = {
                "number": pr["number"],
                "title": pr["title"],
                "author": (pr.get("author") or {}).get("login"),
                "closedAt": pr.get("closedAt"),
                "candidate_slug": slug,
                "bucket": label,
                "matched_by": by,
                "matched_snippet": snippet,
            }
            out.write(json.dumps(record) + "\n")
            if label not in examples and snippet:
                examples[label] = (pr["number"], pr["title"], snippet)

    total = len(prs)
    print(f"Total: {total}")
    print()
    print("Buckets:")
    for k, v in bucket_counts.most_common():
        pct = v / total * 100
        print(f"  {k:<15} {v:>4}  ({pct:.1f}%)")

    print()
    print("Example match per bucket:")
    for label, (n, title, snippet) in examples.items():
        print(f"  [{label}] #{n} — {title}")
        print(f"    \"{snippet[:160]}\"")
        print()


if __name__ == "__main__":
    main()
