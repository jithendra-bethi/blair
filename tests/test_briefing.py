import pytest

from blair.briefing import compose_briefing
from blair.models import AgentResult


def result(text: str) -> AgentResult:
    return AgentResult(session_id="test-session", text=text, provider="test")


def test_summarizes_success_and_references_table() -> None:
    briefing = compose_briefing(
        result(
            """
            ## Completed
            Implemented the Windows adapter and updated three files.

            | Check | Result |
            | --- | --- |
            | Unit tests | Passed |

            All 24 tests passed successfully.
            """
        )
    )

    assert briefing.status == "success"
    assert briefing.had_table is True
    assert "The task is complete." in briefing.text
    assert "compiled a table" in briefing.text
    assert "sir" in briefing.text
    assert "|" not in briefing.text


def test_code_is_not_spoken_verbatim() -> None:
    briefing = compose_briefing(
        result(
            """
            Fixed the session state race and verified the behavior.
            ```python
            raise RuntimeError("this should never be narrated")
            ```
            The tests passed.
            """
        )
    )

    assert briefing.had_code is True
    assert "RuntimeError" not in briefing.text
    assert "check the screen" in briefing.text.lower()


def test_reports_blocker_without_false_positive_for_no_errors() -> None:
    success = compose_briefing(result("Completed the build with no errors. All tests passed."))
    blocked = compose_briefing(result("The build failed. I need your approval to continue."))

    assert success.status == "success"
    assert blocked.status == "blocked"
    assert blocked.text.startswith("The task needs your attention.")


def test_explicit_brief_is_preferred() -> None:
    briefing = compose_briefing(
        result(
            "Lots of irrelevant prose. "
            "<blair_brief>Deployment completed and smoke tests passed.</blair_brief>"
        )
    )

    assert briefing.source == "explicit"
    assert "irrelevant" not in briefing.text
    assert "Deployment completed" in briefing.text


def test_word_limit_is_respected() -> None:
    text = "Implemented the feature. " + "This is additional information. " * 40
    briefing = compose_briefing(result(text), max_words=35)
    assert len(briefing.text.split()) <= 35


def test_sensitive_details_are_not_spoken() -> None:
    briefing = compose_briefing(
        result(
            "Updated C:\\Users\\Ada\\private\\config.json and see "
            "https://example.test/report?token=hunter2. "
            "The API key is sk-example-super-secret-value and commit "
            "0123456789abcdef0123456789abcdef passed validation."
        )
    )

    assert "Ada" not in briefing.text
    assert "https" not in briefing.text
    assert "hunter2" not in briefing.text
    assert "sk-example" not in briefing.text
    assert "0123456789abcdef" not in briefing.text
    assert "passed validation" in briefing.text


@pytest.mark.parametrize("prefix", ["ghp", "gho", "ghu", "ghs", "ghr"])
@pytest.mark.parametrize("wrapper", ["{}", "**{}**"])
def test_token_patterns_survive_formatting_until_redaction(prefix: str, wrapper: str) -> None:
    token = prefix + "_abcdefghijklmnopqrstuvwx"
    briefing = compose_briefing(result(f"Updated the credential {wrapper.format(token)} safely."))

    assert "abcdefghijklmnopqrstuvwx" not in briefing.text
    assert "sensitive information" in briefing.text
    assert "Updated the credential" in briefing.text
    assert "safely" in briefing.text


def test_underscores_do_not_shorten_a_secret_below_its_detection_threshold() -> None:
    briefing = compose_briefing(result("Updated the credential sk-a_b_c_d_e_f_g safely."))

    assert "abcdefg" not in briefing.text
    assert "sensitive information" in briefing.text


def test_explicit_brief_and_link_labels_use_the_same_token_filter() -> None:
    briefing = compose_briefing(
        result(
            "<blair_brief>Updated [ghp_abcdefghijklmnopqrstuvwx]"
            "(https://example.test) safely.</blair_brief>"
        )
    )

    assert briefing.source == "explicit"
    assert "abcdefghijklmnopqrstuvwx" not in briefing.text
    assert "sensitive information" in briefing.text


def test_formatted_secret_label_is_still_redacted_after_cleanup() -> None:
    briefing = compose_briefing(result("Updated **password**: synthetic-value safely."))

    assert "synthetic-value" not in briefing.text
    assert "sensitive information" in briefing.text


def test_partial_and_unverified_work_is_not_reported_as_complete() -> None:
    briefing = compose_briefing(
        result("Implemented the adapter, but integration tests were not run and remain unverified.")
    )

    assert briefing.status == "partial"
    assert briefing.text.startswith("The work is partly complete.")


def test_inline_commands_are_not_narrated() -> None:
    briefing = compose_briefing(
        result("Run `Remove-Item -Recurse important` after reviewing the migration notes.")
    )

    assert "Remove-Item" not in briefing.text


def test_question_reports_that_the_agent_is_waiting() -> None:
    briefing = compose_briefing(
        result("I can implement either approach. Which option do you prefer?")
    )

    assert briefing.status == "waiting"
    assert briefing.text.startswith("The agent is waiting for your input.")


@pytest.mark.parametrize(
    "important",
    [
        "The build failed.",
        "Blocked by missing credentials.",
        "Tests were not run.",
        "Please choose an option.",
        "Approval is required.",
        "Warning: the migration deletes existing data.",
    ],
)
def test_later_important_detail_is_kept_ahead_of_routine_updates(important: str) -> None:
    briefing = compose_briefing(
        result(f"Updated the interface. Created the documentation. {important}")
    )

    assert important in briefing.text
    assert briefing.text.index(important) < briefing.text.index("Updated the interface.")
    assert "Created the documentation." not in briefing.text


def test_failure_and_required_action_both_survive_routine_updates() -> None:
    briefing = compose_briefing(
        result(
            "Updated the interface. Created the documentation. "
            "The build failed. Approval is required."
        )
    )

    assert "The build failed." in briefing.text
    assert "Approval is required." in briefing.text
    assert "Updated the interface." not in briefing.text
    assert briefing.status == "blocked"


@pytest.mark.parametrize(
    "extra,reminder",
    [("", ""), ("\n```python\nprint('hidden')\n```", "check the screen for the code")],
)
def test_short_word_budget_keeps_failure_before_long_routine_update(
    extra: str, reminder: str
) -> None:
    briefing = compose_briefing(
        result(
            "Updated the interface with several additional controls and detailed descriptions "
            "to make every available option easier to understand. The build failed." + extra
        ),
        max_words=20,
    )

    assert "The build failed." in briefing.text
    assert len(briefing.text.split()) <= 20
    assert reminder in briefing.text


def test_no_errors_does_not_displace_an_actual_failure() -> None:
    briefing = compose_briefing(
        result("Updated the interface with no errors. All tests passed. The build failed.")
    )

    assert briefing.status == "blocked"
    assert "The build failed." in briefing.text
    assert briefing.text.index("The build failed.") < briefing.text.index("Updated the interface")


@pytest.mark.parametrize("marker", ["-", "+", "*"])
def test_discussion_bullets_are_spoken_without_a_code_reminder(marker: str) -> None:
    briefing = compose_briefing(
        result(f"{marker} Option A costs less.\n{marker} Option B is easier.")
    )

    assert "Option A costs less." in briefing.text
    assert "Option B is easier." in briefing.text
    assert briefing.had_code is False
    assert "check the screen" not in briefing.text.lower()


@pytest.mark.parametrize("marker", ["-", "+", "*"])
def test_failure_bullets_prevent_a_false_success_announcement(marker: str) -> None:
    briefing = compose_briefing(
        result(f"Implemented the feature.\n{marker} Tests failed.\n{marker} Approval is required.")
    )

    assert briefing.status == "blocked"
    assert "Tests failed." in briefing.text
    assert "The task is complete." not in briefing.text
    assert briefing.had_code is False
    assert "check the screen" not in briefing.text.lower()


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_fenced_code_still_produces_a_code_reminder(fence: str) -> None:
    briefing = compose_briefing(
        result(f"Updated the feature.\n{fence}python\nprint('hidden_code')\n{fence}")
    )

    assert "Updated the feature." in briefing.text
    assert "hidden" not in briefing.text
    assert briefing.had_code is True
    assert "check the screen for the code" in briefing.text.lower()


@pytest.mark.parametrize(
    "header",
    [
        "diff --git a/example.py b/example.py\nindex 1234567..abcdef0 100644\n"
        "--- a/example.py\n+++ b/example.py\n",
        "--- old/example.py\n+++ new/example.py\n",
        "",
    ],
)
def test_unfenced_diff_is_hidden_and_following_bullets_are_preserved(header: str) -> None:
    briefing = compose_briefing(
        result(
            header + "@@ -1,2 +1,2 @@\n"
            " context_secret = True\n"
            "-old_secret = 1\n"
            "+new_secret = 2\n"
            "- Tests failed.\n"
            "+ Approval is required."
        )
    )

    assert briefing.status == "blocked"
    assert "Tests failed." in briefing.text
    assert "Approval is required." in briefing.text
    assert "secret" not in briefing.text
    assert "index" not in briefing.text
    assert "@@" not in briefing.text
    assert briefing.had_code is True
    assert "check the screen for the code" in briefing.text.lower()


@pytest.mark.parametrize(
    "old_range,new_range,body",
    [
        ("1", "1", "-old_value\n+new_value"),
        ("0,0", "1", "+new_value"),
        ("1", "0,0", "-old_value"),
    ],
)
def test_diff_range_counts_end_before_prose_bullets(
    old_range: str, new_range: str, body: str
) -> None:
    briefing = compose_briefing(result(f"@@ -{old_range} +{new_range} @@\n{body}\n- Tests failed."))

    assert "Tests failed." in briefing.text
    assert "value" not in briefing.text
    assert briefing.status == "blocked"


def test_indented_diff_preserves_context_marker_and_following_prose() -> None:
    briefing = compose_briefing(
        result(
            "  @@ -1,2 +1,2 @@\n   context_secret\n  -old_secret\n  +new_secret\n  - Tests failed."
        )
    )

    assert "secret" not in briefing.text
    assert "Tests failed." in briefing.text


def test_truncated_diff_does_not_swallow_unmarked_prose() -> None:
    briefing = compose_briefing(
        result("@@ -1,4 +1,4 @@\n-old_secret\n+new_secret\nThe build failed.")
    )

    assert "secret" not in briefing.text
    assert "The build failed." in briefing.text
    assert briefing.status == "blocked"


def test_multiple_diff_hunks_and_no_newline_markers_stay_off_screen_briefing() -> None:
    briefing = compose_briefing(
        result(
            "diff --git a/example.py b/example.py\n"
            "@@ -1 +1 @@\n"
            "-old_secret\n"
            "\\ No newline at end of file\n"
            "+new_secret\n"
            "@@ -10 +10 @@ function_name\n"
            "-other_secret\n"
            "+replacement_secret\n"
            "\\ No newline at end of file\n"
            "- Tests failed."
        )
    )

    assert "Tests failed." in briefing.text
    assert "secret" not in briefing.text
    assert "newline" not in briefing.text
    assert briefing.had_code is True


def test_horizontal_rule_does_not_add_a_code_reminder() -> None:
    briefing = compose_briefing(result("Option A costs less.\n---\nOption B is easier."))

    assert briefing.had_code is False
    assert "Option A costs less." in briefing.text
    assert "Option B is easier." in briefing.text


@pytest.mark.parametrize(
    "text,status",
    [
        ("Tests were not run.", "partial"),
        ("Please choose an option.", "waiting"),
    ],
)
def test_bullet_caveats_and_decisions_retain_their_meaning(text: str, status: str) -> None:
    briefing = compose_briefing(result(f"- {text}"))

    assert briefing.status == status
    assert text in briefing.text
    assert briefing.had_code is False
