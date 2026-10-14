
const API_BASE = "";

async function request(endpoint, options = {}) {
  let response;

  try {
    response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });
  } catch (error) {
    throw new Error(
      "Cannot connect to the backend. Make sure FastAPI is running on http://localhost:8000."
    );
  }

  const raw = await response.text();
  let data;

  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    throw new Error(
      `The server returned an invalid response: ${raw.slice(0, 200)}`
    );
  }

  if (!response.ok) {
    const detail = data?.detail || data?.message || raw;

    throw new Error(
      typeof detail === "string"
        ? detail
        : JSON.stringify(detail)
    );
  }

  return data;
}

export async function matchPatient(patientCase) {
  if (!patientCase || !patientCase.trim()) {
    throw new Error("Please enter a patient case before matching trials.");
  }

  return request("/api/match", {
    method: "POST",
    body: JSON.stringify({
      patient_case: patientCase.trim(),
    }),
  });
}

export default {
  matchPatient,
};
