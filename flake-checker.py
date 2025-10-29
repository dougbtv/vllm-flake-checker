#!/usr/bin/env python3
"""
vllm-flake-checker: Scan Buildkite builds for log patterns (flakes).
"""

import os
import sys
import re
import json
import time
import argparse
from typing import List, Dict, Optional, Tuple
import requests
from urllib.parse import urlencode


# Default patterns to search for
DEFAULT_PATTERNS = [
    r"FAILED .*::test_multi_shared_storage_connector_consistency\b",
    r"At index 2 diff: 'get_num_new_matched_tokens 96' != 'build_connector_meta'",
    r"get_num_new_matched_tokens 96"
]


class FlakeChecker:
    def __init__(self, args):
        self.token = args.token
        self.org = args.org
        self.pipeline = args.pipeline
        self.branch_regex = args.branch_regex
        self.step_substr = args.step_substr
        self.max_builds = args.max_builds
        self.use_regex = args.regex
        self.json_output = args.json
        self.patterns = self._load_patterns(args.patterns_file)

        self.api_base = "https://api.buildkite.com/v2"
        self.headers = {"Authorization": f"Bearer {self.token}"}

        # Statistics
        self.builds_scanned = 0
        self.jobs_scanned = 0
        self.matches = []

    def _load_patterns(self, patterns_file: Optional[str]) -> List[str]:
        """Load patterns from file or use defaults."""
        if patterns_file and os.path.exists(patterns_file):
            with open(patterns_file, 'r') as f:
                patterns = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            return patterns if patterns else DEFAULT_PATTERNS
        return DEFAULT_PATTERNS

    def _make_request(self, url: str, timeout: int = 30, max_retries: int = 3) -> requests.Response:
        """Make HTTP request with retry logic for 429/5xx errors."""
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=self.headers, timeout=timeout)

                # Retry on rate limit or server errors
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < max_retries - 1:
                        # Longer wait for rate limits
                        wait_time = (2 ** attempt) * (5 if response.status_code == 429 else 1)
                        print(f"Rate limit hit, waiting {wait_time}s...", file=sys.stderr)
                        time.sleep(wait_time)
                        continue

                response.raise_for_status()
                return response

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    continue
                raise
            except requests.exceptions.RequestException:
                if attempt < max_retries - 1 and attempt > 0:
                    time.sleep(1)
                    continue
                raise

        raise Exception(f"Failed after {max_retries} attempts")

    def get_builds(self, page: int = 1, per_page: int = 50) -> Tuple[List[Dict], Optional[str]]:
        """Fetch builds from Buildkite API (includes jobs in response)."""
        params = {"page": page, "per_page": per_page, "include_retried_jobs": "true"}
        url = f"{self.api_base}/organizations/{self.org}/pipelines/{self.pipeline}/builds?{urlencode(params)}"

        response = self._make_request(url)
        next_url = response.links.get("next", {}).get("url")

        return response.json(), next_url

    def get_job_log(self, build_number: int, job_id: str) -> Optional[str]:
        """Fetch log for a specific job. Returns None if log not available."""
        url = f"{self.api_base}/organizations/{self.org}/pipelines/{self.pipeline}/builds/{build_number}/jobs/{job_id}/log?format=txt"

        try:
            response = self._make_request(url, timeout=60)
            # Add small delay to avoid rate limiting
            time.sleep(0.3)
            return response.text
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None  # Log not available
            raise

    def find_pattern_matches(self, text: str) -> List[Tuple[str, str]]:
        """Find all matching patterns in text. Returns list of (pattern, snippet) tuples."""
        matches = []

        for pattern in self.patterns:
            try:
                if self.use_regex:
                    match = re.search(pattern, text, re.MULTILINE)
                else:
                    # Literal search - escape special regex chars
                    escaped = re.escape(pattern)
                    match = re.search(escaped, text, re.MULTILINE)

                if match:
                    # Extract snippet with context
                    start = max(0, match.start() - 200)
                    end = min(len(text), match.end() + 200)
                    snippet = text[start:end].strip()

                    # Clean up snippet - remove excessive whitespace
                    snippet = re.sub(r'\n\s*\n+', '\n', snippet)
                    lines = snippet.splitlines()
                    if len(lines) > 10:
                        snippet = '\n'.join(lines[:10]) + '\n...'

                    matches.append((pattern, snippet))
            except re.error as e:
                print(f"Warning: Invalid regex pattern '{pattern}': {e}", file=sys.stderr)
                continue

        return matches

    def scan_builds(self):
        """Main scanning logic."""
        if not self.token or self.token == "<PUT_YOUR_TOKEN_HERE>":
            print("Error: BK_TOKEN not set. Please set the Buildkite API token.", file=sys.stderr)
            sys.exit(1)

        page = 1
        fetched = 0

        try:
            print(f"Scanning up to {self.max_builds} builds...", file=sys.stderr)

            while fetched < self.max_builds:
                builds, next_url = self.get_builds(page=page, per_page=50)

                if not builds:
                    break

                for build in builds:
                    if fetched >= self.max_builds:
                        break

                    fetched += 1
                    branch = build.get("branch", "")

                    # Filter by branch regex
                    if self.branch_regex and not re.search(self.branch_regex, branch):
                        continue

                    self.builds_scanned += 1
                    build_number = build["number"]
                    web_url = build.get("web_url", "")
                    state = build.get("state", "unknown")
                    created_at = build.get("created_at", "")

                    print(f"Build #{build_number} [{branch}] - {state}", file=sys.stderr)

                    # Get jobs from build object (already included in API response)
                    jobs = build.get("jobs", [])

                    if not jobs:
                        continue

                    # Filter jobs by step substring
                    for job in jobs:
                        label = job.get("label") or job.get("name") or ""

                        if self.step_substr.lower() not in label.lower():
                            continue

                        self.jobs_scanned += 1
                        job_id = job["id"]
                        job_state = job.get("state", "unknown")

                        print(f"  Checking: {label} ({job_state})", file=sys.stderr)

                        # Get job log
                        try:
                            log = self.get_job_log(build_number, job_id)
                        except Exception as e:
                            print(f"  Warning: Failed to fetch log: {e}", file=sys.stderr)
                            continue

                        if not log:
                            continue

                        # Search for patterns
                        pattern_matches = self.find_pattern_matches(log)

                        # Clear log from memory immediately
                        del log

                        # Record matches
                        if pattern_matches:
                            print(f"  ✓ MATCH FOUND in {label}!", file=sys.stderr)

                        for pattern, snippet in pattern_matches:
                            self.matches.append({
                                "build_number": build_number,
                                "branch": branch,
                                "state": state,
                                "created_at": created_at,
                                "step_label": label,
                                "web_url": web_url,
                                "pattern": pattern,
                                "snippet": snippet
                            })

                if not next_url:
                    break

                page += 1

        except KeyboardInterrupt:
            print("\nScan interrupted by user.", file=sys.stderr)
            sys.exit(130)
        except Exception as e:
            print(f"Error during scan: {e}", file=sys.stderr)
            sys.exit(1)

    def output_results(self):
        """Output results in requested format."""
        if self.json_output:
            # JSON output
            output = {
                "summary": {
                    "builds_scanned": self.builds_scanned,
                    "jobs_scanned": self.jobs_scanned,
                    "matches_found": len(self.matches)
                },
                "matches": self.matches
            }
            print(json.dumps(output, indent=2))
        else:
            # Human-readable output
            if not self.matches:
                print("\nNo matching patterns found in the scanned builds.")
            else:
                print(f"\nFound {len(self.matches)} matching failure(s):\n")

                for match in self.matches:
                    print(f"- #{match['build_number']} [{match['branch']}] {match['step_label']} — {match['web_url']}")
                    print(f"  Pattern: {match['pattern']}")
                    print(f"  Snippet: {match['snippet'][:150]}...")
                    print()

            print(f"Scanned {self.builds_scanned} builds, {self.jobs_scanned} jobs, {len(self.matches)} matches found.")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Scan Buildkite builds for log patterns (flakes)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--token",
        default=os.getenv("BK_TOKEN", ""),
        help="Buildkite API token (env: BK_TOKEN)"
    )
    parser.add_argument(
        "--org",
        default=os.getenv("BK_ORG", "vllm"),
        help="Organization slug (env: BK_ORG, default: vllm)"
    )
    parser.add_argument(
        "--pipeline",
        default=os.getenv("BK_PIPELINE", "ci"),
        help="Pipeline slug (env: BK_PIPELINE, default: ci)"
    )
    parser.add_argument(
        "--branch-regex",
        default=os.getenv("BK_BRANCH_REGEX", r"^pull/|^pr/"),
        help="Regex to filter branches (env: BK_BRANCH_REGEX, default: ^pull/|^pr/)"
    )
    parser.add_argument(
        "--step-substr",
        default=os.getenv("BK_STEP_SUBSTR", "v1 Test others"),
        help="Substring of job label to match (env: BK_STEP_SUBSTR, default: 'v1 Test others')"
    )
    parser.add_argument(
        "--max-builds",
        type=int,
        default=int(os.getenv("BK_MAX_BUILDS", "200")),
        help="Maximum builds to scan (env: BK_MAX_BUILDS, default: 200)"
    )
    parser.add_argument(
        "--patterns-file",
        default=os.getenv("BK_PATTERNS_FILE"),
        help="File with patterns to search (one per line) (env: BK_PATTERNS_FILE)"
    )
    parser.add_argument(
        "--regex",
        action="store_true",
        help="Treat patterns as regex (default: literal search)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    checker = FlakeChecker(args)
    checker.scan_builds()
    checker.output_results()

    # Exit with error code if no matches found
    sys.exit(0 if checker.matches else 0)  # Always exit 0 on success per spec


if __name__ == "__main__":
    main()
