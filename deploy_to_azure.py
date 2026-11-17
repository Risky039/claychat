"""Deploy ClayChat to Azure VM using Paramiko."""
import io
import os
import tarfile
from pathlib import Path
import paramiko
from scp import SCPClient

HOST = "20.11.8.40"
USER = "azureuser"
KEY_PATH = os.path.expandvars(r"$USERPROFILE\.ssh\claychat_azure.pem")

ROOT_DIR = Path(__file__).resolve().parent

def make_bundle():
    print("Building in-memory source tarball...")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for fname in ["chat_server.py", "chat_client.py", "web_app.py", "deploy_azure_vm.sh", "requirements.txt"]:
            fpath = ROOT_DIR / fname
            if fpath.is_file():
                tar.add(fpath, arcname=fname)
        
        # chat package
        chat_dir = ROOT_DIR / "chat"
        for p in chat_dir.rglob("*.py"):
            if "__pycache__" not in p.parts:
                tar.add(p, arcname=p.relative_to(ROOT_DIR).as_posix())
        
        # dist directory
        dist_dir = ROOT_DIR / "frontend" / "dist"
        if not (dist_dir / "index.html").is_file():
            raise RuntimeError("frontend/dist/index.html missing! Run npm run build first.")
        for p in dist_dir.rglob("*"):
            if p.is_file():
                tar.add(p, arcname=p.relative_to(ROOT_DIR).as_posix())
                
    buf.seek(0)
    return buf

def main():
    print(f"Connecting to {USER}@{HOST} with key {KEY_PATH}...")
    k = paramiko.RSAKey.from_private_key_file(KEY_PATH)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, pkey=k, timeout=20)
    print("Connected successfully!")
    
    bundle_io = make_bundle()
    bundle_bytes = bundle_io.getvalue()
    print(f"Tarball size: {len(bundle_bytes)} bytes")
    
    sftp = ssh.open_sftp()
    print("Uploading tarball...")
    with sftp.open("/home/azureuser/tcp-chat.tar.gz", "wb") as f:
        f.write(bundle_bytes)
    sftp.close()
    print("Uploaded tarball to /home/azureuser/tcp-chat.tar.gz")
    
    cmd = (
        "rm -rf ~/tcp-chat && mkdir -p ~/tcp-chat && "
        "tar -xzf ~/tcp-chat.tar.gz -C ~/tcp-chat && rm ~/tcp-chat.tar.gz && "
        "sed -i 's/\\r$//' ~/tcp-chat/deploy_azure_vm.sh && "
        "bash ~/tcp-chat/deploy_azure_vm.sh"
    )
    print(f"Running installation and startup script on VM...")
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    for line in iter(stdout.readline, ""):
        print("REMOTE:", line.rstrip())
    rc = stdout.channel.recv_exit_status()
    print(f"Remote command completed with exit status: {rc}")
    
    # check service status
    _, out, _ = ssh.exec_command("sudo systemctl status tcp-chat --no-pager")
    print("\n--- Service Status ---")
    print(out.read().decode())
    
    ssh.close()

if __name__ == "__main__":
    main()

