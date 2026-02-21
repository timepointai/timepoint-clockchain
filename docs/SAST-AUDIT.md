# SAST Audit Report

**Date:** 2026-02-21
**Branch:** `security/sast-audit`
**Tools:** Bandit 1.9.3, Semgrep 1.152.0

## Scan Results

### Semgrep (291 rules, 19 files)

**0 findings.** No SQL injection, XSS, SSRF, or logic flaws detected.

### Bandit (19 files)

**Initial scan: 2 findings.** Both remediated.

| ID | Severity | File | Issue | Fix |
|----|----------|------|-------|-----|
| B311 | LOW | `app/core/graph.py:135` | `random.choice()` not suitable for security | Replaced with `secrets.choice()` |
| B110 | LOW | `app/core/jobs.py:222` | Bare `except: pass` swallows errors | Replaced with `logger.debug()` |

**Post-fix scan: 0 findings.** Bandit exit code 0.

### Manual Review (not scanner-detected)

| Severity | File | Issue | Fix |
|----------|------|-------|-----|
| MEDIUM | `app/core/auth.py:12` | Service key comparison uses `!=` (timing-attack vulnerable) | Replaced with `hmac.compare_digest()` |

## Summary

- **Semgrep**: Clean
- **Bandit**: Clean (2 low-severity findings fixed)
- **Manual**: 1 medium-severity timing-attack vector fixed
- **Tests**: 60/60 passing after all fixes
