#!/usr/bin/env python3
"""Fetch all closed-unmerged plugin-hub PRs with comments and changed files.

Output: corpus/plugin_hub_rejected_prs.jsonl, one PR per line.
Each line has: number, title, createdAt, closedAt, author, comments, files.

Uses `gh api graphql` so this inherits the user's gh auth.
"""

import json
import subprocess
import sys
from pathlib import Path

PRISM_ROOT = Path(__file__).parent.parent
OUT_PATH = PRISM_ROOT / "corpus" / "plugin_hub_rejected_prs.jsonl"

QUERY = """
query($cursor: String) {
  search(
    query: "repo:runelite/plugin-hub is:pr is:closed is:unmerged"
    type: ISSUE
    first: 100
    after: $cursor
  ) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number
        title
        createdAt
        closedAt
        author { login }
        comments(last: 8) {
          nodes { author { login } body createdAt }
        }
        files(first: 10) {
          nodes { path }
        }
      }
    }
  }
}
"""


def gh_graphql(query, variables):
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        if v is None:
            cmd += ["-F", f"{k}=null"]
        else:
            cmd += ["-f", f"{k}={v}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    cursor = None
    page = 0
    total = 0
    with open(OUT_PATH, "w") as out:
        while True:
            page += 1
            variables = {"cursor": cursor} if cursor else {}
            try:
                data = gh_graphql(QUERY, variables)
            except subprocess.CalledProcessError as e:
                print(f"GraphQL error on page {page}: {e.stderr}", file=sys.stderr)
                sys.exit(1)

            search = data["data"]["search"]
            nodes = search["nodes"]
            for pr in nodes:
                if pr is None:
                    continue
                out.write(json.dumps(pr) + "\n")
            total += len(nodes)
            print(
                f"page {page}: {len(nodes)} rows (total {total}) "
                f"hasNext={search['pageInfo']['hasNextPage']}",
                file=sys.stderr,
            )
            if not search["pageInfo"]["hasNextPage"]:
                break
            cursor = search["pageInfo"]["endCursor"]
            if page >= 20:
                print("Hit page cap of 20", file=sys.stderr)
                break

    print(f"Wrote {total} PRs to {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
