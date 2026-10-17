# Publication of current release evidence

On 2026-10-17 the user explicitly requested deletion of old outputs and commit/push of current outputs.

Published sets:

- `../release-F-0a6746187e82-20261016T090229Z/`: the immutable reviewed release package and pre-D3 checks.
- `../D3-0a6746187e82-20261016T093436Z/`: D3 evidence, exports, screenshots and test harnesses.
- This directory: post-D3 checks, publication audit and cleanup record.

The image TAR is stored with Git LFS. Install Git LFS and run `git lfs pull` after cloning to obtain
the archive bytes; the existing package `SHA256SUMS` applies to the downloaded archive, not its Git pointer.
Evidence paths use `-text` attributes to preserve original bytes and sealed checksums across platforms.
Python caches are excluded. Relevant test logs are intentionally included despite the global log ignore rule.

Obsolete output directories removed locally: candidates `4639c2bfd756`, `5680ab506697`, `6a0d1975d6e9`,
`965a9eca42ef`, and `release-restart-fix-20261016T082635Z`. The immutable pre-D3 `REPORT.md` and harness
may still contain historical references to those removed directories. Those references are historical;
the sealed evidence is not rewritten to remove them. The retained final package is `0a67461` only.

Original historical fields such as `D3: NOT_RUN`, `pushed: false`, absolute test-machine paths and recorded
timestamps describe their original capture time. Refer to the final D3 report and post-D3 follow-up report
for later results. Publishing evidence does not rebuild, deploy, or resolve the original artifact's font CSP finding.
