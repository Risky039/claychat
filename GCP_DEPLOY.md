# Deploy ClayChat on Google Compute Engine (VM)

A Compute Engine VM runs the Docker Compose stack with persistent storage for SQLite (`/data/chat.db`) and uploaded attachments (`/data/uploads`), while exposing both the browser interface (`8080` / `80` / `443`) and the raw TCP server (`8765`).

- **Target GCP Project:** `project-602a9d69-acff-43a0-a38`
- **Default VM:** `e2-micro` (`debian-12`, `30GB` `pd-standard` boot disk) in `us-central1-a`

## 1. Enable Compute Engine API (one-time)

Before creating resources, make sure billing is linked to `project-602a9d69-acff-43a0-a38` and enable `compute.googleapis.com`:

```sh
gcloud services enable compute.googleapis.com --project project-602a9d69-acff-43a0-a38 --quiet
```

## 2. Preview or run the deployment script

Preview the exact `gcloud` commands first:

```sh
python deploy_gcp_vm.py --dry-run
```

Create the firewall rule (`80`, `443`, `8080`, `8765`), create the VM, upload the sanitized source bundle (secrets excluded), build the containers, and start the stack:

```sh
python deploy_gcp_vm.py
```

If you already enabled the API in step 1, omit `--enable-api`; or pass `--enable-api` to enable `compute.googleapis.com` as part of the run. Re-running `python deploy_gcp_vm.py` updates the existing VM in place while keeping `/etc/claychat.env` and the `claychat_data` Docker volume intact.

## 3. Configure Chunky AI and optional HTTPS domain

SSH into the VM and edit `/etc/claychat.env` (never commit keys or bake them into images):

```sh
gcloud compute ssh claychat-vm --project project-602a9d69-acff-43a0-a38 --zone=us-central1-a
```

On the VM:

```sh
sudo nano /etc/claychat.env
# Set MODEL_API_KEY=... (and optionally CHAT_DOMAIN=chat.example.com, CHAT_INVITE_CODE=...)
cd ~/claychat
sudo docker compose --env-file /etc/claychat.env up -d
```

- **Without a custom domain:** Open `http://VM_EXTERNAL_IP:8080` in a browser, or connect with `python chat_client.py alice --host VM_EXTERNAL_IP`.
- **With a custom domain:** Point an `A` DNS record to `VM_EXTERNAL_IP`, set `CHAT_DOMAIN=chat.example.com` in `/etc/claychat.env`, restart Compose, and open `https://chat.example.com` (Caddy provisions TLS automatically).

## 4. Verify

```sh
python smoke_remote.py VM_EXTERNAL_IP --port 8765
```

