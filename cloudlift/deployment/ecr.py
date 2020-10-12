import base64
import subprocess

import boto3
import json
from stringcase import spinalcase
import os

from cloudlift.config.logging import log_bold, log_err, log_intent, log_warning
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config.account import get_account_id

ECR_DOCKER_PATH = "{}.dkr.ecr.{}.amazonaws.com/{}"
DEFAULT_DOCKER_FILE = "Dockerfile"


class ECR:
    def __init__(self, region, repo_name, account_id=None, assume_role_arn=None, version=None,
                 build_args=None, dockerfile=None, working_dir='.', ssh=None, cache_from=None):
        self.repo_name = repo_name
        self.region = region
        self.account_id = account_id or get_account_id()
        self.client = _create_ecr_client(region, assume_role_arn)
        self.version = version
        self.build_args = build_args
        self.dockerfile = dockerfile
        self.working_dir = working_dir
        self.ssh = ssh
        self.cache_from = cache_from

    def ensure_image_in_ecr(self):
        if self.version:
            log_intent("Using commit hash " + self.version + " to find image")
            image = self._find_image_in_ecr(self.version)
            if not image:
                log_warning("Please build, tag and upload the image for the \
commit " + self.version)
                raise UnrecoverableException("Image for given version could not be found.")
        else:
            dirty = subprocess.check_output(
                ["git", "status", "--short"]
            ).decode("utf-8")
            if dirty:
                log_intent("Repository has uncommitted changes. Marking version as dirty.")
                self.version = '{}-dirty'.format(self._derive_version())
                image = None
            else:
                self.version = self._derive_version()
                image = self._find_image_in_ecr(self.version)

            log_intent("Version parameter was not provided. Determined version to be " +
                       self.version + " based on current status")
            if image:
                log_intent("Image found in ECR")
            else:
                log_bold("Image not found in ECR. Building image")
                self._build_image()
                self._push_image()
                image = self._find_image_in_ecr(self.version)
        try:
            image_manifest = image['imageManifest']
            self.client.put_image(
                repositoryName=self.repo_name,
                imageTag=self.version,
                imageManifest=image_manifest
            )
        except Exception:
            pass
        self._add_image_tag(self.version, f'{self.version}-{self._git_epoch_time()}')

    def add_tags(self, additional_tags):
        for new_tag in additional_tags:
            self._add_image_tag(self.version, new_tag)

    def upload_artefacts(self):
        self.ensure_repository()
        self.ensure_image_in_ecr()

    def upload_image(self, additional_tags):
        self.ensure_repository()
        self._push_image()

        for new_tag in additional_tags:
            self._add_image_tag(self.version, new_tag)

    def ensure_repository(self):
        try:
            self.client.create_repository(
                repositoryName=self.repo_name,
                imageScanningConfiguration={
                    'scanOnPush': True
                },
            )
            log_intent('Repo created with name: ' + self.repo_name)
        except Exception as ex:
            if type(ex).__name__ == 'RepositoryAlreadyExistsException':
                log_intent('Repo exists with name: ' + self.repo_name)
            else:
                raise ex

        current_account_id = get_account_id()
        if current_account_id != self.account_id:
            log_intent('Setting cross account ECR access: ' + self.repo_name)
            self.client.set_repository_policy(
                repositoryName=self.repo_name,
                policyText=json.dumps(
                    {
                        "Version": "2008-10-17",
                        "Statement": [
                            {
                                "Sid": "AllowCrossAccountPull-{}".format(current_account_id),
                                "Effect": "Allow",
                                "Principal": {
                                    "AWS": [current_account_id]
                                },
                                "Action": [
                                    "ecr:GetDownloadUrlForLayer",
                                    "ecr:BatchCheckLayerAvailability",
                                    "ecr:BatchGetImage",
                                    "ecr:InitiateLayerUpload",
                                    "ecr:PutImage",
                                    "ecr:UploadLayerPart",
                                    "ecr:CompleteLayerUpload",
                                ]
                            }
                        ]
                    }
                )
            )

    @property
    def image_uri(self):
        return "{}:{}".format(
            self.repo_path,
            self.version
        )

    @property
    def repo_path(self):
        return ECR_DOCKER_PATH.format(
            str(self.account_id),
            self.region,
            self.repo_name,
        )

    @property
    def local_image_uri(self):
        return spinalcase(self.repo_name) + ':' + self.version

    def _login_to_ecr(self):
        log_intent("Attempting login...")
        auth_token_res = self.client.get_authorization_token()
        user, auth_token = base64.b64decode(
            auth_token_res['authorizationData'][0]['authorizationToken']
        ).decode("utf-8").split(':')
        ecr_url = auth_token_res['authorizationData'][0]['proxyEndpoint']
        subprocess.check_call(["docker", "login", "-u", user,
                               "-p", auth_token, ecr_url])
        log_intent('Docker login to ECR succeeded.')

    def _git_epoch_time(self, git_version=None):
        return subprocess.check_output(
            ["git", "show", "-s", "--format=\"%ct\"", git_version or "HEAD"]
        ).strip().decode("utf-8").replace('"', '')

    def _derive_version(self, git_version=None):
        log_intent("Finding commit SHA")
        try:
            version_to_find = git_version or "HEAD"
            commit_sha = subprocess.check_output(
                ["git", "rev-list", "-n", "1", version_to_find]
            ).strip().decode("utf-8")

            derived_version = commit_sha
            if self.dockerfile is not None and self.dockerfile != DEFAULT_DOCKER_FILE:
                derived_version = "{}-{}".format(derived_version, self.dockerfile)

            log_intent("Derived version is " + derived_version)
            return derived_version
        except:
            raise UnrecoverableException("Commit SHA not found. Given version is not a git tag, \
branch or commit SHA")

    def _push_image(self):
        local_name = self.local_image_uri
        ecr_name = self.image_uri
        try:
            subprocess.check_call(["docker", "tag", local_name, ecr_name])
        except:
            raise UnrecoverableException("Local image was not found.")
        self._login_to_ecr()
        subprocess.check_call(["docker", "push", ecr_name])
        subprocess.check_call(["docker", "rmi", ecr_name])
        log_intent('Pushed the image (' + local_name + ') to ECR sucessfully.')

    def _add_image_tag(self, existing_tag, new_tag):
        try:
            image_manifest = self.client.batch_get_image(
                repositoryName=self.repo_name,
                imageIds=[
                    {'imageTag': existing_tag}
                ])['images'][0]['imageManifest']
            self.client.put_image(
                repositoryName=self.repo_name,
                imageTag=new_tag,
                imageManifest=image_manifest
            )
            log_intent(f'Added additional tag: {new_tag}')
        except:
            log_err("Unable to add additional tag " + str(new_tag))

    def _find_image_in_ecr(self, tag):
        try:
            return self.client.batch_get_image(
                repositoryName=self.repo_name,
                imageIds=[{'imageTag': tag}]
            )['images'][0]
        except:
            return None

    def _should_enable_buildkit(self):
        if self.ssh:
            return True
        if self.cache_from and len(self.cache_from) > 0:
            return True
        return False

    def _build_image(self):
        image_name = self.local_image_uri
        log_bold(
            f'Building docker image {image_name} using {"default Dockerfile" if self.dockerfile is None else self.dockerfile}')
        command = self._build_command(image_name)
        env = os.environ
        if self._should_enable_buildkit():
            env['DOCKER_BUILDKIT'] = '1'
        try:
            subprocess.check_call(command, env=env, shell=True)
        except subprocess.CalledProcessError as e:
            message = 'docker build exited with status: {}'.format(e.returncode)
            if e.output:
                message += '\n'
                message += e.output

            if e.stderr:
                message += '\n'
                message += e.output

            raise UnrecoverableException(message)
        log_bold("Built " + image_name)

    def _build_command(self, image_name):
        command = ['docker', 'build']
        if self.dockerfile:
            command.append(f'-f {self.dockerfile}')

        command.append(f'-t {image_name}')

        if self.ssh:
            command.append(f'--ssh {self.ssh}')

        if self.cache_from and len(self.cache_from) > 0:
            for cache in self.cache_from:
                command.append(f'--cache-from {cache}')

        command.extend(self._build_args_opts())
        command.append(self.working_dir)

        return " ".join(filter(None, command))

    def _build_args_opts(self):
        if self.build_args is None:
            return []
        else:
            build_args_command_fragment = []
            for k, v in self.build_args.items():
                build_args_command_fragment.append("--build-arg " + "=".join((k, v)))
            return build_args_command_fragment


def _create_ecr_client(region, assume_role_arn=None):
    if assume_role_arn:
        credentials = boto3.client('sts').assume_role(RoleArn=assume_role_arn,
                                                      RoleSessionName='ecrCloudliftAgent')
        return boto3.session.Session(
            aws_access_key_id=credentials['Credentials']['AccessKeyId'],
            aws_secret_access_key=credentials['Credentials']['SecretAccessKey'],
            aws_session_token=credentials['Credentials']['SessionToken']
        ).client('ecr')
    else:
        return boto3.session.Session(region_name=region).client('ecr')
