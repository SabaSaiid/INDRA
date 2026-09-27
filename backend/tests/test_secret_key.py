"""
Production refuses the JWT signing key the source ships (BUG-120).

Until 27 Sep the team server signed its tokens with the default in
core/config.py, so anyone who had read the repository could sign a
commander's token. Settings now refuse that key, or any key shorter than 32
characters, when ENVIRONMENT is production; development and tests keep the
default.
"""

import pytest
from pydantic import ValidationError

from app.core.config import MIN_PRODUCTION_SECRET_KEY_LENGTH, PUBLISHED_SECRET_KEY, Settings

STRONG = "k" * MIN_PRODUCTION_SECRET_KEY_LENGTH


@pytest.mark.parametrize("key", [PUBLISHED_SECRET_KEY, "k" * (MIN_PRODUCTION_SECRET_KEY_LENGTH - 1), ""])
@pytest.mark.parametrize("environment", ["production", "Production", " production "])
def test_production_refuses_the_published_or_a_short_key(environment, key):
    with pytest.raises(ValidationError, match="its own SECRET_KEY"):
        Settings(_env_file=None, ENVIRONMENT=environment, SECRET_KEY=key)


def test_production_accepts_its_own_key_of_32_characters():
    assert Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY=STRONG).SECRET_KEY == STRONG


@pytest.mark.parametrize("environment", ["development", "test", "e2e"])
def test_other_environments_keep_the_default(environment):
    assert Settings(_env_file=None, ENVIRONMENT=environment).SECRET_KEY == PUBLISHED_SECRET_KEY
