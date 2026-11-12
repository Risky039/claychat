"""Provision or update a Google Compute Engine VM running ClayChat via Docker Compose.

Requires: Google Cloud SDK (`gcloud`) authenticated with `gcloud auth login` and
the Compute Engine API (`compute.googleapis.com`) enabled on the target project.
Secrets (`.env`, `deployment-private/`, keys) are never included in the uploaded bundle.
"""

import argparse
import io
import os
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

DEFAULT_PROJECT = "project-602a9d69-acff-43a0-a38"
DEFAULT_ZONE = "us-central1-a"
DEFAULT_INSTANCE = "claychat-vm"
DEFAULT_MACHINE_TYPE = "e2-micro"
DEFAULT_BOOT_DISK_SIZE = "30GB"
DEFAULT_BOOT_DISK_TYPE = "pd-standard"
DEFAULT_TAG = "claychat-vm"
DEFAULT_FIREWALL_RULE = "claychat-allow-web-tcp"

ROOT_FILES = (
    "Dockerfile",
    "docker-compose.yml",
    "Caddyfile",
    "requirements.txt",
    "deploy_gcp_vm.sh",
    "chat_server.py",
    "chat_client.py",
    "web_app.py",
)

FRONTEND_FILES = (
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "frontend/vite.config.js",
)


def find_gcloud():
    """Locate the gcloud CLI binary on PATH or standard Windows install paths."""
    found = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if found:
        return found
    local_app = os.environ.get("LOCALAPPDATA", "")
    candidate = Path(local_app) / "Google" / "Cloud SDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError("Could not find `gcloud` on PATH")


def bundle_bytes(root=None):
    """Build a gzipped tar archive containing only source and Docker build files."""
    root = Path(root) if root else Path(__file__).resolve().parent
    bundle = io.BytesIO()
    with tarfile.open(fileobj=bundle, mode="w:gz") as archive:
        for relative in ROOT_FILES:
            archive.add(root / relative, arcname=relative)
        for path in sorted((root / "chat").rglob("*.py")):
            if "__pycache__" not in path.parts:
                archive.add(path, arcname=path.relative_to(root).as_posix())
        for relative in FRONTEND_FILES:
            archive.add(root / relative, arcname=relative)
        for path in sorted((root / "frontend" / "src").rglob("*")):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(root).as_posix())
    return bundle.getvalue()


def build_commands(args, bundle_path="~/claychat-bundle.tar.gz"):
    """Return the ordered list of gcloud commands needed to provision and deploy."""
    cmds = []
    if args.enable_api:
        cmds.append([
            "services", "enable", "compute.googleapis.com",
            "--project", args.project, "--quiet",
        ])
    cmds.append([
        "compute", "firewall-rules", "create", args.firewall_rule,
        "--project", args.project,
        "--allow=tcp:80,tcp:443,tcp:8080,tcp:8765",
        "--direction=INGRESS",
        "--source-ranges=0.0.0.0/0",
        f"--target-tags={args.tag}",
        "--description=Allow HTTP/HTTPS, ClayChat web (8080), and raw TCP chat (8765)",
        "--quiet",
    ])
    cmds.append([
        "compute", "instances", "create", args.instance,
        "--project", args.project,
        f"--zone={args.zone}",
        f"--machine-type={args.machine_type}",
        "--image-family=debian-12",
        "--image-project=debian-cloud",
        f"--boot-disk-size={args.boot_disk_size}",
        f"--boot-disk-type={args.boot_disk_type}",
        f"--tags={args.tag}",
        "--quiet",
    ])
    cmds.append([
        "compute", "scp", str(bundle_path), f"{args.instance}:~/claychat-bundle.tar.gz",
        "--project", args.project, f"--zone={args.zone}", "--quiet",
    ])
    cmds.append([
        "compute", "ssh", args.instance,
        "--project", args.project, f"--zone={args.zone}",
        "--command=mkdir -p ~/claychat && tar -xzf ~/claychat-bundle.tar.gz -C ~/claychat && rm -f ~/claychat-bundle.tar.gz && bash ~/claychat/deploy_gcp_vm.sh",
        "--quiet",
    ])
    return cmds


def run_gcloud(gcloud, args, check=True):
    """Execute a gcloud subcommand and optionally raise on non-zero exit."""
    result = subprocess.run([gcloud, *args], check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"gcloud command failed ({result.returncode}): {' '.join(args[:4])}")
    return result.returncode


def capture_gcloud(gcloud, args):
    """Execute a gcloud subcommand and return (returncode, stdout)."""
    result = subprocess.run([gcloud, *args], capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip()


def wait_for_ssh(gcloud, instance, project, zone, attempts=18):
    """Wait until SSH is accepting connections on a newly created VM."""
    for _ in range(attempts):
        rc, _ = capture_gcloud(
            gcloud,
            ["compute", "ssh", instance, "--project", project, f"--zone={zone}", "--command=true", "--quiet"],
        )
        if rc == 0:
            return
        time.sleep(5)
    raise TimeoutError(f"SSH did not become ready on {instance} ({zone})")


def main():
    parser = argparse.ArgumentParser(description="Deploy ClayChat on a Google Compute Engine VM")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT))
    parser.add_argument("--zone", default=os.getenv("GOOGLE_CLOUD_ZONE", DEFAULT_ZONE))
    parser.add_argument("--instance", default=DEFAULT_INSTANCE)
    parser.add_argument("--machine-type", default=DEFAULT_MACHINE_TYPE)
    parser.add_argument("--boot-disk-size", default=DEFAULT_BOOT_DISK_SIZE)
    parser.add_argument("--boot-disk-type", default=DEFAULT_BOOT_DISK_TYPE)
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--firewall-rule", default=DEFAULT_FIREWALL_RULE)
    parser.add_argument("--enable-api", action="store_true", help="Enable compute.googleapis.com before creating resources")
    parser.add_argument("--dry-run", action="store_true", help="Print gcloud commands without executing them")
    args = parser.parse_args()

    if args.dry_run:
        for cmd in build_commands(args):
            print("gcloud " + " ".join(shlex.quote(part) for part in cmd))
        return

    gcloud = find_gcloud()
    if args.enable_api:
        print(f"Enabling compute.googleapis.com on {args.project}...", flush=True)
        run_gcloud(gcloud, ["services", "enable", "compute.googleapis.com", "--project", args.project, "--quiet"])

    fw_rc, _ = capture_gcloud(
        gcloud,
        ["compute", "firewall-rules", "describe", args.firewall_rule, "--project", args.project, "--quiet"],
    )
    if fw_rc != 0:
        print(f"Creating firewall rule {args.firewall_rule}...", flush=True)
        run_gcloud(
            gcloud,
            [
                "compute", "firewall-rules", "create", args.firewall_rule,
                "--project", args.project,
                "--allow=tcp:80,tcp:443,tcp:8080,tcp:8765",
                "--direction=INGRESS",
                "--source-ranges=0.0.0.0/0",
                f"--target-tags={args.tag}",
                "--description=Allow HTTP/HTTPS, ClayChat web (8080), and raw TCP chat (8765)",
                "--quiet",
            ],
        )

    inst_rc, _ = capture_gcloud(
        gcloud,
        ["compute", "instances", "describe", args.instance, "--project", args.project, f"--zone={args.zone}", "--quiet"],
    )
    if inst_rc != 0:
        print(f"Creating Compute Engine VM {args.instance} ({args.machine_type}) in {args.zone}...", flush=True)
        run_gcloud(
            gcloud,
            [
                "compute", "instances", "create", args.instance,
                "--project", args.project,
                f"--zone={args.zone}",
                f"--machine-type={args.machine_type}",
                "--image-family=debian-12",
                "--image-project=debian-cloud",
                f"--boot-disk-size={args.boot_disk_size}",
                f"--boot-disk-type={args.boot_disk_type}",
                f"--tags={args.tag}",
                "--quiet",
            ],
        )
        print("Waiting for SSH readiness...", flush=True)
        wait_for_ssh(gcloud, args.instance, args.project, args.zone)

    payload = bundle_bytes()
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp.write(payload)
        bundle_path = Path(tmp.name)

    try:
        print("Uploading source bundle to VM...", flush=True)
        run_gcloud(
            gcloud,
            [
                "compute", "scp", str(bundle_path), f"{args.instance}:~/claychat-bundle.tar.gz",
                "--project", args.project, f"--zone={args.zone}", "--quiet",
            ],
        )
    finally:
        bundle_path.unlink(missing_ok=True)

    print("Building and starting Docker Compose stack on VM...", flush=True)
    run_gcloud(
        gcloud,
        [
            "compute", "ssh", args.instance,
            "--project", args.project, f"--zone={args.zone}",
            "--command=mkdir -p ~/claychat && tar -xzf ~/claychat-bundle.tar.gz -C ~/claychat && rm -f ~/claychat-bundle.tar.gz && bash ~/claychat/deploy_gcp_vm.sh",
            "--quiet",
        ],
    )

    _, ip = capture_gcloud(
        gcloud,
        [
            "compute", "instances", "describe", args.instance,
            "--project", args.project,
            f"--zone={args.zone}",
            "--format=value(networkInterfaces[0].accessConfigs[0].natIP)",
            "--quiet",
        ],
    )
    print(f"Deployed! Web UI: http://{ip}:8080 | Raw TCP: {ip}:8765", flush=True)
    print(
        f"To add MODEL_API_KEY or CHAT_DOMAIN, SSH in and edit /etc/claychat.env:\n"
        f"  gcloud compute ssh {args.instance} --project {args.project} --zone={args.zone}",
        flush=True,
    )


if __name__ == "__main__":
    main()

