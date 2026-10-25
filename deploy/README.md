# Cloud Run deployment

This project deploys as two Cloud Run services: the FastAPI API and the React static application. The deployment script uses Cloud Build from the Dockerfiles and keeps the local Firebase web configuration in ignored `frontend/.env`.

## Prerequisites

1. Install Google Cloud CLI, Node.js 20+, and npm.
2. Sign in with `gcloud auth login` and use an account allowed to deploy Cloud Run services, use Cloud Build and Artifact Registry, and enable APIs in the target project.
3. Configure `frontend/.env` using `frontend/.env.example`. Do not commit this file. Set the Firebase web app values for the Firebase project already used by the application.
4. Configure `backend/.env` with the GCP project that owns the existing BigQuery dataset, Vertex AI access, and optional GCS trial data. The script reads `GCP_PROJECT` from this ignored file; it defaults to the Cloud Run project if absent.

## Deploy

From the repository root in PowerShell:

```powershell
./deploy/deploy-cloud-run.ps1
```

The default Cloud Run target is `quiet-terminal-422106` in `us-central1`. Override the project, region, service names, and runtime service account as needed:

```powershell
./deploy/deploy-cloud-run.ps1 -ProjectId "your-cloud-run-project" -Region "us-central1" -RuntimeServiceAccount "clinical-trial-runtime@your-cloud-run-project.iam.gserviceaccount.com"
```

The script deploys the API first, builds the frontend with that API URL, deploys the web service, then sets API CORS to the web service origin. Both services are internet reachable so users can load the UI and Firebase-authenticated requests can reach the API. Protected API endpoints still verify Firebase ID tokens.

## Runtime identity permissions

Cloud Run uses its runtime service account and Application Default Credentials; do not upload a service-account key. Grant the runtime identity only the roles needed for configured services:

- Firestore access in the Firebase project used by `FIREBASE_PROJECT_ID` (typically `roles/datastore.user`).
- BigQuery job execution and read access to the configured dataset (typically `roles/bigquery.jobUser` and dataset-level `roles/bigquery.dataViewer`).
- Vertex AI model access in the project configured by `GCP_PROJECT` (typically `roles/aiplatform.user`).
- `roles/storage.objectViewer` on the trial-data bucket only when `GCS_BUCKET` is configured.

If Firebase, BigQuery, Vertex AI, or GCS belongs to another project, grant access on that resource's project. Keep `FIREBASE_PROJECT_ID` and `GCP_PROJECT` set to the projects that own those resources; they do not have to match the Cloud Run deployment project.

After deployment, open the printed web URL and check the printed `/api/ready` URL. Read API logs with:

```powershell
gcloud run services logs read clinical-trial-api --project quiet-terminal-422106 --region us-central1
```
