import base64
import subprocess

import boto3
from cloudlift.exceptions import UnrecoverableException
from stringcase import spinalcase


from cloudlift.config import get_account_id
from cloudlift.config.logging import log_intent, log_warning, log_bold, log_err


class EcrClient:
    def __init__(self, name, region, build_args=None, working_dir='.'):
        self.name = name
        self.build_args = build_args
        self.working_dir = working_dir
        self.region = region
        self.ecr_client = boto3.session.Session(region_name=self.region).client('ecr')

    def build_and_upload_image(self):
        self._ensure_repository()
        self._ensure_image_in_ecr()

    def upload_image(self, version, additional_tags):
        image_name = spinalcase(self.name) + ':' + version
        ecr_image_name = self.ecr_image_uri + ':' + version
        self._ensure_repository()
        self._push_image(image_name, ecr_image_name)

        for new_tag in additional_tags:
            self._add_image_tag(version, new_tag)

    def _ensure_repository(self):
        try:
            self.ecr_client.create_repository(
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

    def _ensure_image_in_ecr(self):
        if self.version == 'dirty':
            image = None
        else:
            image = self._find_image_in_ecr(self.version)
        if image:
            log_intent("Image found in ECR")
        else:
            log_bold(f"Image not found in ECR. Building image {self.name} {self.version}")
            image_name = spinalcase(self.name) + ':' + self.version
            ecr_name = self.ecr_image_uri + ':' + self.version
            self._build_image(image_name)
            self._push_image(image_name, ecr_name)
            image = self._find_image_in_ecr(self.version)

        try:
            image_manifest = image['imageManifest']
            self.ecr_client.put_image(
                repositoryName=self.repo_name,
                imageTag=self.version,
                imageManifest=image_manifest
            )
        except Exception:
            pass

    def set_version(self, version):
        if version:
            try:
                commit_sha = self._find_commit_sha(version)
            except:
                commit_sha = version
            log_intent("Using commit hash " + commit_sha + " to find image")
            image = self._find_image_in_ecr(commit_sha)
            if not image:
                log_warning("Please build, tag and upload the image for the \
        commit " + commit_sha)
                raise UnrecoverableException("Image for given version could not be found.")
            self.version = version
        else:
            dirty = subprocess.check_output(
                ["git", "status", "--short"]
            ).decode("utf-8")
            if dirty:
                self.version = 'dirty'
                log_intent("Version parameter was not provided. Determined \
        version to be " + self.version + " based on current status")
            else:
                self.version = self._find_commit_sha()
                log_intent("Version parameter was not provided. Determined \
        version to be " + self.version + " based on current status")

    def _build_image(self, image_name):
        log_bold("Building docker image " + image_name)
        command = self._build_command(image_name)
        subprocess.check_call(command, shell=True)
        log_bold("Built " + image_name)

    def _build_command(self, image_name):
        if self.build_args is None:
            return f'docker build -t {image_name} {self.working_dir}'
        else:
            build_args_command_fragment = []
            for k, v in self.build_args.items():
                build_args_command_fragment.append(" --build-arg " + "=".join((k, v)))
            return f'docker build -t {image_name}{"".join(build_args_command_fragment)} {self.working_dir}'

    def _login_to_ecr(self):
        log_intent("Attempting login...")
        auth_token_res = self.ecr_client.get_authorization_token()
        user, auth_token = base64.b64decode(
            auth_token_res['authorizationData'][0]['authorizationToken']
        ).decode("utf-8").split(':')
        ecr_url = auth_token_res['authorizationData'][0]['proxyEndpoint']
        subprocess.check_call(["docker", "login", "-u", user,
                               "-p", auth_token, ecr_url])
        log_intent('Docker login to ECR succeeded.')

    def _find_commit_sha(self, version=None):
        log_intent("Finding commit SHA")
        try:
            version_to_find = version or "HEAD"
            commit_sha = subprocess.check_output(
                ["git", "rev-list", "-n", "1", version_to_find]
            ).strip().decode("utf-8")
            log_intent("Found commit SHA " + commit_sha)
            return commit_sha
        except:
            raise UnrecoverableException("Commit SHA not found. Given version is not a git tag, \
branch or commit SHA")

    def _push_image(self, local_name, ecr_name):
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
            image_manifest = self.ecr_client.batch_get_image(
                repositoryName=self.repo_name,
                imageIds=[
                    {'imageTag': existing_tag}
                ])['images'][0]['imageManifest']
            self.ecr_client.put_image(
                repositoryName=self.repo_name,
                imageTag=new_tag,
                imageManifest=image_manifest
            )
        except:
            log_err("Unable to add additional tag " + str(new_tag))

    def _find_image_in_ecr(self, tag):
        try:
            return self.ecr_client.batch_get_image(
                repositoryName=self.repo_name,
                imageIds=[{'imageTag': tag}]
            )['images'][0]
        except:
            return None

    @property
    def repo_name(self):
        return self.name + '-repo'

    @property
    def ecr_image_uri(self):
        return str(self.account_id) + ".dkr.ecr." + self.region + \
               ".amazonaws.com/" + self.repo_name

    @property
    def account_id(self):
        return get_account_id()
