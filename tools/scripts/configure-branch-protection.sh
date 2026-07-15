#!/usr/bin/env bash
# Applies the branch protection ruleset declared in .github/settings.yml to
# `main` via the GitHub CLI/API. This is the authoritative fallback when the
# Probot Settings App is not installed on the GitHub org.
#
# Satisfies US-01 acceptance criterion: "branch protection blocks direct
# pushes to main" (Engineering Backlog v1.0 §4).
#
# Requires: `gh` CLI authenticated with repo admin scope.
# Usage: OWNER=my-org REPO=emg-platform ./tools/scripts/configure-branch-protection.sh
set -euo pipefail

OWNER="${OWNER:?Set OWNER=<github-org>}"
REPO="${REPO:?Set REPO=<repo-name>}"
BRANCH="main"

echo "==> Applying branch protection to $OWNER/$REPO@$BRANCH"

gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/$OWNER/$REPO/branches/$BRANCH/protection" \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=lint-and-static-analysis" \
  -f "required_status_checks[contexts][]=unit-tests" \
  -f "required_status_checks[contexts][]=build" \
  -f "required_status_checks[contexts][]=security-scan" \
  -f "required_status_checks[contexts][]=integration-tests" \
  -F "enforce_admins=true" \
  -f "required_pull_request_reviews[required_approving_review_count]=1" \
  -f "required_pull_request_reviews[dismiss_stale_reviews]=true" \
  -F "required_pull_request_reviews[require_code_owner_reviews]=true" \
  -F "restrictions=null" \
  -F "required_linear_history=true" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false"

echo "==> Branch protection applied. Verify at https://github.com/$OWNER/$REPO/settings/branches"
