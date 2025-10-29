## Spec: **vllm-flake-checker**

We’re building a small Python CLI script that searches recent Buildkite builds for log patterns (flakes) in a given pipeline.

You’ll be given an example script (`poc-flake-check.py`) to reference for API usage and structure — use that as inspiration, but this spec defines what the final tool should do.

---

### 🎯 Goal

Scan recent Buildkite builds in the `vllm/ci` pipeline, find jobs that match a given step substring (e.g. `"v1 Test others"`), and report if specific text or regex patterns appear in their logs.
Output a simple summary and list of matches (build URLs + snippets).

---

### 🧰 Environment Setup

We use a `.env` file that can be sourced before running:

```bash
export BK_TOKEN=bkua_28a919e0....f
export BK_ORG=vllm
export BK_PIPELINE=ci
export BK_BRANCH_REGEX='^pull/|^pr/'
export BK_STEP_SUBSTR='v1 Test others'
export BK_MAX_BUILDS=200
```

This allows the script to be run easily with:

```bash
source .env
python3 flake-checker.py
```

---

### 🧠 Inputs

* **Environment variables (preferred)**, with fallbacks hardcoded to reasonable defaults.
* Optional CLI flags to override them (use `argparse`).

| Variable           | Description                                | Example / Default |       |
| ------------------ | ------------------------------------------ | ----------------- | ----- |
| `BK_TOKEN`         | Buildkite API token (read access only)     | required          |       |
| `BK_ORG`           | Org slug                                   | `vllm`            |       |
| `BK_PIPELINE`      | Pipeline slug                              | `ci`              |       |
| `BK_BRANCH_REGEX`  | Regex to filter branches                   | `^pull/           | ^pr/` |
| `BK_STEP_SUBSTR`   | Substring of the job label/name            | `v1 Test others`  |       |
| `BK_MAX_BUILDS`    | Max builds to scan                         | `200`             |       |
| `BK_PATTERNS_FILE` | Optional file with patterns (one per line) | `patterns.txt`    |       |

---

### 🔍 Behavior

1. List up to `BK_MAX_BUILDS` recent builds from:

   ```
   GET /v2/organizations/{BK_ORG}/pipelines/{BK_PIPELINE}/builds
   ```

   Apply the branch regex filter client-side.

2. For each build:

   * Fetch its jobs:

     ```
     GET /v2/organizations/{BK_ORG}/pipelines/{BK_PIPELINE}/builds/{number}/jobs
     ```
   * Include only jobs whose `label` or `name` contains the `BK_STEP_SUBSTR`.

3. For each matching job:

   * Download its log:

     ```
     GET .../jobs/{job_id}/log?format=txt
     ```
   * Search for each pattern (regex or literal, depending on a `--regex` flag).

4. If a pattern is found:

   * Record:

     ```
     build number, branch, state, step label, pattern, snippet, web_url
     ```

---

### 📄 Output

Print a short summary + details:

```
Found 3 matching failures:

- #2334 [pull/555] v1 Test others — https://buildkite.com/vllm/ci/builds/2334
  Pattern: get_num_new_matched_tokens 96
  Snippet: ...At index 2 diff: 'get_num_new_matched_tokens 96' != 'build_connector_meta'...

- #2321 [pull/547] v1 Test others — https://buildkite.com/vllm/ci/builds/2321
  Pattern: build_connector_meta
  Snippet: ...FAILED v1/kv_connector/unit/test_multi_connector.py::test_multi_shared_storage_connector_consistency...
```

Add a summary footer:

```
Scanned 200 builds, 25 jobs, 3 matches found.
```

Support `--json` for machine-readable output.

---

### 💡 Example patterns

These can be embedded or loaded from `patterns.txt`:

```python
MATCH_PATTERNS = [
    r"FAILED .*::test_multi_shared_storage_connector_consistency\b",
    r"At index 2 diff: 'get_num_new_matched_tokens 96' != 'build_connector_meta'",
    r"get_num_new_matched_tokens 96"
]
```

---

### ⚙️ Implementation details

* Use `requests` and `re` only (no extra deps).
* Retry on HTTP 429 or 5xx with small backoff.
* Timeout per request: 30s.
* Gracefully skip missing logs (404).
* Output matches immediately or after collecting all.
* Exit code `0` on success, `>0` on error.
* Limit memory use by discarding logs once searched.

---

### ✅ Acceptance criteria

* Works out-of-the-box when `.env` is sourced.
* Prints clear human-readable report.
* Runs under 2 minutes scanning 200 builds.
* Detects flakes appearing in multiple PRs.
* `--json` flag produces valid JSON array of match objects.
