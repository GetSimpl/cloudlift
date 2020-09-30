import base64
import multiprocessing
import os
import subprocess
from time import sleep

import boto3
from cloudlift.config import get_account_id
from cloudlift.config import get_cluster_name
from cloudlift.config import (get_region_for_environment)
from cloudlift.config.logging import log_bold, log_err, log_intent, log_warning
from cloudlift.deployment import deployer, ServiceInformationFetcher
from cloudlift.deployment.ecs import EcsClient
from cloudlift.exceptions import UnrecoverableException
from stringcase import spinalcase
from cloudlift.utils import chunks

DEPLOYMENT_COLORS = ['blue', 'magenta', 'white', 'cyan']
DEPLOYMENT_CONCURRENCY = int(os.environ.get('CLOUDLIFT_DEPLOYMENT_CONCURRENCY', 4))


class ServiceUpdater(object):
    def __init__(self, name, environment='', env_sample_file='', timeout_seconds=None, version=None,
                 build_args=None, dockerfile=None, working_dir='.'):
        self.name = name
        self.environment = environment
        self.env_sample_file = env_sample_file
        self.timeout_seconds = timeout_seconds
        self.version = version
        self.ecr_client = boto3.session.Session(region_name=self.region).client('ecr')
        self.cluster_name = get_cluster_name(environment)
        self.build_args = build_args
        self.dockerfile = dockerfile
        self.working_dir = working_dir
        self.service_info = ServiceInformationFetcher(self.name, self.environment).service_info

    def run(self):
        log_warning("Deploying to {self.region}".format(**locals()))
        if not os.path.exists(self.env_sample_file):
            raise UnrecoverableException('env.sample not found. Exiting.')
        log_intent("name: " + self.name + " | environment: " +
                   self.environment + " | version: " + str(self.version))
        log_bold("Checking image in ECR")
        self.upload_artefacts()
        log_bold("Initiating deployment\n")
        ecs_client = EcsClient(None, None, self.region)

        image_url = self.ecr_image_uri
        image_url += (':' + self.version)
        target = deployer.deploy_new_version
        kwargs = dict(client=ecs_client, cluster_name=self.cluster_name,
                      deploy_version_tag=self.version,
                      service_name=self.name, sample_env_file_path=self.env_sample_file,
                      timeout_seconds=self.timeout_seconds, env_name=self.environment,
                      complete_image_uri=image_url)
        self.run_job_for_all_services("Deploy", target, kwargs)

    def revert(self):
        target = deployer.revert_last_deployment
        ecs_client = EcsClient(None, None, self.region)
        kwargs = dict(client=ecs_client, cluster_name=self.cluster_name, timeout_seconds=self.timeout_seconds)
        self.run_job_for_all_services("Revert", target, kwargs)

    def run_job_for_all_services(self, job_name, target, kwargs):
        log_bold("{} concurrency: {}".format(job_name, DEPLOYMENT_CONCURRENCY))
        jobs = []
        for index, ecs_service_logical_name in enumerate(self.service_info):
            ecs_service_info = self.service_info[ecs_service_logical_name]
            log_bold(f"Queueing {job_name} of " + ecs_service_info['ecs_service_name'])
            color = DEPLOYMENT_COLORS[index % 3]
            kwargs.update(dict(ecs_service_name=ecs_service_info['ecs_service_name'],
                               secrets_name=ecs_service_info.get('secrets_name'),
                               color=color))
            process = multiprocessing.Process(
                target=target,
                kwargs=kwargs
            )
            jobs.append(process)
        all_exit_codes = []
        for chunk_of_jobs in chunks(jobs, DEPLOYMENT_CONCURRENCY):
            exit_codes = []
            for process in chunk_of_jobs:
                process.start()

            while True:
                sleep(1)
                exit_codes = [proc.exitcode for proc in chunk_of_jobs]
                if None not in exit_codes:
                    break

            for exit_code in exit_codes:
                all_exit_codes.append(exit_code)
        if any(all_exit_codes) != 0:
            raise UnrecoverableException(f"{job_name} failed")

    def upload_image(self, additional_tags):
        image_name = spinalcase(self.name) + ':' + self.version
        ecr_image_name = self.ecr_image_uri + ':' + self.version
        self.ensure_repository()
        self._push_image(image_name, ecr_image_name)

        for new_tag in additional_tags:
            self._add_image_tag(self.version, new_tag)

    def _build_image(self, image_name):
        log_bold(
            f'Building docker image {image_name} using {"default Dockerfile" if self.dockerfile is None else self.dockerfile}')
        command = self._build_command(image_name)
        subprocess.check_call(command, shell=True)
        log_bold("Built " + image_name)

    def _build_command(self, image_name):
        dockerfile_opt = '' if self.dockerfile is None else f'-f {self.dockerfile}'
        build_args_opts = self._build_args_opts()
        return " ".join(
            filter(None, ['docker', 'build', dockerfile_opt, '-t', image_name, *build_args_opts, self.working_dir]))

    def _build_args_opts(self):
        if self.build_args is None:
            return []
        else:
            build_args_command_fragment = []
            for k, v in self.build_args.items():
                build_args_command_fragment.append("--build-arg " + "=".join((k, v)))
            return build_args_command_fragment

    def upload_artefacts(self):
        self.ensure_repository()
        self.ensure_image_in_ecr()

    def ensure_repository(self):
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

    def ensure_image_in_ecr(self):
        if self.version:
            try:
                commit_sha = self._find_commit_sha(self.version)
            except:
                commit_sha = self.version
            log_intent("Using commit hash " + commit_sha + " to find image")
            image = self._find_image_in_ecr(commit_sha)
            if not image:
                log_warning("Please build, tag and upload the image for the \
commit " + commit_sha)
                raise UnrecoverableException("Image for given version could not be found.")
        else:
            dirty = subprocess.check_output(
                ["git", "status", "--short"]
            ).decode("utf-8")
            if dirty:
                self.version = 'dirty'
                log_intent("Version parameter was not provided. Determined \
version to be " + self.version + " based on current status")
                image = None
            else:
                self.version = self._find_commit_sha()
                log_intent("Version parameter was not provided. Determined \
version to be " + self.version + " based on current status")
                image = self._find_image_in_ecr(self.version)

            if image:
                log_intent("Image found in ECR")
            else:
                log_bold("Image not found in ECR. Building image")
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

    @property
    def ecr_image_uri(self):
        return str(self.account_id) + ".dkr.ecr." + self.region + \
               ".amazonaws.com/" + self.repo_name

    @property
    def repo_name(self):
        return self.name + '-repo'

    @property
    def region(self):
        return get_region_for_environment(self.environment)

    @property
    def account_id(self):
        return get_account_id()


