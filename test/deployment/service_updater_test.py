from cloudlift.deployment.service_updater import ServiceUpdater
from unittest import mock, TestCase
import boto3


class TestServiceUpdate(TestCase):
    def setUp(self):
        patcher = mock.patch.object(boto3.session.Session, 'client')
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_build_command_without_build_args(self):
        su = ServiceUpdater("dummy", "test", None, None)
        assert 'docker build -t test:v1 .' == su._build_command("test:v1")

    def test_build_command_with_build_args(self):
        su = ServiceUpdater("dummy", "test", None, None, build_args={"SSH_KEY": "\"`cat ~/.ssh/id_rsa`\"", "A": "1"})
        assert su._build_command("test:v1") == 'docker build -t test:v1 --build-arg SSH_KEY="`cat ~/.ssh/id_rsa`"' \
                                               ' --build-arg A=1 .'

    def test_use_dockerfile_with_build_args(self):
        su = ServiceUpdater("dummy", "test", None, None, build_args={"SSH_KEY": "\"`cat ~/.ssh/id_rsa`\"", "A": "1"},
                            dockerfile='CustomDockerfile')
        assert su._build_command("test:v1") == 'docker build -f CustomDockerfile -t test:v1 ' \
                                               '--build-arg SSH_KEY="`cat ~/.ssh/id_rsa`" --build-arg A=1 .'

    def test_build_command_with_dockerfile_without_build_args(self):
        su = ServiceUpdater("dummy", "test", None, None, None, dockerfile='CustomDockerfile')
        assert 'docker build -f CustomDockerfile -t test:v1 .' == su._build_command("test:v1")
