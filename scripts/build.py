import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

DOCKERFILES = {
    "linux": "dockerfile.linux",
    "alpine": "dockerfile.alpine",
}
PYINSTALLER_VERSION = os.getenv("PYINSTALLER_VERSION", "6.10.0")

# test distros are mainly used for testing the package
# while developing on the local machine. these are not required
# for the CI/CD pipeline as CI/CD pipeline will run tests separately.
# to test the packages while building, use the --test flag.
TEST_DISTROS = {
    "linux": {
        "ubuntu": [
            "24.04",
            "22.04",
            "20.04",
            "18.04",
            "16.04",
            "14.04",
        ],
        "debian": [
            "12",
            "11",
            "10",
            "9",
            "8",
        ],
        "amazonlinux": [
            "2023",
            "2",
            "1",
        ],
        "fedora": [
            "40",
            "39",
            "38",
        ],
    },
    "alpine": {
        "alpine": [
            "3.20",
            "3.19",
            "3.18",
            "3.17",
            "3.16",
            "3.15",
            "3.14",
            "3.13",
            "3.12",
            "3.11",
        ],
    },
}


def BuildError(Exception):
    pass


class Builder:
    def __init__(
        self, work_dir: Path, os_name: str, arch: str, use_docker: bool
    ) -> None:
        self.work_dir = work_dir
        self.os_name = os_name
        self.arch = arch
        self.use_docker = use_docker
        self.docker_image = f"cloudlift-builder-{self.os_name}"
        self.docker_container = f"cloudlift-builder-{self.os_name}"
        self.package_name = self._get_package_name()
        self.python = "python3"

    @staticmethod
    def print_info(message: str):
        print(f"\033[0;32m[INFO]\033[0m {message}")

    @staticmethod
    def print_error(message: str):
        print(f"\033[0;31m[ERROR]\033[0m {message}")
        raise BuildError(message)

    @staticmethod
    def print_success(message: str):
        print(f"\033[0;32m[SUCCESS]\033[0m {message}")

    @staticmethod
    def print_warning(message: str):
        print(f"\033[0;33m[WARNING]\033[0m {message}")

    def _get_package_name(self) -> str:
        version_file = os.path.join(
            self.work_dir, "cloudlift", "version", "__init__.py"
        )
        version = None

        with open(version_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("VERSION"):
                    version = line.split("=")[1].strip().strip("'")

        package_name = f"cloudlift-{self.os_name}-{self.arch}-v{version}"
        return package_name

    def _check_for_binary(self, binary: str) -> None:
        if not shutil.which(binary):
            self.print_error(f"Could not find {binary}")

    def cleanup(self):
        self.print_info("Cleaning up")

        if os.path.exists(self.work_dir / "build"):
            shutil.rmtree(self.work_dir / "build")

        if os.path.exists(self.work_dir / "venv"):
            shutil.rmtree(self.work_dir / "venv")

        spec_files = list(self.work_dir.glob("*.spec"))
        for spec_file in spec_files:
            os.remove(spec_file)

        # remove .egg-info
        egg_info = list(self.work_dir.glob("*.egg-info"))
        for egg in egg_info:
            shutil.rmtree(egg)

    def preflight_check(self):
        self.print_info("Running preflight checks")

        if not os.path.exists(self.work_dir / "cloudlift" / "version" / "__init__.py"):
            self.print_error("Could not find version/__init__.py")

        packages = [self.python]
        for package in packages:
            self._check_for_binary(package)

        if self.use_docker:
            self._check_for_binary("docker")

        self.print_info("Preflight checks passed")

    def _check_for_docker_image(self) -> bool:
        cmd = ["docker", "images", "--format", "{{.Repository}}"]
        self.print_info(" ".join(cmd))
        output = subprocess.run(cmd, check=True, capture_output=True, text=True)

        if self.docker_image not in output.stdout:
            self.print_info(f"Could not find Docker image {self.docker_image}")
            return False

        return True

    def create_docker_image(self):
        if not self.use_docker:
            return

        dockerfile = DOCKERFILES.get(self.os_name)
        if not dockerfile:
            self.print_error(f"Could not find Dockerfile for {self.os_name}")

        dockerfile_path = os.path.join(self.work_dir, "scripts/dockerfiles", dockerfile)

        self.print_info(f"Building Docker image for {self.os_name}")
        docker_build_cmd = [
            "docker",
            "build",
            "-t",
            self.docker_image,
            "--build-arg",
            f"PYINSTALLER_VERSION={PYINSTALLER_VERSION}",
            "-f",
            dockerfile_path,
            ".",
        ]

        self.print_info(" ".join(docker_build_cmd))
        subprocess.run(docker_build_cmd, check=True)

    def create_docker_container(self):
        if not self.use_docker:
            return

        # check if the docker image exists
        if not self._check_for_docker_image():
            self.print_error(
                f"Could not find Docker image {self.docker_image}; please build the image first"
            )

        # check if container already exists
        cmd = ["docker", "ps", "-a", "--format", "{{.Names}}"]
        self.print_info(" ".join(cmd))
        output = subprocess.run(cmd, check=True, capture_output=True, text=True)
        self.print_info(output.stdout)

        if self.docker_container in output.stdout:
            self.print_info(f"Container {self.docker_container} already exists")
            self.delete_container()

        self.print_info(
            f"Creating Docker container for {self.os_name} in detached mode"
        )

        docker_platform = "linux/arm64" if self.arch == "arm64" else "linux/amd64"

        host_dir_abs = os.path.abspath(self.work_dir).strip()
        self.print_info(f"Mounting {host_dir_abs} to /app in container")

        docker_run_cmd = [
            "docker",
            "run",
            "-d",
            "-i",
            "-v",
            f"{shlex.quote(host_dir_abs)}:/app",
            f"--platform={docker_platform}",
            "--name",
            self.docker_container,
            self.docker_image,
        ]

        self.print_info(subprocess.list2cmdline(docker_run_cmd))
        subprocess.run(docker_run_cmd, check=True)

    def delete_container(self):
        if not self.use_docker:
            return

        # check if container already exists
        cmd = ["docker", "ps", "-a", "--format", "{{.Names}}"]
        self.print_info(" ".join(cmd))
        output = subprocess.run(cmd, check=True, capture_output=True, text=True)

        if self.docker_container not in output.stdout:
            self.print_info(f"Container {self.docker_container} does not exist")
            return

        self.print_info(f"Stopping and removing container {self.docker_image}")
        docker_rm_cmd = ["docker", "rm", "-f", self.docker_image]

        self.print_info(" ".join(docker_rm_cmd))
        subprocess.run(docker_rm_cmd, check=True)

    def setup_venv(self):
        if self.os_name != "darwin":
            self.print_info("Virtual env is not required for non-darwin platforms")
            return

        self.print_info("Setting up virtual environment")
        venv_path = os.path.join(self.work_dir, "venv")

        # if venv exists, remove it
        if os.path.exists(venv_path):
            shutil.rmtree(venv_path)

        venv_python = f"{venv_path}/bin/python"
        os.environ["VIRTUAL_ENV"] = str(venv_path)
        os.environ["PATH"] = f"{venv_path}/bin:{os.environ['PATH']}"

        sys.prefix = str(venv_path)
        sys.executable = venv_python

        if sys.prefix != str(venv_path):
            self.print_error("Could not set up virtual environment")

        venv_cmd = [self.python, "-m", "venv", venv_path]
        self.print_info(" ".join(venv_cmd))
        subprocess.run(venv_cmd, check=True)

        # set python to venv python path for darwin
        # as python will be used from venv
        if not self.use_docker:
            self.python = venv_python

    def install_requirements(self):
        self.print_info("Installing requirements")

        cmd = [
            self.python,
            "-m",
            "pip",
            "install",
            ".",
        ]
        shell_cmd = "/bin/sh" if self.os_name == "alpine" else "/bin/bash"

        try:
            if self.use_docker:
                # run inside docker container
                docker_exec_cmd = [
                    "docker",
                    "exec",
                    "-i",
                    self.docker_container,
                    shell_cmd,
                    "-c",
                    "cd /app && " + subprocess.list2cmdline(cmd),
                ]

                self.print_info(subprocess.list2cmdline(docker_exec_cmd))
                subprocess.run(docker_exec_cmd, check=True)
            else:
                self.print_info(subprocess.list2cmdline(cmd))
                subprocess.run(cmd, check=True, cwd=self.work_dir)
        except subprocess.CalledProcessError:
            self.print_error("Could not install requirements")

        if self.os_name == "darwin":
            self._install_pyinstaller()

    def _install_pyinstaller(self) -> None:
        self.print_info(f"Installing pyinstaller {PYINSTALLER_VERSION}")

        pyinstaller_cmd = [
            self.python,
            "-m",
            "pip",
            "install",
            f"pyinstaller=={PYINSTALLER_VERSION}",
        ]
        self.print_info(subprocess.list2cmdline(pyinstaller_cmd))
        subprocess.run(pyinstaller_cmd, check=True)

    def build_package(self):
        self.print_info("Building package")
        pyinstaller_args = [
            "pyinstaller",
            "--onedir",
            "--clean",
            "--noconfirm",
            "--nowindow",
            "--name=cloudlift",
            "--paths=cloudlift",
            "--add-data=LICENSE:.",
            "--add-data=README.md:.",
            "--exclude-module=pyinstaller",
            "bin/cloudlift",
        ]
        shell_cmd = "/bin/sh" if self.os_name == "alpine" else "/bin/bash"

        if self.use_docker:
            docker_exec_cmd = [
                "docker",
                "exec",
                "-i",
                self.docker_container,
                shell_cmd,
                "-c",
                "cd /app && " + subprocess.list2cmdline(pyinstaller_args),
            ]

            self.print_info(subprocess.list2cmdline(docker_exec_cmd))
            subprocess.run(docker_exec_cmd, check=True)
        else:
            self.print_info(subprocess.list2cmdline(pyinstaller_args))
            subprocess.run(pyinstaller_args, check=True, cwd=self.work_dir)

    def package(self):
        self.print_info(
            f"Packaging Cloudlift for {self.os_name} to {self.package_name}"
        )

        try:
            temp_dir = os.path.join("/tmp")
            temp_package_path = os.path.join(temp_dir, f"{self.package_name}.tar.gz")

            # create the package in temp directory
            with tarfile.open(temp_package_path, "w:gz") as tar:
                cloudlift_dir = os.path.join(self.work_dir, "dist", "cloudlift")
                tar.add(cloudlift_dir, arcname=self.package_name)

            self.print_info(f"Package created at {temp_package_path}")

        except PermissionError as e:
            self.print_error(f"Permission error while creating package: {str(e)}")
        except OSError as e:
            self.print_error(f"OS error while creating package: {str(e)}")
        except Exception as e:
            self.print_error(f"Unexpected error while creating package: {str(e)}")

    def test_package(self, package_path: str) -> None:
        self.print_info("Testing package")

        # if not package_path:
        if package_path.startswith("/tmp"):
            # copy the package to work_dir/dist as I was facing issues with mounting
            # /tmp/<package_name>.tar.gz to /app. when I mounted
            # /app was empty in the container. this is a workaround for now.

            tmp_package_path = os.path.join("/tmp", f"{self.package_name}.tar.gz")
            package_path = os.path.join(
                self.work_dir, "dist", f"{self.package_name}.tar.gz"
            )
            self.print_info(
                f"Copying package from {tmp_package_path} to {package_path}"
            )

            # create package_path directory if it does not exist
            if not os.path.exists(os.path.dirname(package_path)):
                os.makedirs(os.path.dirname(package_path))
            shutil.copy(tmp_package_path, os.path.dirname(package_path))

        if not os.path.exists(package_path):
            self.print_error(f"Could not find package at {package_path}")

        cloudlift_extracted_dir = os.path.join(
            os.path.dirname(package_path), self.package_name
        )
        with tarfile.open(package_path, "r:gz") as tar:
            tar.extractall(path=os.path.dirname(package_path))

        if not os.path.exists(cloudlift_extracted_dir):
            self.print_error("Could not extract package")

        # run tests
        if self.use_docker:
            self._test_on_containers(cloudlift_extracted_dir)
        else:
            self._test_on_local(cloudlift_extracted_dir)

    def _test_on_local(self, cloudlift_extracted_dir):
        self.print_info("Testing on local machine")

        test_cmd = [
            # "./dist/cloudlift/cloudlift",
            os.path.join(cloudlift_extracted_dir, "cloudlift"),
            "--version",
        ]

        self.print_info(subprocess.list2cmdline(test_cmd))
        subprocess.run(test_cmd, check=True, cwd=self.work_dir)

    def _test_on_containers(self, cloudlift_extracted_dir):
        distros = TEST_DISTROS.get(self.os_name)
        if not distros:
            self.print_error(f"Could not find distros for {self.os_name}")

        is_failed = False
        for distro, versions in distros.items():
            for version in versions:
                response = self._test_on_container(
                    self.os_name, distro, version, cloudlift_extracted_dir
                )
                if not response:
                    is_failed = True

        if is_failed:
            self.print_error(f"Some tests failed for {self.os_name}")

    def _test_on_container(
        self, os_name, distro, version, cloudlift_extracted_dir
    ) -> bool:
        docker_platform = "linux/arm64" if self.arch == "arm64" else "linux/amd64"
        # host_dir_abs = os.path.abspath(self.work_dir).strip()
        shell_cmd = "/bin/sh" if self.os_name == "alpine" else "/bin/bash"

        cmd = [
            "docker",
            "run",
            "--rm",
            "-i",
            "-v",
            f"{shlex.quote(cloudlift_extracted_dir)}:/app",
            f"--platform={docker_platform}",
            f"{distro}:{version}",
            shell_cmd,
            "-c",
            "cd /app && ./cloudlift --version",
        ]

        output = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )

        if output.returncode == 0:
            self.print_success(f"Test passed for {distro}:{version}")
            return True
        else:
            self.print_warning(f"Test failed for {distro}:{version}")
            return False

    def build(
        self, test_package: bool, only_test: bool, package_dir: str, build_image: bool
    ) -> None:
        package_path = os.path.join(str(package_dir), f"{self.package_name}.tar.gz")

        if only_test:
            self.print_info("Only running tests on the package")
            self.test_package(package_path)
            return

        self.preflight_check()

        if build_image:
            self.create_docker_image()

        self.create_docker_container()
        self.setup_venv()
        self.install_requirements()
        self.build_package()
        self.package()

        if test_package:
            self.test_package(package_path)


def get_os_name() -> str:
    os_name = platform.system().lower()
    if os_name == "linux":
        if os.path.exists("/etc/alpine-release"):
            return "alpine"

    return os_name


def get_arch() -> str:
    return platform.machine()


def main():
    parser = argparse.ArgumentParser(description="Build Cloudlift package")
    parser.add_argument(
        "--os",
        type=str,
        default=get_os_name(),
        help="Operating system to build package for",
    )
    parser.add_argument(
        "--arch",
        type=str,
        default=get_arch(),
        help="Architecture to build package for",
    )
    parser.add_argument(
        "--package-name",
        action="store_true",
        help="Print package name and exit",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run tests on the package; mainly used for local testing while developing",
    )
    parser.add_argument(
        "--only-test",
        action="store_true",
        help="Only run tests on the package; mainly used in CI/CD pipeline. This will not build the package. Also pass the path to the package using --package-path",
    )
    parser.add_argument(
        "--package-dir",
        type=str,
        default="/tmp",
        help="Directory to the package to run tests on; used in CI/CD pipeline",
    )
    parser.add_argument(
        "--build-image",
        action="store_true",
        help="Build Docker image for the specified OS",
    )
    args = parser.parse_args()

    work_dir = Path(__file__).resolve().parent.parent
    use_docker = False

    # handle macOS or darwin as os
    if args.os.lower() in ["macos", "darwin"]:
        args.os = "darwin"

    if args.os in ["linux", "alpine"]:
        use_docker = True

    builder = Builder(work_dir, args.os, args.arch, use_docker)

    if args.package_name:
        sys.stdout.write(builder.package_name)
        sys.exit(0)

    builder.build(
        test_package=args.test,
        only_test=args.only_test,
        package_dir=args.package_dir,
        build_image=args.build_image,
    )


if __name__ == "__main__":
    main()
