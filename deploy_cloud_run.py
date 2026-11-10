"""Deploy ClayChat to Google Cloud Run from source.

Requires: Google Cloud SDK (`gcloud`) authenticated with `gcloud auth login`.
The Meta Model API key is never baked into the container image; if present in
`MODEL_API_KEY` or `deployment-private/meta_model_api_key`, it is passed at
runtime to the Cloud Run service environment.
"""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from chat.config import load_api_key

DEFAULT_PROJECT = "project-602a9d69-acff-43a0-a38"
DEFAULT_REGION = "us-central1"
DEFAULT_SERVICE = "claychat"


def find_gcloud():
    found = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if found:
        return found
    local_app = os.environ.get("LOCALAPPDATA", "")
    candidate = Path(local_app) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError("Could not find `gcloud` on PATH")


def run_gcloud(gcloud, args, env):
    cmd = [gcloud, *args]
    result = subprocess.run(cmd, env=env, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"gcloud command failed with exit code {result.returncode}: {' '.join(args[:4])}")


def main():
    parser = argparse.ArgumentParser(description="Deploy ClayChat to Google Cloud Run")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT))
    parser.add_argument("--region", default=os.getenv("GOOGLE_CLOUD_REGION", DEFAULT_REGION))
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    args = parser.parse_args()

    gcloud = find_gcloud()
    env = os.environ.copy()
    existing_metrics = env.get("CLOUDSDK_METRICS_ENVIRONMENT", "").strip()
    env["CLOUDSDK_METRICS_ENVIRONMENT"] = (
        f"{existing_metrics} datacloud.antigravity".strip() if existing_metrics else "datacloud.antigravity"
    )

    print(f"Setting active project to {args.project}...", flush=True)
    run_gcloud(gcloud, ["config", "set", "project", args.project, "--quiet"], env)

    print("Enabling Cloud Run, Cloud Build, and Artifact Registry APIs...", flush=True)
    run_gcloud(
        gcloud,
        [
            "services",
            "enable",
            "run.googleapis.com",
            "cloudbuild.googleapis.com",
            "artifactregistry.googleapis.com",
            "--project",
            args.project,
            "--quiet",
        ],
        env,
    )

    deploy_args = [
        "run",
        "deploy",
        args.service,
        "--source",
        ".",
        "--project",
        args.project,
        "--region",
        args.region,
        "--platform",
        "managed",
        "--allow-unauthenticated",
        "--port",
        "8080",
        "--max-instances",
        "1",
        "--session-affinity",
        "--timeout",
        "3600",
        "--quiet",
    ]
    api_key = load_api_key()
    if api_key:
        deploy_args.extend(["--set-env-vars", f"MODEL_API_KEY={api_key}"])

    print(f"Deploying {args.service} to Cloud Run ({args.region})...", flush=True)
    run_gcloud(gcloud, deploy_args, env)


if __name__ == "__main__":
    main()
