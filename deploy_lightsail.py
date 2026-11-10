"""Create a Lightsail chat instance from a private S3 deployment bundle.

Requires: pip install boto3. The Meta key is never included in the bundle.
"""

import hashlib
import io
import os
import shlex
import tarfile
import time
import uuid
from pathlib import Path

REGION = "us-east-1"
ZONE = "us-east-1a"
NAME = "tcp-chat-assignment-20261110"
PORT = 8765


def bundle_bytes():
    root = Path(__file__).resolve().parent
    bundle = io.BytesIO()
    with tarfile.open(fileobj=bundle, mode="w:gz") as archive:
        for relative in ("chat_server.py", "web_app.py"):
            archive.add(root / relative, arcname=relative)
        dist = root / "frontend" / "dist"
        if not (dist / "index.html").is_file():
            raise FileNotFoundError("Build the React frontend first: cd frontend; npm install; npm run build")
        archive.add(dist, arcname="frontend/dist")
    return bundle.getvalue()


def user_data(download_url, bundle_sha256):
    quoted_url = shlex.quote(download_url)
    return f"""#!/bin/bash
set -euo pipefail
apt-get update
apt-get install -y python3 python3-aiohttp curl
mkdir -p /opt/tcp-chat
curl --fail --location --retry 5 --retry-delay 2 {quoted_url} -o /tmp/tcp-chat.tar.gz
echo '{bundle_sha256}  /tmp/tcp-chat.tar.gz' | sha256sum --check
tar -xz -C /opt/tcp-chat -f /tmp/tcp-chat.tar.gz
rm /tmp/tcp-chat.tar.gz
cat > /etc/systemd/system/tcp-chat.service <<'UNIT'
[Unit]
Description=Python TCP chat and WebSocket gateway
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/tcp-chat
EnvironmentFile=-/etc/tcp-chat.env
ExecStart=/usr/bin/python3 /opt/tcp-chat/web_app.py --tcp-host 0.0.0.0 --tcp-port {PORT} --web-host 0.0.0.0 --web-port 8080
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
[Install]
WantedBy=multi-user.target
UNIT
chown -R ubuntu:ubuntu /opt/tcp-chat
systemctl daemon-reload
systemctl enable --now tcp-chat
"""


def main():
    import boto3

    session = boto3.Session(region_name=REGION)
    client = session.client("lightsail")
    s3 = session.client("s3")
    account = session.client("sts").get_caller_identity()["Account"]
    bucket = os.getenv("CHAT_DEPLOY_BUCKET") or f"tcp-chat-deploy-{account}-{uuid.uuid4().hex[:12]}"
    if not os.getenv("CHAT_DEPLOY_BUCKET"):
        s3.create_bucket(Bucket=bucket)
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        s3.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
        )
    bundle = bundle_bytes()
    key = f"releases/{uuid.uuid4().hex}.tar.gz"
    s3.upload_fileobj(
        io.BytesIO(bundle), bucket, key,
        ExtraArgs={"ContentType": "application/gzip", "ServerSideEncryption": "AES256"},
    )
    download_url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
    client.create_instances(
        instanceNames=[NAME],
        availabilityZone=ZONE,
        blueprintId="ubuntu_24_04",
        bundleId="nano_3_0",
        userData=user_data(download_url, hashlib.sha256(bundle).hexdigest()),
        tags=[{"key": "Project", "value": "tcp-chat-assignment"}],
    )
    for _ in range(30):
        instance = client.get_instance(instanceName=NAME)["instance"]
        if instance["state"]["name"] == "running":
            break
        time.sleep(10)
    else:
        raise TimeoutError("Instance did not reach running state; check Lightsail console")
    for port in (PORT, 8080):
        client.open_instance_public_ports(
            instanceName=NAME,
            portInfos=[{"fromPort": port, "toPort": port, "protocol": "tcp"}],
        )
    ip = instance.get("publicIpAddress")
    print(f"Created {NAME}. TCP: {ip}:8765; web: http://{ip}:8080. Wait for first boot before connecting.")
    print(f"Private deployment bundle: s3://{bucket}/{key}")


if __name__ == "__main__":
    main()
