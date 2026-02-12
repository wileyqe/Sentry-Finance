"""
extractors/credentials.py — Secure credential storage and retrieval.

Supports multiple backends:
  1. Environment variables (NFCU_USERNAME, NFCU_PASSWORD, etc.)
  2. Interactive prompt (fallback)
  3. .env file (if python-dotenv is installed)

Credentials are NEVER stored in code or config files.
"""
import os
import logging
import getpass
from typing import Optional

log = logging.getLogger("antigravity")


def _try_dotenv():
    """Attempt to load .env file if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return True
    except ImportError:
        return False


def get_credential(institution: str, field: str,
                   prompt: str | None = None) -> str:
    """Retrieve a credential value.

    Lookup order:
      1. Environment variable: {INSTITUTION}_{FIELD} (e.g., NFCU_USERNAME)
      2. .env file (if python-dotenv installed)
      3. Interactive prompt (last resort)

    Args:
        institution: Institution key (e.g., "NFCU", "CHASE")
        field: Credential field (e.g., "USERNAME", "PASSWORD")
        prompt: Custom prompt for interactive input.

    Returns:
        The credential value as a string.
    """
    env_key = f"{institution.upper()}_{field.upper()}"

    # Try environment variable
    value = os.environ.get(env_key)
    if value:
        log.debug("Credential %s loaded from environment", env_key)
        return value

    # Try .env file
    _try_dotenv()
    value = os.environ.get(env_key)
    if value:
        log.debug("Credential %s loaded from .env", env_key)
        return value

    # Fall back to interactive prompt
    default_prompt = f"Enter {institution} {field.lower()}: "
    display_prompt = prompt or default_prompt

    if field.upper() == "PASSWORD":
        value = getpass.getpass(display_prompt)
    else:
        value = input(display_prompt)

    return value.strip()


def get_credentials(institution: str) -> dict[str, str]:
    """Get username and password for an institution.

    Returns dict with 'username' and 'password' keys.
    """
    return {
        "username": get_credential(institution, "USERNAME"),
        "password": get_credential(institution, "PASSWORD"),
    }


def has_env_credentials(institution: str) -> bool:
    """Check if credentials are available in environment (non-interactive)."""
    _try_dotenv()
    user_key = f"{institution.upper()}_USERNAME"
    pass_key = f"{institution.upper()}_PASSWORD"
    return bool(os.environ.get(user_key) and os.environ.get(pass_key))
