from cloudlift.deployment import ECR
from unittest import TestCase
import boto3
import json
import os
from unittest.mock import patch, MagicMock, call


class TestECR(TestCase):
    def setUp(self):
        patcher = patch.object(boto3.session.Session, 'client')
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_build_command_without_build_args(self):
        ecr = ECR("aws-region", "test-repo", "12345", None, None)
        assert 'docker build -t test:v1 .' == ecr._build_command("test:v1")

    def test_build_command_with_build_args(self):
        ecr = ECR("aws-region", "test-repo", "12345", None, None,
                  build_args={"SSH_KEY": "\"`cat ~/.ssh/id_rsa`\"", "A": "1"})
        assert ecr._build_command("test:v1") == 'docker build -t test:v1 --build-arg SSH_KEY="`cat ~/.ssh/id_rsa`"' \
                                                ' --build-arg A=1 .'

    def test_use_dockerfile_with_build_args(self):
        ecr = ECR("aws-region", "test-repo", "12345", None, None,
                  build_args={"SSH_KEY": "\"`cat ~/.ssh/id_rsa`\"", "A": "1"}, dockerfile='CustomDockerfile')
        assert ecr._build_command("test:v1") == 'docker build -f CustomDockerfile -t test:v1 ' \
                                                '--build-arg SSH_KEY="`cat ~/.ssh/id_rsa`" --build-arg A=1 .'

    def test_build_command_with_dockerfile_without_build_args(self):
        ecr = ECR("aws-region", "test-repo", "12345", None, None, dockerfile='CustomDockerfile')
        assert 'docker build -f CustomDockerfile -t test:v1 .' == ecr._build_command("test:v1")

    def test_build_command_with_cache_from(self):
        ecr = ECR("aws-region", "test-repo", "12345", version="v1", cache_from=['image1', 'image2'])
        assert 'docker build -t test:v1 --cache-from image1 --cache-from image2 .' == ecr._build_command("test:v1")

    def test_should_enable_buildkit(self):
        self.assertTrue(
            ECR("aws-region", "test-repo", "12345",
                cache_from=['image1', 'image2'])._should_enable_buildkit()
        )
        self.assertFalse(
            ECR("aws-region", "test-repo", "12345")._should_enable_buildkit()
        )
        self.assertTrue(
            ECR("aws-region", "test-repo", "12345", ssh="/tmp/sock")._should_enable_buildkit()
        )

    @patch("cloudlift.deployment.ecr.subprocess")
    @patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=True)
    def test_build_with_ssh(self, mock_subprocess):
        ecr = ECR("aws-region", "test-repo", version="12345", ssh="default=$SSH_AUTH_SOCK")
        ecr._build_image()

        mock_subprocess.check_call.assert_called_with(
            'docker build -t test-repo:12345 --ssh default=$SSH_AUTH_SOCK .', env={'DOCKER_BUILDKIT': '1',
                                                                                   'PATH': '/usr/bin'}, shell=True,
        )

    @patch("boto3.session.Session")
    @patch("boto3.client")
    def test_if_ecr_assumes_given_role_arn(self, mock_boto_client, mock_session):
        assume_role_arn = 'test-assume-role-arn'
        mock_sts_client = MagicMock()
        mock_boto_client.return_value = mock_sts_client
        mock_sts_client.assume_role.return_value = {
            'Credentials': {
                'AccessKeyId': 'mockAccessKeyId', 'SecretAccessKey': 'mockSecretAccessKey',
                'SessionToken': 'mockSessionToken'
            }
        }

        ECR("aws-region", "test-repo", "12345", assume_role_arn=assume_role_arn)

        mock_sts_client.assume_role.assert_called_with(RoleArn=assume_role_arn, RoleSessionName='ecrCloudliftAgent')
        mock_session.assert_called_with(
            aws_access_key_id='mockAccessKeyId',
            aws_secret_access_key='mockSecretAccessKey',
            aws_session_token='mockSessionToken',
        )

    @patch("cloudlift.deployment.ecr.get_account_id")
    @patch("cloudlift.deployment.ecr._create_ecr_client")
    def test_ensure_repository_without_cross_account_access(self, mock_create_ecr_client, mock_get_account_id):
        mock_ecr_client = MagicMock()
        mock_create_ecr_client.return_value = mock_ecr_client
        mock_get_account_id.return_value = "12345"

        ecr = ECR("aws-region", "test-repo", "12345")

        ecr.ensure_repository()

        mock_ecr_client.create_repository.assert_called_with(
            repositoryName='test-repo',
            imageScanningConfiguration={'scanOnPush': True}
        )

        mock_ecr_client.set_repository_policy.assert_not_called()

    @patch("cloudlift.deployment.ecr.get_account_id")
    @patch("cloudlift.deployment.ecr._create_ecr_client")
    def test_ensure_repository_with_cross_account_access(self, mock_create_ecr_client, mock_get_account_id):
        mock_ecr_client = MagicMock()
        mock_create_ecr_client.return_value = mock_ecr_client
        mock_get_account_id.return_value = "98765"

        ecr = ECR("aws-region", "test-repo", "12345")

        ecr.ensure_repository()

        mock_ecr_client.create_repository.assert_called_with(
            repositoryName='test-repo',
            imageScanningConfiguration={'scanOnPush': True}
        )

        expected_policy_text = {"Version": "2008-10-17", "Statement": [
            {"Sid": "AllowCrossAccountPull-98765", "Effect": "Allow", "Principal": {"AWS": ["98765"]},
             "Action": ["ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage",
                        "ecr:InitiateLayerUpload", "ecr:PutImage", "ecr:UploadLayerPart",
                        "ecr:CompleteLayerUpload"]}]}

        mock_ecr_client.set_repository_policy.assert_called_with(
            repositoryName='test-repo',
            policyText=json.dumps(expected_policy_text),
        )

    def test_image_uri(self):
        ecr = ECR("aws-region", "target-repo", "acc-id", version="v1")

        self.assertEqual("acc-id.dkr.ecr.aws-region.amazonaws.com/target-repo:v1", ecr.image_uri)

    def test_repo_path(self):
        ecr = ECR("aws-region", "target-repo", "acc-id", version="v1")

        self.assertEqual("acc-id.dkr.ecr.aws-region.amazonaws.com/target-repo", ecr.repo_path)

    def test_local_image_uri(self):
        ecr = ECR("aws-region", "target-repo", "acc-id", version="v1")

        self.assertEqual("target-repo:v1", ecr.local_image_uri)

    @patch("cloudlift.deployment.ecr.subprocess")
    @patch("cloudlift.deployment.ecr._create_ecr_client")
    def test_ensure_image_in_ecr_for_explicit_version(self, mock_create_ecr_client, mock_subprocess):
        mock_ecr_client = MagicMock()
        mock_create_ecr_client.return_value = mock_ecr_client
        mock_ecr_client.batch_get_image.return_value = {'images': 'image-01'}

        def mock_check_output(cmd):
            if " ".join(cmd) == "git rev-list -n 1 HEAD":
                mock = MagicMock()
                mock.strip.return_value.decode.return_value = Exception('mocked error')
                return mock

            if " ".join(cmd) == 'git show -s --format="%ct" HEAD':
                mock = MagicMock()
                mock.strip.return_value.decode.return_value = '"1602236172"'
                return mock

            mock = MagicMock()
            mock.decode.return_value = None
            return mock

        mock_subprocess.check_output.side_effect = mock_check_output

        ecr = ECR("aws-region", "target-repo", "acc-id", version="v1")

        ecr.ensure_image_in_ecr()

        mock_ecr_client.batch_get_image.assert_called_with(
            imageIds=[{'imageTag': 'v1'}], repositoryName='target-repo',
        )

    @patch("cloudlift.deployment.ecr.log_intent")
    @patch("cloudlift.deployment.ecr.subprocess")
    @patch("cloudlift.deployment.ecr._create_ecr_client")
    def test_ensure_image_in_ecr_for_derived_version_with_image_in_ecr(self, mock_create_ecr_client,
                                                                       mock_subprocess, mock_log_intent):
        mock_ecr_client = MagicMock()
        mock_create_ecr_client.return_value = mock_ecr_client
        mock_ecr_client.batch_get_image.return_value = {'images': [{'imageManifest': 'manifest-01'}]}

        mock_subprocess.check_output.side_effect = _mock_git_calls

        ecr = ECR("aws-region", "target-repo", "acc-id")

        ecr.ensure_image_in_ecr()

        mock_log_intent.assert_has_calls([call('Image found in ECR')])
        mock_ecr_client.put_image.assert_has_calls([
            call(imageManifest='manifest-01', imageTag='v1', repositoryName='target-repo'),
            call(imageManifest='manifest-01', imageTag='v1-1602236172', repositoryName='target-repo'),
        ])

    @patch("cloudlift.deployment.ecr.subprocess")
    @patch("cloudlift.deployment.ecr._create_ecr_client")
    @patch.dict(os.environ, {'ENV': 'test'}, clear=True)
    def test_ensure_image_in_ecr_for_derived_version_with_image_not_in_ecr(self, mock_create_ecr_client,
                                                                           mock_subprocess):
        mock_ecr_client = MagicMock()
        mock_create_ecr_client.return_value = mock_ecr_client
        mock_ecr_client.batch_get_image.side_effect = [
            {'images': []},
            {'images': [{'imageManifest': 'manifest-01'}]},
            {'images': [{'imageManifest': 'manifest-01'}]},
        ]

        mock_ecr_client.get_authorization_token.return_value = {
            'authorizationData': [
                {'authorizationToken': 'dXNlcjp0b2tlbgo=', 'proxyEndpoint': 'http://proxy'}
            ]
        }

        mock_subprocess.check_output.side_effect = _mock_git_calls

        ecr = ECR("aws-region", "target-repo", "acc-id")

        ecr.ensure_image_in_ecr()

        self.assertEqual('acc-id.dkr.ecr.aws-region.amazonaws.com/target-repo:v1', ecr.image_uri)
        mock_subprocess.check_call.assert_has_calls([
            call(['docker', 'tag', 'target-repo:v1',
                  'acc-id.dkr.ecr.aws-region.amazonaws.com/target-repo:v1']),
        ])
        mock_ecr_client.put_image.assert_has_calls([
            call(imageManifest='manifest-01', imageTag='v1', repositoryName='target-repo'),
            call(imageManifest='manifest-01', imageTag='v1-1602236172', repositoryName='target-repo'),
        ]

        )

    @patch("cloudlift.deployment.ecr.subprocess")
    @patch("cloudlift.deployment.ecr._create_ecr_client")
    @patch.dict(os.environ, {'ENV': 'test'}, clear=True)
    def test_ensure_image_in_ecr_with_image_not_in_ecr_built_with_custom_dockerfile(self,
                                                                                    mock_create_ecr_client,
                                                                                    mock_subprocess):
        mock_ecr_client = MagicMock()
        mock_create_ecr_client.return_value = mock_ecr_client
        mock_ecr_client.batch_get_image.side_effect = [
            {'images': []},
            {'images': [{'imageManifest': 'manifest-01'}]},
        ]

        mock_ecr_client.get_authorization_token.return_value = {
            'authorizationData': [
                {'authorizationToken': 'dXNlcjp0b2tlbgo=', 'proxyEndpoint': 'http://proxy'}
            ]
        }

        mock_subprocess.check_output.side_effect = _mock_git_calls

        ecr = ECR("aws-region", "target-repo", "acc-id", dockerfile='CustomDockerFile')

        ecr.ensure_image_in_ecr()

        mock_subprocess.check_call.assert_has_calls([
            call(['docker', 'tag', 'target-repo:v1-CustomDockerFile',
                  'acc-id.dkr.ecr.aws-region.amazonaws.com/target-repo:v1-CustomDockerFile']),
        ])

        self.assertEqual('acc-id.dkr.ecr.aws-region.amazonaws.com/target-repo:v1-CustomDockerFile', ecr.image_uri)
        mock_ecr_client.put_image.assert_called_with(
            imageManifest='manifest-01', imageTag='v1-CustomDockerFile', repositoryName='target-repo',
        )


def _mock_git_calls(cmd, rev_list=None, epoch=None):
    if " ".join(cmd) == "git rev-list -n 1 HEAD":
        mock = MagicMock()
        mock.strip.return_value.decode.return_value = rev_list or "v1"
        return mock

    if " ".join(cmd) == 'git show -s --format="%ct" HEAD':
        mock = MagicMock()
        mock.strip.return_value.decode.return_value = epoch or '"1602236172"'
        return mock

    mock = MagicMock()
    mock.decode.return_value = None
    return mock
