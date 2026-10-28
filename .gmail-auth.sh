#!/bin/bash
# Re-authorize the Gmail OTP reader token (~/.career_agent/gmail_token.json).
# Saves to HOME, so every server instance picks it up automatically.
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD/src"
exec /usr/bin/env python3 -m career_agent.integrations.gmail_otp authorize
