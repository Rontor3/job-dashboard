#!/bin/bash
# Run the Job Dashboard API server (port 8001) from THIS worktree's code.
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD/src"
exec /usr/bin/env python3 -m uvicorn job_dashboard.api.serve:app --port 8001
