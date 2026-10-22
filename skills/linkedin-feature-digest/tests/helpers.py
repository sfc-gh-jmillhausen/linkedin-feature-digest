"""Shared test setup: synthetic config and import path. No mail, network, or connectors."""

import os
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
FIXTURES = SKILL / "fixtures"
OWNER = "digest-owner@example.com"

os.environ["LINKEDIN_DIGEST_CONFIG"] = str(FIXTURES / "test-config.json")
sys.path.insert(0, str(SKILL / "scripts"))
