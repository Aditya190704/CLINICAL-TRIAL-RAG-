"""User-scoped Firestore profiles, sessions, and chat persistence."""

from __future__ import annotations

from typing import Any

from app.services.firebase_auth import firestore_client



def _timestamp_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _session_ref(uid: str, session_id: str):
    return firestore_client().collection("users").document(uid).collection("sessions").document(session_id)


def get_or_create_profile(uid: str, email: str, display_name: str) -> dict[str, Any]:
    db = firestore_client()
    ref = db.collection("users").document(uid)
    snapshot = ref.get()
    if snapshot.exists:
        profile = snapshot.to_dict() or {}
        # Never trust a stored or client-supplied role to grant access.
        return {
            "displayName": str(profile.get("displayName") or display_name or "Clinical Technician"),
            "email": str(profile.get("email") or email),
            "role": "clinical_technician",
        }

    from firebase_admin import firestore

    profile = {
        "displayName": (display_name or "Clinical Technician")[:100],
        "email": email[:254],
        "role": "clinical_technician",
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    }
    # A concurrent first login may create this document first. Merge only
    # controlled fields and keep the application role fixed.
    ref.set(profile, merge=True)
    return {key: profile[key] for key in ("displayName", "email", "role")}


def initialize_profile(uid: str, email: str, display_name: str) -> dict[str, Any]:
    """Initialize a profile after signup; role and UID remain server-controlled."""
    from firebase_admin import firestore

    ref = firestore_client().collection("users").document(uid)
    snapshot = ref.get()
    now = firestore.SERVER_TIMESTAMP
    if snapshot.exists:
        ref.update({
            "displayName": display_name[:100],
            "email": email[:254],
            "updatedAt": now,
        })
    else:
        ref.set({
            "displayName": display_name[:100],
            "email": email[:254],
            "role": "clinical_technician",
            "createdAt": now,
            "updatedAt": now,
        })
    return {"displayName": display_name[:100], "email": email[:254], "role": "clinical_technician"}


def create_session(uid: str, title: str = "New Patient Session") -> dict[str, Any]:
    from firebase_admin import firestore

    ref = firestore_client().collection("users").document(uid).collection("sessions").document()
    ref.set({
        "title": (title or "New Patient Session")[:100],
        "createdAt": firestore.SERVER_TIMESTAMP,
        "updatedAt": firestore.SERVER_TIMESTAMP,
        "status": "draft",
        "matchedTrialIds": [],
        "resultSummary": None,
    })
    return {"id": ref.id, "title": title or "New Patient Session", "status": "draft", "matchedTrialIds": [], "resultSummary": None}


def save_search_query(uid: str, session_id: str, search_query: str) -> bool:
    """Save a validated search to its owner's session before matching starts."""
    from firebase_admin import firestore

    ref = _session_ref(uid, session_id)
    if not ref.get().exists:
        return False
    ref.update({
        "searchQuery": search_query,
        "searchedAt": firestore.SERVER_TIMESTAMP,
        "status": "searching",
        "matchedTrialIds": [],
        "resultSummary": None,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    return True


def mark_search_failed(uid: str, session_id: str) -> None:
    """Leave a durable query in a clear retryable state after matching fails."""
    from firebase_admin import firestore

    ref = _session_ref(uid, session_id)
    if ref.get().exists:
        ref.update({"status": "failed", "updatedAt": firestore.SERVER_TIMESTAMP})


def _sidebar_result_summary(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    matches = []
    for match in result.get("matches", []):
        if not isinstance(match, dict):
            continue
        matches.append({
            key: match.get(key)
            for key in ("nct_id", "title", "verdict", "relevance_score")
            if key in match
        })
    return {
        "matches": matches,
        "disclaimer": result.get("disclaimer", ""),
        "result_message": result.get("result_message"),
    }


def list_sessions(uid: str) -> list[dict[str, Any]]:
    ref = firestore_client().collection("users").document(uid).collection("sessions")
    docs = ref.order_by("updatedAt", direction="DESCENDING").stream()
    result = []
    for doc in docs:
        data = doc.to_dict() or {}
        result.append({
            "id": doc.id,
            "title": data.get("title") or "Untitled Session",
            "createdAt": _timestamp_value(data.get("createdAt")),
            "updatedAt": _timestamp_value(data.get("updatedAt")),
            "searchedAt": _timestamp_value(data.get("searchedAt")),
            "status": data.get("status", "draft"),
            "matchedTrialIds": data.get("matchedTrialIds", []),
            "searchQuery": data.get("searchQuery", ""),
            "data": _sidebar_result_summary(data.get("resultSummary")),
        })
    return result


def get_session(uid: str, session_id: str) -> dict[str, Any] | None:
    snapshot = _session_ref(uid, session_id).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    messages = (
        snapshot.reference.collection("messages")
        .order_by("createdAt", direction="DESCENDING")
        .stream()
    )
    by_turn: dict[str, dict[str, Any]] = {}
    for message in reversed(list(messages)):
        item = message.to_dict() or {}
        turn_id = str(item.get("turnId") or message.id)
        turn = by_turn.setdefault(turn_id, {"question": "", "answer": "", "citations": [], "timestamp": None})
        if item.get("role") == "user":
            turn["question"] = str(item.get("content") or "")
        elif item.get("role") == "assistant":
            turn["answer"] = str(item.get("content") or "")
            turn["citations"] = item.get("trialReferences", [])
        turn["timestamp"] = _timestamp_value(item.get("createdAt")) or turn["timestamp"]
    return {
        "id": snapshot.id,
        "title": data.get("title") or "Untitled Session",
        "createdAt": _timestamp_value(data.get("createdAt")),
        "updatedAt": _timestamp_value(data.get("updatedAt")),
        "searchedAt": _timestamp_value(data.get("searchedAt")),
        "status": data.get("status", "draft"),
        "matchedTrialIds": data.get("matchedTrialIds", []),
        "searchQuery": data.get("searchQuery", ""),
        "data": data.get("resultSummary"),
        "chatHistory": list(by_turn.values()),
    }


def update_session_title(uid: str, session_id: str, title: str) -> bool:
    from firebase_admin import firestore

    ref = _session_ref(uid, session_id)
    if not ref.get().exists:
        return False
    ref.update({"title": title[:100], "updatedAt": firestore.SERVER_TIMESTAMP})
    return True


def save_match_result(uid: str, session_id: str, response: dict[str, Any]) -> bool:
    from firebase_admin import firestore

    ref = _session_ref(uid, session_id)
    if not ref.get().exists:
        return False

    # Keep the full structured response so reopening restores criteria,
    # evidence, and trial summaries exactly as they were presented.
    summary = response
    matches = summary.get("matches", [])
    ref.update({
        "status": "matched",
        "matchedTrialIds": [item.get("nct_id") for item in matches if item.get("nct_id")],
        "resultSummary": summary,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    return True


def persist_chat_turn(
    uid: str,
    session_id: str,
    turn_id: str,
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
) -> bool:
    from firebase_admin import firestore

    session_ref = _session_ref(uid, session_id)
    if not session_ref.get().exists:
        return False
    messages_ref = session_ref.collection("messages")
    timestamp = firestore.SERVER_TIMESTAMP
    batch = firestore_client().batch()
    batch.set(messages_ref.document(f"{turn_id}_user"), {
        "turnId": turn_id,
        "role": "user",
        "content": question[:4000],
        "createdAt": timestamp,
        "trialReferences": [],
    }, merge=True)
    batch.set(messages_ref.document(f"{turn_id}_assistant"), {
        "turnId": turn_id,
        "role": "assistant",
        "content": answer[:12000],
        "createdAt": timestamp,
        "trialReferences": citations[:12],
    }, merge=True)
    batch.update(session_ref, {"updatedAt": timestamp})
    batch.commit()
    return True


def load_chat_turn(uid: str, session_id: str, turn_id: str) -> dict[str, Any] | None:
    messages_ref = _session_ref(uid, session_id).collection("messages")
    user_message = messages_ref.document(f"{turn_id}_user").get()
    assistant_message = messages_ref.document(f"{turn_id}_assistant").get()
    if not assistant_message.exists:
        return None
    user_data = user_message.to_dict() or {}
    assistant_data = assistant_message.to_dict() or {}
    return {
        "question": user_data.get("content", ""),
        "answer": assistant_data.get("content", ""),
        "citations": assistant_data.get("trialReferences", []),
    }


def delete_session(uid: str, session_id: str) -> bool:
    ref = _session_ref(uid, session_id)
    if not ref.get().exists:
        return False
    for message in ref.collection("messages").stream():
        message.reference.delete()
    ref.delete()
    return True


def clear_sessions(uid: str) -> None:
    sessions = firestore_client().collection("users").document(uid).collection("sessions").stream()
    for session in sessions:
        delete_session(uid, session.id)


def clear_chat_messages(uid: str, session_id: str) -> bool:
    ref = _session_ref(uid, session_id)
    if not ref.get().exists:
        return False
    for message in ref.collection("messages").stream():
        message.reference.delete()
    return True


def clear_match_result(uid: str, session_id: str) -> bool:
    from firebase_admin import firestore

    ref = _session_ref(uid, session_id)
    if not ref.get().exists:
        return False
    ref.update({
        "status": "draft",
        "searchQuery": "",
        "searchedAt": None,
        "matchedTrialIds": [],
        "resultSummary": None,
        "updatedAt": firestore.SERVER_TIMESTAMP,
    })
    return True
