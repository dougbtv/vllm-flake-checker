# vllm-flake-checker

A Python CLI tool to scan recent Buildkite builds for log patterns (flakes) in the vllm CI pipeline.

## Features

- Scans recent builds from Buildkite API
- Filters builds by branch regex (e.g., only PRs)
- Searches specific job steps for pattern matches
- Supports both literal and regex pattern matching
- Configurable via environment variables or CLI flags
- Human-readable and JSON output formats
- Retry logic for rate limits and transient errors
- Memory-efficient log processing

## Requirements

- Python 3.6+
- `requests` library

Install dependencies:

```bash
pip install requests
```

## Quick Start

1. Set up your `.env` file with your Buildkite API token:

```bash
cp .env.example .env
# Edit .env and add your BK_TOKEN
```

2. Run the scanner:

```bash
source .env
python3 flake-checker.py
```

Or directly:

```bash
./flake-checker.py
```

## Configuration

### Environment Variables

The tool reads configuration from environment variables (can be set in `.env`):

| Variable           | Description                              | Default           |
| ------------------ | ---------------------------------------- | ----------------- |
| `BK_TOKEN`         | Buildkite API token (required)           | -                 |
| `BK_ORG`           | Organization slug                        | `vllm`            |
| `BK_PIPELINE`      | Pipeline slug                            | `ci`              |
| `BK_BRANCH_REGEX`  | Regex to filter branches                 | `^pull/\|^pr/`    |
| `BK_STEP_SUBSTR`   | Substring of job label to match          | `v1 Test others`  |
| `BK_MAX_BUILDS`    | Maximum builds to scan                   | `200`             |
| `BK_PATTERNS_FILE` | Path to file with patterns (one per line)| -                 |

### CLI Arguments

All environment variables can be overridden via command-line flags:

```bash
./flake-checker.py --help
```

Options:
- `--token TOKEN`: Buildkite API token
- `--org ORG`: Organization slug
- `--pipeline PIPELINE`: Pipeline slug
- `--branch-regex REGEX`: Branch filter regex
- `--step-substr TEXT`: Job step substring to match
- `--max-builds N`: Maximum builds to scan
- `--patterns-file FILE`: File with patterns to search
- `--regex`: Treat patterns as regex (default: literal search)
- `--json`: Output results as JSON

## Usage Examples

### Basic scan with environment variables:

```bash
source .env
./flake-checker.py
```

### Scan with custom settings:

```bash
./flake-checker.py --max-builds 50 --step-substr "Test GPU"
```

### Use patterns from file:

```bash
./flake-checker.py --patterns-file patterns.txt --regex
```

### JSON output for automation:

```bash
./flake-checker.py --json > results.json
```

### Scan specific branch pattern:

```bash
./flake-checker.py --branch-regex "^main$"
```

## Patterns File

Create a `patterns.txt` file with one pattern per line:

```
# Lines starting with # are ignored
FAILED .*::test_multi_shared_storage_connector_consistency
get_num_new_matched_tokens 96
At index 2 diff:
```

Use `--regex` flag to enable regex matching. Without it, patterns are treated as literal strings.

## Output Format

### Human-readable (default):

```
Found 3 matching failure(s):

- #2334 [pull/555] v1 Test others — https://buildkite.com/vllm/ci/builds/2334
  Pattern: get_num_new_matched_tokens 96
  Snippet: ...At index 2 diff: 'get_num_new_matched_tokens 96' != 'build_connector_meta'...

Scanned 200 builds, 25 jobs, 3 matches found.
```

### JSON output (--json):

```json
{
  "summary": {
    "builds_scanned": 200,
    "jobs_scanned": 25,
    "matches_found": 3
  },
  "matches": [
    {
      "build_number": 2334,
      "branch": "pull/555",
      "state": "failed",
      "created_at": "2025-01-15T10:30:00Z",
      "step_label": "v1 Test others",
      "web_url": "https://buildkite.com/vllm/ci/builds/2334",
      "pattern": "get_num_new_matched_tokens 96",
      "snippet": "...log context..."
    }
  ]
}
```

## Performance

- Scans ~200 builds in under 2 minutes (depending on network and API limits)
- Memory-efficient: logs are discarded immediately after processing
- Automatic retry with exponential backoff for rate limits
- Configurable timeouts and retry logic

## Error Handling

- Missing or invalid API token: exits with error message
- Rate limit (429): automatic retry with backoff
- Server errors (5xx): automatic retry
- Missing logs (404): gracefully skipped
- Network timeouts: configurable with retries

## Exit Codes

- `0`: Success (regardless of matches found)
- `1`: Error during execution
- `130`: Interrupted by user (Ctrl+C)

## Getting a Buildkite API Token

1. Go to https://buildkite.com/user/api-access-tokens
2. Click "New API Access Token"
3. Select scopes: `read_builds`, `read_pipelines`, `read_organizations`
4. Copy the token and add to `.env`

## License

See project root for license information.
