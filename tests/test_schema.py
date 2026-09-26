import pytest

from schema import CATEGORIES, PRIORITIES, ROUTES, TriageDecision, validate_decision

VALID = {
    "category": "billing",
    "priority": "P2",
    "route": "billing-team",
    "rationale": "Double charge is a money problem.",
}


def test_valid_decision_is_accepted():
    decision = validate_decision(VALID)
    assert decision.category == "billing"
    assert decision.priority == "P2"
    assert decision.route == "billing-team"
    assert decision.rationale == VALID["rationale"]


def test_missing_field_is_rejected_with_a_message_naming_the_field():
    bad = dict(VALID)
    del bad["rationale"]
    with pytest.raises(ValueError, match="rationale"):
        validate_decision(bad)


def test_extra_field_is_rejected_with_a_message_naming_the_field():
    bad = dict(VALID, extra="nope")
    with pytest.raises(ValueError, match="extra"):
        validate_decision(bad)


def test_invalid_category_is_rejected_with_a_message_naming_the_field():
    bad = dict(VALID, category="not-a-category")
    with pytest.raises(ValueError, match="category"):
        validate_decision(bad)


def test_invalid_priority_is_rejected_with_a_message_naming_the_field():
    bad = dict(VALID, priority="P5")
    with pytest.raises(ValueError, match="priority"):
        validate_decision(bad)


def test_invalid_route_is_rejected_with_a_message_naming_the_field():
    bad = dict(VALID, route="not-a-team")
    with pytest.raises(ValueError, match="route"):
        validate_decision(bad)


def test_wrong_type_is_rejected_with_a_message_naming_the_field():
    bad = dict(VALID, rationale=["not", "a", "string"])
    with pytest.raises(ValueError, match="rationale"):
        validate_decision(bad)


def test_non_object_payload_is_rejected():
    for payload in ("not a dict", ["a", "b"], 42, None):
        with pytest.raises(ValueError):
            validate_decision(payload)


def test_multiple_simultaneous_violations_still_raises_one_clear_error():
    bad = {"category": "not-a-category", "priority": "P2", "route": "billing-team"}  # missing rationale too
    with pytest.raises(ValueError, match="category") as exc_info:
        validate_decision(bad)
    assert "rationale" in str(exc_info.value)


def test_empty_rationale_is_accepted():
    # decision-schema.md says rationale "has no enum" and imposes no length
    # or non-emptiness rule, unlike category/priority/route. This is
    # intentional permissiveness, not an oversight.
    validate_decision(dict(VALID, rationale=""))


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_allowed_category_is_accepted(category):
    validate_decision(dict(VALID, category=category))


@pytest.mark.parametrize("priority", PRIORITIES)
def test_every_allowed_priority_is_accepted(priority):
    validate_decision(dict(VALID, priority=priority))


@pytest.mark.parametrize("route", ROUTES)
def test_every_allowed_route_is_accepted(route):
    validate_decision(dict(VALID, route=route))


def test_literal_fields_stay_in_sync_with_allowed_value_tuples():
    # Guards against schema.py's two hand-written copies of each allowed-value
    # list (the CATEGORIES/PRIORITIES/ROUTES tuples and the model's Literal
    # annotations) silently drifting apart.
    fields = TriageDecision.model_fields
    assert set(fields["category"].annotation.__args__) == set(CATEGORIES)
    assert set(fields["priority"].annotation.__args__) == set(PRIORITIES)
    assert set(fields["route"].annotation.__args__) == set(ROUTES)
