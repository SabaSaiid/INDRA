"""
INDRA Platform — Account signals for social sources (layers 3 and 6, Phase 5 T7)

The "generic handle" idea from another SIH entry, made measurable. Mastodon
reports each post's account age, follower count and whether it is a bot, and
the poller has kept those in `source_meta` since Phase 2. Three published
rules turn them into flags, each with its cost (report_flags.FLAGS):

| flag            | rule                                   | effect |
|-----------------|----------------------------------------|--------|
| `new_account`   | the account is less than 7 days old when it posts | credibility × 0.6 |
| `few_followers` | fewer than 5 followers                 | × 0.8 |
| `bot_account`   | the platform marks the account a bot   | × 0.8, and it counts **at most 0.5** of a witness in n_eff: a bot re-posting news is not a witness |

A brand-new account with one follower therefore counts × 0.48 of an
established one. News publishers get no account flags: each publisher has its
own reputation in the source credibility table (T6).

Pure: the age is measured at the moment of posting, never against a clock, so
the same post always gets the same flags.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

NEW_ACCOUNT_AGE = timedelta(days=7)
FEW_FOLLOWERS = 5


def _parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def account_flags(
    *,
    account_created_at: Any,
    followers_count: Any,
    bot: Any,
    posted_at: Any,
) -> Tuple[List[str], Dict[str, str]]:
    """The T7 flags for one post's account, and why each was set. Unknown values set nothing."""
    basis: Dict[str, str] = {}
    created, posted = _parse(account_created_at), _parse(posted_at)
    if created is not None and posted is not None:
        age = posted - created
        if age < NEW_ACCOUNT_AGE:
            days = max(0, age.days)
            basis["new_account"] = f"account {days} day{'' if days == 1 else 's'} old when it posted"
    try:
        followers = int(followers_count) if followers_count is not None else None
    except (TypeError, ValueError):
        followers = None
    if followers is not None and followers < FEW_FOLLOWERS:
        basis["few_followers"] = f"{followers} follower{'' if followers == 1 else 's'}"
    if bot is True:
        basis["bot_account"] = "the platform marks this account as a bot"
    flags = [f for f in ("new_account", "few_followers", "bot_account") if f in basis]
    return flags, basis
