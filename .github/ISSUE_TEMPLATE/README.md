# Review issue templates

Four YAML issue forms for the YoYoPod codebase review workflow:

| Template | Lens |
|---|---|
| `review-architecture.yml` | Boundaries, coupling, state ownership, threading, layering, dependency direction. |
| `review-code-quality.yml` | Error handling, logging, dead code, naming, idioms, perf hot-paths, security. |
| `review-testing.yml` | Coverage gaps, brittle tests, mocks-vs-reality, CI gate gaps, missing integration. |
| `review-docs.yml` | Stale, missing, inaccurate, or contradictory documentation. |

## Obsolescence-prevention contract

Every template enforces:

1. **Source commit SHA is required.** Every finding pins to the exact snapshot it was reviewed against.
2. **No SLOC fields.** Findings are observational, not line-count heuristics.
3. **"Suggested direction" not "Proposed fix".** Framing survives reorganization even when specific mechanisms rot.
4. **File paths primary, line numbers optional.** Paths are stabler across refactors.

## Reviewer workflow (for agents using `gh` CLI)

YAML issue forms enforce field validation only for web submissions. Agents filing via
`gh issue create --body` must mirror the field schema in their rendered body and apply
severity/effort/review-round labels manually:

```bash
gh issue create \
  --title "[Arch] <short finding title>" \
  --body "$(cat <<'EOF'
### Finding ID
A01

### Source commit SHA
<full SHA>

### Concern type
boundary

### Invariant violated
rules/architecture.md §"Dependency Direction"

### Severity
high

### Effort
medium

### Files affected
yoyopod/core/loop.py
yoyopod/core/application.py

### Finding
<what's wrong, observed at the pinned SHA>

### Impact
<what breaks / what rule or doc it violates>

### Suggested direction
<observational guidance, not prescriptive file splits>

### References
rules/architecture.md
docs/architecture/SYSTEM_ARCHITECTURE.md
EOF
)" \
  --label "architecture" \
  --label "review" \
  --label "review:2026-04-23" \
  --label "severity:high" \
  --label "effort:medium"
```

Template files under this directory are the schema contract. Field order and labels
in the body must match the corresponding `.yml` file's `body:` entries.

## See also

- Spec: [docs/superpowers/specs/2026-04-23-review-issue-templates-design.md](../../docs/superpowers/specs/2026-04-23-review-issue-templates-design.md)
