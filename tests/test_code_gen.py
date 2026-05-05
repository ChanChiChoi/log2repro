"""Tests for the LLM code generation module (D2).

All tests mock litellm so no real LLM calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from log2repro.extractors.ast_parser import ASTContext
from log2repro.generators.code_gen import (
    ReproContext,
    _normalise_block_name,
    _validate_files,
    generate_repro_script,
    parse_llm_response,
)
from log2repro.validators.sandbox import SandboxResult
from log2repro.generators.prompts import (
    SYSTEM_PROMPT_DATABASE,
    SYSTEM_PROMPT_GENERAL,
    SYSTEM_PROMPT_NETWORK,
    render_user_message,
    select_system_prompt,
)
from log2repro.parsers.base import ParsedTrace

FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Sample LLM responses for testing
# ---------------------------------------------------------------------------

GOOD_LLM_RESPONSE = """\
Here is the reproduction script:

```reproduce.py
""" + '"""Minimal reproduction for ValueError."""' + """

import json
from unittest.mock import MagicMock

def process_data(data):
    user_id = data.get("user_id")
    if user_id is None:
        raise ValueError("user_id must not be None")
    return {"user_id": user_id}

def main():
    mock_data = json.load(open("mock_data.json"))
    try:
        result = process_data(mock_data)
        print(f"Unexpected success: {result}")
    except ValueError as e:
        print(f"Reproduced error: {e}")
        raise

if __name__ == "__main__":
    main()
```

```requirements.txt
# No external dependencies — stdlib only
```

```mock_data.json
{
  "user_id": null,
  "name": "test_user"
}
```
"""

GOOD_LLM_RESPONSE_PYTHON_TAG = """\
```python
raise ValueError("test")
```

```text
# no deps
```

```json
{"key": "value"}
```
"""

INCOMPLETE_LLM_RESPONSE = """\
```reproduce.py
print("hello")
```
"""

EMPTY_LLM_RESPONSE = "I cannot generate a reproduction script for this error."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_trace() -> ParsedTrace:
    return ParsedTrace(
        file="/app/utils.py",
        line=42,
        error="ValueError: user_id must not be None",
        context_vars=["user_id", "data", "payload"],
        chain=["/app/main.py:main:10", "/app/utils.py:validate:42"],
    )


@pytest.fixture()
def sample_ast_context() -> ASTContext:
    return ASTContext(
        signature="def validate(payload: dict, strict: bool = True) -> dict",
        imports=["import json", "from typing import Optional"],
        known_vars={"user_id": "Optional[int]", "name": "str"},
    )


@pytest.fixture()
def sample_context(
    sample_trace: ParsedTrace,
    sample_ast_context: ASTContext,
) -> ReproContext:
    return ReproContext(
        trace=sample_trace,
        ast_context=sample_ast_context,
        model="gpt-4o",
    )


# ---------------------------------------------------------------------------
# Tests: parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLLMResponse:
    """Tests for Markdown code-block extraction."""

    def test_parses_three_blocks(self) -> None:
        files = parse_llm_response(GOOD_LLM_RESPONSE)
        assert "reproduce.py" in files
        assert "requirements.txt" in files
        assert "mock_data.json" in files

    def test_reproduce_content(self) -> None:
        files = parse_llm_response(GOOD_LLM_RESPONSE)
        assert "def process_data" in files["reproduce.py"]
        assert "ValueError" in files["reproduce.py"]

    def test_mock_data_is_valid_json(self) -> None:
        files = parse_llm_response(GOOD_LLM_RESPONSE)
        data = json.loads(files["mock_data.json"])
        assert "user_id" in data

    def test_python_language_tag_mapping(self) -> None:
        files = parse_llm_response(GOOD_LLM_RESPONSE_PYTHON_TAG)
        assert "reproduce.py" in files
        assert "requirements.txt" in files
        assert "mock_data.json" in files

    def test_incomplete_response_missing_files(self) -> None:
        files = parse_llm_response(INCOMPLETE_LLM_RESPONSE)
        assert "reproduce.py" in files
        assert "requirements.txt" not in files

    def test_empty_response(self) -> None:
        files = parse_llm_response(EMPTY_LLM_RESPONSE)
        assert files == {}

    def test_custom_filename_preserved(self) -> None:
        text = "```helper.py\nprint('hi')\n```"
        files = parse_llm_response(text)
        assert "helper.py" in files

    def test_sql_block_ignored(self) -> None:
        text = "```sql\nSELECT 1;\n```"
        files = parse_llm_response(text)
        assert files == {}


# ---------------------------------------------------------------------------
# Tests: _normalise_block_name
# ---------------------------------------------------------------------------


class TestNormaliseBlockName:
    """Tests for code-block name normalisation."""

    def test_known_filename(self) -> None:
        assert _normalise_block_name("reproduce.py") == "reproduce.py"

    def test_python_tag(self) -> None:
        assert _normalise_block_name("python") == "reproduce.py"

    def test_json_tag(self) -> None:
        assert _normalise_block_name("json") == "mock_data.json"

    def test_text_tag(self) -> None:
        assert _normalise_block_name("text") == "requirements.txt"

    def test_bare_tag(self) -> None:
        assert _normalise_block_name("") == "requirements.txt"

    def test_unknown_tag_ignored(self) -> None:
        assert _normalise_block_name("sql") is None

    def test_custom_filename_with_dot(self) -> None:
        assert _normalise_block_name("config.yaml") == "config.yaml"


# ---------------------------------------------------------------------------
# Tests: _validate_files
# ---------------------------------------------------------------------------


class TestValidateFiles:
    """Tests for output validation."""

    def test_all_present(self) -> None:
        _validate_files({
            "reproduce.py": "x",
            "requirements.txt": "",
            "mock_data.json": "{}",
        })

    def test_missing_reproduce(self) -> None:
        with pytest.raises(ValueError, match="missing required"):
            _validate_files({"requirements.txt": "", "mock_data.json": "{}"})

    def test_missing_all(self) -> None:
        with pytest.raises(ValueError, match="missing required"):
            _validate_files({})


# ---------------------------------------------------------------------------
# Tests: select_system_prompt
# ---------------------------------------------------------------------------


class TestSelectSystemPrompt:
    """Tests for prompt selection heuristics."""

    def test_general_by_default(self) -> None:
        prompt = select_system_prompt("ValueError: bad value")
        assert prompt is SYSTEM_PROMPT_GENERAL

    def test_network_for_requests(self) -> None:
        prompt = select_system_prompt("requests.exceptions.SSLError: ...")
        assert prompt is SYSTEM_PROMPT_NETWORK

    def test_network_for_ssl(self) -> None:
        prompt = select_system_prompt("ssl.SSLCertVerificationError: cert expired")
        assert prompt is SYSTEM_PROMPT_NETWORK

    def test_network_for_connection_refused(self) -> None:
        prompt = select_system_prompt("ConnectionRefusedError: [Errno 111]")
        assert prompt is SYSTEM_PROMPT_NETWORK

    def test_database_for_sqlalchemy(self) -> None:
        prompt = select_system_prompt("sqlalchemy.exc.IntegrityError: duplicate key")
        assert prompt is SYSTEM_PROMPT_DATABASE

    def test_database_for_noresult(self) -> None:
        prompt = select_system_prompt("NoResultFound: No row was found")
        assert prompt is SYSTEM_PROMPT_DATABASE

    def test_database_for_psycopg2(self) -> None:
        prompt = select_system_prompt("psycopg2.errors.UniqueViolation: ...")
        assert prompt is SYSTEM_PROMPT_DATABASE

    def test_general_for_pydantic(self) -> None:
        prompt = select_system_prompt("pydantic_core.ValidationError: ...")
        assert prompt is SYSTEM_PROMPT_GENERAL


# ---------------------------------------------------------------------------
# Tests: render_user_message
# ---------------------------------------------------------------------------


class TestRenderUserMessage:
    """Tests for Jinja2 user-message rendering."""

    def test_basic_render(self) -> None:
        msg = render_user_message(
            file="app.py",
            line=10,
            error="ValueError: x",
            chain=["a.py:f:1"],
            context_vars=["x", "y"],
            signature="def f(x: int) -> None",
            imports=["import os"],
            known_vars={"x": "int"},
        )
        assert "app.py" in msg
        assert "ValueError: x" in msg
        assert "def f(x: int) -> None" in msg
        assert "`x`" in msg

    def test_empty_context(self) -> None:
        msg = render_user_message(
            file="x.py",
            line=1,
            error="E",
            chain=[],
            context_vars=[],
            signature="",
            imports=[],
            known_vars={},
        )
        assert "x.py" in msg


# ---------------------------------------------------------------------------
# Tests: ReproContext
# ---------------------------------------------------------------------------


class TestReproContext:
    """Tests for the ReproContext dataclass."""

    def test_to_prompt_vars(self, sample_context: ReproContext) -> None:
        vars = sample_context.to_prompt_vars()
        assert vars["file"] == "/app/utils.py"
        assert vars["line"] == 42
        assert "ValueError" in vars["error"]
        assert "validate" in vars["signature"]
        assert "user_id" in vars["known_vars"]

    def test_default_ast_context(self, sample_trace: ParsedTrace) -> None:
        ctx = ReproContext(trace=sample_trace)
        assert ctx.ast_context.signature == ""
        assert ctx.ast_context.imports == []

    def test_custom_model(self, sample_trace: ParsedTrace) -> None:
        ctx = ReproContext(trace=sample_trace, model="claude-3-opus")
        assert ctx.model == "claude-3-opus"


# ---------------------------------------------------------------------------
# Tests: generate_repro_script (mocked LLM)
# ---------------------------------------------------------------------------


class TestGenerateReproScript:
    """Tests for the full generation pipeline with mocked LLM.

    All tests mock ``_call_llm`` so no real ``litellm`` dependency is needed.
    """

    MOCK_PATH = "log2repro.generators.code_gen._call_llm"

    def test_success(self, sample_context: ReproContext) -> None:
        """A well-formed LLM response is parsed into three files."""
        with patch(self.MOCK_PATH, return_value=GOOD_LLM_RESPONSE) as mock_call:
            files = generate_repro_script(sample_context)

        assert "reproduce.py" in files
        assert "requirements.txt" in files
        assert "mock_data.json" in files
        mock_call.assert_called_once()

    def test_calls_with_correct_args(self, sample_context: ReproContext) -> None:
        """Verify _call_llm receives the expected arguments."""
        with patch(self.MOCK_PATH, return_value=GOOD_LLM_RESPONSE) as mock_call:
            generate_repro_script(sample_context, temperature=0.5, max_tokens=1000)

        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["max_tokens"] == 1000
        msgs = call_kwargs["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_system_prompt_selected_for_network_error(self) -> None:
        """Network errors should use the network system prompt."""
        trace = ParsedTrace(
            file="sync.py",
            line=10,
            error="requests.exceptions.SSLError: SSL cert expired",
            chain=["sync.py:fetch:10"],
        )
        ctx = ReproContext(trace=trace)
        with patch(self.MOCK_PATH, return_value=GOOD_LLM_RESPONSE) as mock_call:
            generate_repro_script(ctx)

        system_content = mock_call.call_args.kwargs["messages"][0]["content"]
        assert "network" in system_content.lower() or "I/O" in system_content

    def test_system_prompt_selected_for_db_error(self) -> None:
        """Database errors should use the database system prompt."""
        trace = ParsedTrace(
            file="repo.py",
            line=20,
            error="sqlalchemy.exc.IntegrityError: duplicate key",
            chain=["repo.py:save:20"],
        )
        ctx = ReproContext(trace=trace)
        with patch(self.MOCK_PATH, return_value=GOOD_LLM_RESPONSE) as mock_call:
            generate_repro_script(ctx)

        system_content = mock_call.call_args.kwargs["messages"][0]["content"]
        assert "database" in system_content.lower() or "SQLAlchemy" in system_content

    def test_retry_on_incomplete_response(self, sample_context: ReproContext) -> None:
        """Retry when LLM returns incomplete output (missing files)."""
        with patch(self.MOCK_PATH, side_effect=[INCOMPLETE_LLM_RESPONSE, GOOD_LLM_RESPONSE]) as mock_call, \
             patch("log2repro.generators.code_gen.time.sleep"):
            files = generate_repro_script(sample_context)

        assert "reproduce.py" in files
        assert mock_call.call_count == 2

    def test_retry_on_llm_exception(self, sample_context: ReproContext) -> None:
        """Retry when _call_llm raises an exception."""
        with patch(self.MOCK_PATH, side_effect=[RuntimeError("API timeout"), GOOD_LLM_RESPONSE]) as mock_call, \
             patch("log2repro.generators.code_gen.time.sleep"):
            files = generate_repro_script(sample_context)

        assert "reproduce.py" in files
        assert mock_call.call_count == 2

    def test_raises_after_all_retries_exhausted(self, sample_context: ReproContext) -> None:
        """RuntimeError after MAX_RETRIES+1 failures."""
        with patch(self.MOCK_PATH, side_effect=RuntimeError("permanent failure")), \
             patch("log2repro.generators.code_gen.time.sleep"):
            with pytest.raises(RuntimeError, match="failed after"):
                generate_repro_script(sample_context)

    def test_user_message_contains_ast_context(self, sample_context: ReproContext) -> None:
        """The user message should include AST-extracted info."""
        with patch(self.MOCK_PATH, return_value=GOOD_LLM_RESPONSE) as mock_call:
            generate_repro_script(sample_context)

        user_msg = mock_call.call_args.kwargs["messages"][1]["content"]
        assert "validate" in user_msg  # from AST signature
        assert "import json" in user_msg  # from AST imports
        assert "user_id" in user_msg  # from known_vars


# ---------------------------------------------------------------------------
# Tests: sandbox refinement loop
# ---------------------------------------------------------------------------


# A "bad" response — script prints but does NOT raise the expected error.
BAD_LLM_RESPONSE = """\
Here is a script:

```reproduce.py
print("This script does not raise ValueError")
```

```requirements.txt
# none
```

```mock_data.json
{}
```
"""

# A "refined" response — script now raises the expected error.
REFINED_LLM_RESPONSE = """\
Fixed script:

```reproduce.py
raise ValueError("user_id must not be None")
```

```requirements.txt
# none
```

```mock_data.json
{}
```
"""


class TestSandboxRefinement:
    """Tests for the sandbox→LLM feedback loop."""

    MOCK_LLM = "log2repro.generators.code_gen._call_llm"
    MOCK_SANDBOX = "log2repro.generators.code_gen._run_sandbox_check"

    def test_refines_on_mismatch(self, sample_context: ReproContext) -> None:
        """When sandbox doesn't reproduce the error, LLM is called again for a fix."""
        sandbox_fail = SandboxResult(
            stdout="", stderr="print ran fine", exit_code=0, error_reproduced=False,
        )
        sandbox_ok = SandboxResult(
            stdout="",
            stderr="ValueError: user_id must not be None",
            exit_code=1,
            error_reproduced=True,
        )

        with (
            patch(self.MOCK_LLM, side_effect=[GOOD_LLM_RESPONSE, REFINED_LLM_RESPONSE]) as mock_llm,
            patch(self.MOCK_SANDBOX, side_effect=[sandbox_fail, sandbox_ok]) as mock_sandbox,
        ):
            files = generate_repro_script(sample_context, max_refine_rounds=2)

        assert "raise ValueError" in files["reproduce.py"]
        assert mock_llm.call_count == 2
        assert mock_sandbox.call_count == 2

        # Second LLM call should be a refinement message
        second_call_msgs = mock_llm.call_args_list[1].kwargs["messages"]
        assert "未能复现" in second_call_msgs[1]["content"] or "stderr" in second_call_msgs[1]["content"]

    def test_skips_refine_when_rounds_zero(self, sample_context: ReproContext) -> None:
        """max_refine_rounds=0 skips sandbox entirely."""
        with (
            patch(self.MOCK_LLM, return_value=GOOD_LLM_RESPONSE) as mock_llm,
            patch(self.MOCK_SANDBOX) as mock_sandbox,
        ):
            files = generate_repro_script(sample_context, max_refine_rounds=0)

        assert "reproduce.py" in files
        assert mock_llm.call_count == 1
        mock_sandbox.assert_not_called()

    def test_returns_last_files_on_exhaustion(self, sample_context: ReproContext) -> None:
        """After max rounds without reproduction, returns the last files."""
        sandbox_fail = SandboxResult(
            stdout="", stderr="TypeError: other error", exit_code=1, error_reproduced=False,
        )

        with (
            patch(self.MOCK_LLM, side_effect=[GOOD_LLM_RESPONSE, REFINED_LLM_RESPONSE, REFINED_LLM_RESPONSE]) as mock_llm,
            patch(self.MOCK_SANDBOX, return_value=sandbox_fail) as mock_sandbox,
        ):
            files = generate_repro_script(sample_context, max_refine_rounds=2)

        # Returns files even though error was never reproduced
        assert "reproduce.py" in files
        assert mock_sandbox.call_count == 2
        assert mock_llm.call_count == 3  # initial + 2 refinements

    def test_sandbox_timeout_passed_through(self, sample_context: ReproContext) -> None:
        """sandbox_timeout is forwarded to _run_sandbox_check."""
        sandbox_ok = SandboxResult(error_reproduced=True)

        with (
            patch(self.MOCK_LLM, return_value=GOOD_LLM_RESPONSE),
            patch(self.MOCK_SANDBOX, return_value=sandbox_ok) as mock_sandbox,
        ):
            generate_repro_script(sample_context, sandbox_timeout=30, max_refine_rounds=1)

        mock_sandbox.assert_called_once()
        assert mock_sandbox.call_args.kwargs["timeout"] == 30

    def test_refine_message_contains_original_error(self, sample_context: ReproContext) -> None:
        """The refinement message includes the original error and sandbox stderr."""
        sandbox_fail = SandboxResult(
            stdout="out", stderr="TypeError: wrong type", exit_code=1, error_reproduced=False,
        )

        with (
            patch(self.MOCK_LLM, side_effect=[GOOD_LLM_RESPONSE, REFINED_LLM_RESPONSE]) as mock_llm,
            patch(self.MOCK_SANDBOX, side_effect=[sandbox_fail, SandboxResult(error_reproduced=True)]),
        ):
            generate_repro_script(sample_context, max_refine_rounds=1)

        # Inspect the refinement user message
        refine_msg = mock_llm.call_args_list[1].kwargs["messages"][1]["content"]
        assert "ValueError" in refine_msg
        assert "TypeError: wrong type" in refine_msg
        assert "stderr" in refine_msg

    def test_refine_preserves_requirements_and_mock(self, sample_context: ReproContext) -> None:
        """Refinement merges new reproduce.py with existing requirements/mock_data."""
        sandbox_fail = SandboxResult(
            stdout="", stderr="err", exit_code=1, error_reproduced=False,
        )
        # LLM returns only reproduce.py in the refinement (no requirements/mock)
        refine_only_repro = """```reproduce.py\nraise ValueError("fixed")\n```"""

        with (
            patch(self.MOCK_LLM, side_effect=[GOOD_LLM_RESPONSE, refine_only_repro]),
            patch(self.MOCK_SANDBOX, side_effect=[sandbox_fail, SandboxResult(error_reproduced=True)]),
        ):
            files = generate_repro_script(sample_context, max_refine_rounds=1)

        # reproduce.py updated, but requirements.txt and mock_data.json preserved
        assert "raise ValueError" in files["reproduce.py"]
        assert "requirements.txt" in files
        assert "mock_data.json" in files
