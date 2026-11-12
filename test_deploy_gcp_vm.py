"""Tests for the Google Compute Engine VM deployment helper."""

import io
import tarfile
import unittest
from types import SimpleNamespace

import deploy_gcp_vm


class DeployGcpVmTest(unittest.TestCase):
    def test_bundle_includes_runtime_and_excludes_secrets(self):
        data = deploy_gcp_vm.bundle_bytes()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            names = set(archive.getnames())
            script_bytes = archive.extractfile("deploy_gcp_vm.sh").read()

        self.assertNotIn(b"\r\n", script_bytes)
        self.assertIn("Dockerfile", names)
        self.assertIn("docker-compose.yml", names)
        self.assertIn("deploy_gcp_vm.sh", names)
        self.assertIn("web_app.py", names)
        self.assertIn("chat/server.py", names)
        self.assertIn("frontend/package.json", names)
        self.assertIn("frontend/src/App.jsx", names)
        self.assertTrue(
            all(
                "deployment-private" not in name
                and ".env" not in name
                and "node_modules" not in name
                and "meta_model" not in name
                for name in names
            )
        )

    def test_build_commands_use_explicit_project_and_zone(self):
        args = SimpleNamespace(
            project="project-602a9d69-acff-43a0-a38",
            zone="us-central1-a",
            instance="claychat-vm",
            machine_type="e2-micro",
            boot_disk_size="30GB",
            boot_disk_type="pd-standard",
            tag="claychat-vm",
            firewall_rule="claychat-allow-web-tcp",
            enable_api=True,
        )
        cmds = deploy_gcp_vm.build_commands(args)
        self.assertEqual(cmds[0][:3], ["services", "enable", "compute.googleapis.com"])
        self.assertIn("project-602a9d69-acff-43a0-a38", cmds[0])
        self.assertEqual(cmds[1][:3], ["compute", "firewall-rules", "create"])
        self.assertEqual(cmds[2][:3], ["compute", "instances", "create"])
        self.assertIn("--zone=us-central1-a", cmds[2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
