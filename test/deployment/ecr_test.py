from cloudlift.deployment import ECR
from unittest import TestCase
import boto3
import json
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
             "Action": ["ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage"]}]}

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