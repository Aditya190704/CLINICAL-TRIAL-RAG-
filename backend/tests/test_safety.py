from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.schemas import CriterionResult, PatientProfile
from app.services.eligibility_judge import compute_verdict, judge
from app.services.patient_parser import _validate_profile


def test_patient_profile_discards_facts_not_supported_by_case():
    profile = PatientProfile(
        age_years=70,
        sex="MALE",
        primary_conditions=["breast cancer", "lung cancer"],
        current_medications=["tamoxifen", "pembrolizumab"],
        key_findings=["HER2 positive"],
        search_query="breast cancer HER2 positive",
    )

    validated = _validate_profile(
        profile,
        "A 55-year-old female with breast cancer taking tamoxifen.",
    )

    assert validated.age_years is None
    assert validated.sex == "UNKNOWN"
    assert validated.primary_conditions == ["breast cancer"]
    assert validated.current_medications == ["tamoxifen"]
    assert validated.key_findings == []
    assert validated.search_query == "breast cancer"


def test_patient_profile_keeps_explicit_age_and_sex():
    profile = PatientProfile(
        age_years=55,
        sex="FEMALE",
        search_query="breast cancer",
    )

    validated = _validate_profile(
        profile,
        "A 55-year-old female with breast cancer.",
    )

    assert validated.age_years == 55
    assert validated.sex == "FEMALE"


def test_non_blocking_assessment_never_reports_eligible():
    supported = CriterionResult(
        source="TRIAL_TEXT",
        criterion_type="INCLUSION",
        criterion_quote="Age 18 years or older",
        patient_evidence="Age 55",
        impact="SUPPORTS",
        explanation="Age requirement is met.",
    )

    assert compute_verdict([supported]) == "POSSIBLY_ELIGIBLE"
    assert compute_verdict([]) == "POSSIBLY_ELIGIBLE"

    blocked = supported.model_copy(update={"impact": "BLOCKS"})
    assert compute_verdict([blocked]) == "EXCLUDED"


def test_unparseable_judge_output_fails_closed_without_logging_response(caplog):
    private_response = "patient-secret-phrase"
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        parsed=None,
        text=private_response,
    )
    profile = PatientProfile(age_years=55, search_query="cancer")

    with patch(
        "app.services.eligibility_judge.create_judge_client",
        return_value=client,
    ):
        criteria, summary, _ = judge(
            "A 55-year-old patient with cancer.",
            profile,
            {
                "nct_id": "NCT00000001",
                "eligibility_text": "Age 18 years or older",
                "min_age_years": 18,
                "max_age_years": 80,
            },
        )

    assert compute_verdict(criteria) == "POSSIBLY_ELIGIBLE"
    assert any(item.impact == "UNKNOWN" for item in criteria)
    assert "Manual review is required." in summary
    assert private_response not in caplog.text
