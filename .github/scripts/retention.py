#!/usr/bin/env python3
"""
Delete the versions of ghcr container packages that are older than a number of days.

Usage: retention.py <owner> <days> <package> [<package> ...]
  e.g. retention.py molior-dbs 14 dev/molior dev/aptly dev/charts/molior

Environment: GITHUB_TOKEN (packages: write), GITHUB_API_URL (default https://api.github.com),
GITHUB_STEP_SUMMARY (optional, the result is appended as markdown).

The newest version of a package is never deleted. Errors are printed as warnings, the exit code is always 0:
the retention must not fail the job that pushed the images.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


def api(method, path):
    url = os.environ.get("GITHUB_API_URL", "https://api.github.com") + path
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": "Bearer " + os.environ.get("GITHUB_TOKEN", ""),
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return json.loads(body) if body else None


def owner_path(owner):
    """/orgs/<owner> or /users/<owner>, the packages API differs for organizations and users"""
    kind = api("GET", "/users/" + urllib.parse.quote(owner))["type"]
    return ("/orgs/" if kind == "Organization" else "/users/") + urllib.parse.quote(owner)


def versions(base, package):
    """all versions of a package, newest first"""
    result = []
    page = 1
    while True:
        batch = api("GET", "%s/packages/container/%s/versions?per_page=100&page=%d"
                    % (base, urllib.parse.quote(package, safe=""), page))
        result.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return sorted(result, key=lambda v: v["created_at"], reverse=True)


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def tags(version):
    return version.get("metadata", {}).get("container", {}).get("tags", [])


def retention(owner, days, packages):
    lines = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        base = owner_path(owner)
    except Exception as exc:
        print("::warning title=Retention::owner %s: %s" % (owner, exc))
        return ["* owner `%s`: %s" % (owner, exc)]
    for package in packages:
        try:
            found = versions(base, package)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                lines.append("* `%s`: not found" % package)
                continue
            print("::warning title=Retention::%s: %s" % (package, exc))
            lines.append("* `%s`: %s" % (package, exc))
            continue
        except Exception as exc:
            print("::warning title=Retention::%s: %s" % (package, exc))
            lines.append("* `%s`: %s" % (package, exc))
            continue
        old = [v for v in found[1:] if parse_time(v["created_at"]) < cutoff]
        deleted = 0
        for v in old:
            try:
                api("DELETE", "%s/packages/container/%s/versions/%d"
                    % (base, urllib.parse.quote(package, safe=""), v["id"]))
                deleted += 1
                print("deleted %s %s (%s, %s)" % (package, v["id"], ",".join(tags(v)) or "untagged", v["created_at"]))
            except Exception as exc:
                print("::warning title=Retention::%s version %s: %s" % (package, v["id"], exc))
        lines.append("* `%s`: %d versions, %d older than %d days, %d deleted"
                     % (package, len(found), len(old), days, deleted))
    return lines


def main(argv):
    if len(argv) < 4:
        print(__doc__.strip())
        return 0
    owner, days, packages = argv[1], int(argv[2]), argv[3:]
    lines = retention(owner, days, packages)
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("### Retention (%d days)\n\n%s\n\n" % (days, "\n".join(lines)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
