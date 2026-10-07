#!/usr/bin/env bash
# Push captured frames (git-ignored) of some scenes to their own branch, so parallel
# sessions can hand footage over without putting binaries in the code branch.
#   scripts/push-frames.sh <branch> <scene-id> [<scene-id>...]
# The branch holds only promo/video/public/capture/<scene-id>/ and is replaced on each run.
set -euo pipefail
cd "$(dirname "$0")/.."
branch=$1
shift
repo=$(git rev-parse --show-toplevel)
tmp=$(mktemp -d)
git -C "$repo" worktree add --detach "$tmp" >/dev/null 2>&1
(
  cd "$tmp"
  git checkout -q --orphan "$branch"
  git rm -rq --cached . >/dev/null 2>&1 || true
  find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  mkdir -p promo/video/public/capture
  for s in "$@"; do cp -a "$repo/promo/video/public/capture/$s" promo/video/public/capture/; done
  git add -f promo/video/public/capture
  git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -qm "Captured frames: $*"
  for i in 1 2 3 4; do git push -q -f origin "HEAD:refs/heads/$branch" && break; sleep $((2 ** i)); done
)
git -C "$repo" worktree remove --force "$tmp"
echo "frames for $* -> $branch"
