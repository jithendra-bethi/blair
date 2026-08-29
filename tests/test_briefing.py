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
