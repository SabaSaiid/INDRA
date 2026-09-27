"""
scripts/set_operator_password.py refuses what it should, before touching a database.

Passwords left the source on 25 Sep (migration 0019): the script is the only
way an account gets one, so its refusals are the policy. Nothing here connects.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "set_operator_password.py"
_spec = importlib.util.spec_from_file_location("set_operator_password", SCRIPT)
set_operator_password = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(set_operator_password)

parse_args = set_operator_password.parse_args
choose_passwords = set_operator_password.choose_passwords
Refused = set_operator_password.Refused


@pytest.mark.parametrize(
    "argv",
    [
        [],                                              # nobody named
        ["--all", "commander"],                          # both at once
        ["commander", "--from-env", "X", "--generate"],  # two sources
        ["--all", "--from-env"],                         # --from-env needs a name
    ],
)
def test_bad_arguments_exit_2(argv):
    with pytest.raises(SystemExit) as exc:
        parse_args(argv)

    assert exc.value.code == 2


def test_names_or_all_parse():
    assert parse_args(["commander", "analyst"]).usernames == ["commander", "analyst"]
    args = parse_args(["--all", "--from-env", "INDRA_OPERATOR_PASSWORD"])
    assert args.all and args.from_env == "INDRA_OPERATOR_PASSWORD"


@pytest.mark.parametrize("password, ok", [("123456789", False), ("", False), ("1234567890", True)])
def test_passwords_under_ten_characters_are_refused(password, ok):
    assert (set_operator_password.password_problem(password) == "") is ok


def test_unknown_usernames_are_named_in_order():
    known = {"admin", "commander"}

    assert set_operator_password.unknown_usernames(["ghost", "commander", "nobody"], known) == ["ghost", "nobody"]
    assert set_operator_password.unknown_usernames(["admin"], known) == []


def test_the_target_never_shows_the_database_password():
    url = "postgresql+asyncpg://indra_user:s3cret-value@localhost:5433/indra_e2e"

    assert set_operator_password.describe_target(url) == "localhost:5433/indra_e2e"


def test_from_env_uses_one_password_for_every_account():
    args = parse_args(["--all", "--from-env", "PW"])

    chosen = choose_passwords(["admin", "commander"], args, {"PW": "long-enough-1"})

    assert chosen == {"admin": "long-enough-1", "commander": "long-enough-1"}


@pytest.mark.parametrize("environ", [{}, {"PW": ""}, {"PW": "short"}])
def test_from_env_refuses_a_missing_or_short_password(environ):
    args = parse_args(["commander", "--from-env", "PW"])

    with pytest.raises(Refused):
        choose_passwords(["commander"], args, environ)


def test_generate_gives_each_account_its_own_password():
    args = parse_args(["--all", "--generate"])

    chosen = choose_passwords(["admin", "commander", "analyst"], args, {})

    assert len(set(chosen.values())) == 3
    assert all(set_operator_password.password_problem(pw) == "" for pw in chosen.values())


def test_the_prompt_asks_twice_and_refuses_a_mismatch():
    args = parse_args(["commander"])
    typed = iter(["first-password", "other-password"])

    with pytest.raises(Refused, match="differ"):
        choose_passwords(["commander"], args, {}, prompt=lambda _: next(typed))


def test_the_prompt_refuses_a_short_password_before_asking_again():
    args = parse_args(["commander"])
    asked = []

    def prompt(message):
        asked.append(message)
        return "short"

    with pytest.raises(Refused, match="shorter than 10"):
        choose_passwords(["commander"], args, {}, prompt=prompt)
    assert len(asked) == 1


def test_the_prompt_accepts_two_matching_entries():
    args = parse_args(["commander", "analyst"])
    typed = iter(["commander-pass-1", "commander-pass-1", "analyst-pass-22", "analyst-pass-22"])

    chosen = choose_passwords(["commander", "analyst"], args, {}, prompt=lambda _: next(typed))

    assert chosen == {"commander": "commander-pass-1", "analyst": "analyst-pass-22"}
