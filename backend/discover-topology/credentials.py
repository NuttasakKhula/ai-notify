"""
credentials.py
--------------
Loads SSH credential sets from a .env file. NOTHING is hardcoded here.

Credentials are numbered so the order of attempts is explicit:
production first (NET_CRED_1_*), lab/fallback later (NET_CRED_2_*, ...).

.env format:
    NET_CRED_1_USERNAME=REPLACE_WITH_SSH_USER
    NET_CRED_1_PASSWORD=...
    NET_CRED_1_SECRET=...          # optional enable secret
    NET_CRED_1_LABEL=production    # optional, for logs only

    NET_CRED_2_USERNAME=REPLACE_WITH_SECOND_SSH_USER
    NET_CRED_2_PASSWORD=REPLACE_WITH_SECOND_SSH_PASSWORD
    NET_CRED_2_LABEL=lab
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

log = logging.getLogger("discovery.credentials")

MAX_CRED_SETS = 10  # how many NET_CRED_N_* blocks we look for


@dataclass
class Credential:
    """One SSH credential set. __repr__ never leaks the password."""

    username: str
    password: str = field(repr=False)
    secret: str = field(default="", repr=False)
    label: str = "unnamed"

    def as_netmiko_kwargs(self) -> dict:
        return {
            "username": self.username,
            "password": self.password,
            "secret": self.secret or self.password,
            # เพิ่มคำสั่งนี้เพื่อบังคับให้ไลบรารียอมรับ SSH Algorithm รุ่นเก่า
            "disabled_algorithms": {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]}
        }

    def __str__(self) -> str:
        return f"{self.label}({self.username})"


def load_credentials(dotenv_path: str | None = None) -> List[Credential]:
    """
    Read NET_CRED_1_* .. NET_CRED_N_* from the environment/.env.

    Returns them in numeric order, so index 0 is tried first.
    Raises RuntimeError if none are found - we never fall back to defaults.
    """
    # override=False so real environment variables (e.g. from a secret manager
    # or CI) win over whatever is sitting in the .env file on disk.
    load_dotenv(dotenv_path=dotenv_path, override=False)

    creds: List[Credential] = []
    for i in range(1, MAX_CRED_SETS + 1):
        username = os.getenv(f"NET_CRED_{i}_USERNAME")
        password = os.getenv(f"NET_CRED_{i}_PASSWORD")

        # A set is only valid if both username and password exist.
        if not username or password is None:
            continue

        creds.append(
            Credential(
                username=username,
                password=password,
                secret=os.getenv(f"NET_CRED_{i}_SECRET", ""),
                label=os.getenv(f"NET_CRED_{i}_LABEL", f"cred{i}"),
            )
        )

    if not creds:
        raise RuntimeError(
            "No credentials found. Create a .env file with at least "
            "NET_CRED_1_USERNAME and NET_CRED_1_PASSWORD (see .env.example)."
        )

    log.info("Loaded %d credential set(s): %s", len(creds), ", ".join(str(c) for c in creds))
    return creds