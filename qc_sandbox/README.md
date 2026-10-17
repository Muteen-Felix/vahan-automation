# Deliberate QC worker fixtures

DO NOT MERGE. auth/status returns HTTP 500 for Schemathesis; an uncalled eval helper triggers Semgrep; a synthetic unissued token triggers Gitleaks; requests 2.19.1 in this directory triggers Trivy. This requirements file is not installed by the application. Existing baseline findings must be distinguished from these new findings. No LLM calls requested.
