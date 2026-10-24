from datetime import datetime, timezone
from unittest.mock import patch

from app.services import user_data


class FakeSnapshot:
    def __init__(self, doc_id, data, reference=None):
        self.id = doc_id
        self._data = data
        self.exists = data is not None
        self.reference = reference

    def to_dict(self):
        return dict(self._data or {})


class FakeQuery:
    def __init__(self, docs):
        self.docs = docs

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, _count):
        return self

    def stream(self):
        return iter(self.docs)


class FakeMessageCollection(FakeQuery):
    pass


class FakeSessionRef:
    id = "session-123"

    def __init__(self, data, messages=()):
        self.data = data
        self.messages = list(messages)

    def get(self):
        return FakeSnapshot(self.id, self.data, self)

    def update(self, fields):
        self.data.update(fields)

    def collection(self, name):
        assert name == "messages"
        return FakeMessageCollection(self.messages)


def test_search_query_and_full_result_are_saved_for_reopen():
    ref = FakeSessionRef({"title": "Trial search"})
    query = "62-year-old patient with stage III lung cancer and documented EGFR mutation."
    result = {
        "patient_profile": {"search_query": "stage III lung cancer EGFR"},
        "matches": [{
            "nct_id": "NCT00000001",
            "title": "EGFR study",
            "summary": "Full trial summary",
            "passages": [{"text": "Trial evidence"}],
            "criteria": [{
                "source": "eligibility",
                "criterion_type": "INCLUSION",
                "criterion_quote": "EGFR mutation required",
                "patient_evidence": "EGFR exon 19 deletion",
                "impact": "SUPPORTS",
                "explanation": "The mutation matches.",
            }],
        }],
        "disclaimer": "Review clinically.",
    }

    with patch.object(user_data, "_session_ref", return_value=ref):
        assert user_data.save_search_query("uid-a", ref.id, query)
        assert user_data.save_match_result("uid-a", ref.id, result)

    assert ref.data["searchQuery"] == query
    assert ref.data["status"] == "matched"
    assert ref.data["matchedTrialIds"] == ["NCT00000001"]
    assert ref.data["resultSummary"] == result
    assert ref.data["resultSummary"]["matches"][0]["criteria"][0]["patient_evidence"]
    assert ref.data["resultSummary"]["matches"][0]["passages"]


def test_reopen_restores_query_result_and_chat_history():
    updated = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
    full_result = {"matches": [{"nct_id": "NCT00000002", "criteria": [{"impact": "UNKNOWN"}]}]}
    messages = [
        FakeSnapshot("turn-1_user", {
            "turnId": "turn-1", "role": "user", "content": "Does this trial include stage III?", "createdAt": updated,
        }),
        FakeSnapshot("turn-1_assistant", {
            "turnId": "turn-1", "role": "assistant", "content": "The inclusion criteria say...", "createdAt": updated,
            "trialReferences": [{"nct_id": "NCT00000002"}],
        }),
    ]
    ref = FakeSessionRef({
        "title": "Lung cancer search",
        "searchQuery": "Stage III lung cancer with EGFR mutation and prior treatment details.",
        "searchedAt": updated,
        "createdAt": updated,
        "updatedAt": updated,
        "status": "matched",
        "matchedTrialIds": ["NCT00000002"],
        "resultSummary": full_result,
    }, messages)

    with patch.object(user_data, "_session_ref", return_value=ref):
        restored = user_data.get_session("uid-a", ref.id)

    assert restored["searchQuery"].startswith("Stage III lung cancer")
    assert restored["data"] == full_result
    assert restored["chatHistory"] == [{
        "question": "Does this trial include stage III?",
        "answer": "The inclusion criteria say...",
        "citations": [{"nct_id": "NCT00000002"}],
        "timestamp": updated.isoformat(),
    }]


def test_sidebar_session_list_is_lightweight_and_ordered_by_updated_at():
    updated = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
    result = {"matches": [{
        "nct_id": "NCT00000003", "title": "Trial", "verdict": "ELIGIBLE",
        "passages": [{"text": "Large evidence payload"}],
    }]}
    doc = FakeSnapshot("session-123", {
        "title": "Trial search",
        "searchQuery": "anonymized patient query",
        "createdAt": updated,
        "updatedAt": updated,
        "searchedAt": updated,
        "status": "matched",
        "matchedTrialIds": ["NCT00000003"],
        "resultSummary": result,
    })

    class FakeSessions(FakeQuery):
        def order_by(self, field, direction=None):
            assert field == "updatedAt"
            assert direction is not None
            return self

    class FakeUser:
        def collection(self, name):
            assert name == "sessions"
            return FakeSessions([doc])

        def document(self, _uid):
            return FakeUser()

    class FakeUsers:
        def collection(self, name):
            assert name == "users"
            return self

        def document(self, _uid):
            return FakeUser()

    class FakeDb:
        def collection(self, _name):
            return FakeUsers()

    with patch("app.services.user_data.firestore_client", return_value=FakeDb()):
        listed = user_data.list_sessions("uid-a")

    assert listed[0]["searchQuery"] == "anonymized patient query"
    assert listed[0]["data"]["matches"] == [{
        "nct_id": "NCT00000003", "title": "Trial", "verdict": "ELIGIBLE",
    }]
