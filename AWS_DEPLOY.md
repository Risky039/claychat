# Deploy ClayChat on Amazon Web Services (AWS)

There are two primary ways to run ClayChat on AWS:

---

## Option 1: AWS Lightsail (Fastest & Simplest)

AWS Lightsail is a virtual private server (VPS) that includes compute, storage, DNS, and a public static IPv4 address with straightforward, predictable monthly pricing ($3.50–$5.00/mo, with a 3-month free trial on eligible plans).

### In the AWS Management Console:
1. Go to **[lightsail.aws.amazon.com](https://lightsail.aws.amazon.com/)**.
2. Click **Create instance**.
3. Select:
   * **Instance location:** Any region close to you (e.g., `us-east-1`).
   * **Platform:** Linux/Unix.
   * **Blueprint:** **Ubuntu 24.04 LTS** (or 22.04 LTS) under "OS Only".
   * **Instance plan:** Select the lowest tier ($3.50 or $5/month, 512MB–1GB RAM, free for first 90 days).
   * **Instance name:** `claychat-lightsail`.
4. Click **Create instance**.
5. Once running, open the instance, go to the **Networking** tab, and under **IPv4 Firewall**, click **Add rule**:
   * Add Custom **TCP 8080** (Web interface & WebSocket gateway).
   * Add Custom **TCP 8765** (Raw TCP chat clients).
   * Keep **SSH 22** open.

---

## Option 2: AWS EC2 (Free Tier Eligible)

AWS EC2 includes 750 hours per month of `t2.micro` or `t3.micro` instances under the 12-Month AWS Free Tier.

### In the AWS Management Console:
1. Go to **[console.aws.amazon.com/ec2](https://console.aws.amazon.com/ec2/)**.
2. Click **Launch Instance**:
   * **Name:** `claychat-ec2`.
   * **AMI:** **Ubuntu Server 24.04 LTS** (Free tier eligible).
   * **Instance type:** `t2.micro` (or `t3.micro` depending on region, Free tier eligible).
   * **Key pair:** Create a new key pair (e.g. `claychat-key.pem`) and save it to `C:\Users\Aaron\.ssh\claychat-key.pem`.
   * **Network settings (Firewall / Security Group):**
     * Allow SSH traffic from Anywhere (0.0.0.0/0).
     * Add security group rule: **Custom TCP**, Port **8080**, Source **0.0.0.0/0** (Web).
     * Add security group rule: **Custom TCP**, Port **8765**, Source **0.0.0.0/0** (Chat).
3. Click **Launch Instance**.

---

## Deploying Your Code to the Instance (From PowerShell)

Once your Lightsail or EC2 instance is running and has a **Public IPv4 address**:

### 1. Build the Frontend
```powershell
Set-Location 'C:\Users\Aaron\Downloads\New folder (6)'
cd frontend
npm ci
npm run build
cd ..
```

### 2. Upload and Run via SSH

Replace `YOUR_INSTANCE_IP` and the key path:

```powershell
$instanceIp = "YOUR_INSTANCE_IP"
$sshKey = "C:\Users\Aaron\.ssh\claychat-key.pem"

# Create destination folder and upload
ssh -i $sshKey -o StrictHostKeyChecking=no "ubuntu@$instanceIp" "mkdir -p ~/tcp-chat/frontend"
scp -i $sshKey -r chat chat_server.py chat_client.py web_app.py deploy_azure_vm.sh "ubuntu@${instanceIp}:~/tcp-chat/"
scp -i $sshKey -r frontend/dist "ubuntu@${instanceIp}:~/tcp-chat/frontend/"

# Run the setup script (installs aiohttp, systemd service, auto-restart)
ssh -i $sshKey "ubuntu@$instanceIp" "bash ~/tcp-chat/deploy_azure_vm.sh"
```
*(Note: `deploy_azure_vm.sh` is a standard Ubuntu systemd service installer that works identically on AWS Ubuntu instances).*

### 3. (Optional) Set up Chunky AI
On the instance:
```sh
sudo install -m 600 -o root -g root /dev/null /etc/tcp-chat.env
sudo nano /etc/tcp-chat.env
# Add: MODEL_API_KEY=your_meta_model_key
sudo systemctl restart tcp-chat
```

---

## Verifying the Deployment
* Open browser: `http://YOUR_INSTANCE_IP:8080`
* Run remote two-user verification:
  ```powershell
  python smoke_remote.py YOUR_INSTANCE_IP --port 8765
  ```
