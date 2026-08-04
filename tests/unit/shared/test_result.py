"""Unit tests for shared.result.Result."""

from __future__ import annotations

import pytest

from pharmacy_invoice_automation.shared.result import Result

pytestmark = pytest.mark.unit


def test_success_reports_success_and_unwraps() -> None:
    result = Result.success(42)

    assert result.is_success is True
    assert result.is_failure is False
    assert result.failure_reason is None
    assert result.unwrap() == 42


def test_failure_reports_failure_and_carries_a_reason() -> None:
    result: Result[int] = Result.failure("could not compute")

    assert result.is_success is False
    assert result.is_failure is True
    assert result.failure_reason == "could not compute"


def test_unwrap_on_failure_raises_value_error() -> None:
    result: Result[int] = Result.failure("nope")

    with pytest.raises(ValueError, match="nope"):
        result.unwrap()


@pytest.mark.parametrize("falsy_value", [False, 0, "", ()])
def test_falsy_success_values_still_report_success(falsy_value: object) -> None:
    result = Result.success(falsy_value)

    assert result.is_success is True
    assert result.unwrap() == falsy_value


def test_success_and_failure_are_independent_instances() -> None:
    a = Result.success(1)
    b = Result.success(2)

    assert a.unwrap() != b.unwrap()
