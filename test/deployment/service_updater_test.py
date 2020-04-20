import unittest

from cloudlift.deployment.service_updater import ServiceUpdater


class TestServiceUpdate(unittest.TestCase):
    def test_build_command_without_build_args(self):
        su = ServiceUpdater("dummy", "test", None, None)
        self.assertEqual('docker build -t test:v1 .'.split(), su._build_command("test:v1"))

    def test_build_command_wit_build_args(self):
        su = ServiceUpdater("dummy", "test", None, None, {"SSH_KEY": "\"`cat ~/.ssh/id_rsa`\"", "A": "1"})
        self.assertEqual('docker build -t test:v1 --build-arg SSH_KEY="`cat ~/.ssh/id_rsa`" --build-arg A=1 .'.split(), su._build_command("test:v1"))
