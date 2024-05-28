#!/bin/bash

# ----------------------------------------
# Setup
# ----------------------------------------

# exit on error
set -o errexit

# ----------------------------------------
# Configuration
# ----------------------------------------

WORK_DIR=$(pwd)
VENV_DIRNAME="venv"

MIN_PYTHON_MINOR_VERSION=9  # 3.9
MAX_PYTHON_MINOR_VERSION=9  # 3.9

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

PACKAGE_VERSION=$(<cloudlift/version/__init__.py grep VERSION | cut -d'=' -f2 | tr -d "'" | tr -d ' ')

OUT_PACKAGE_NAME="cloudlift-${OS}-${ARCH}-v${PACKAGE_VERSION}"

for arg in "$@"; do
  case $arg in
  --package-name)
    echo "${OUT_PACKAGE_NAME}.tar.gz"
    shift
    exit 0
    ;;
  *)
    [ -z "$arg" ] && break
    exit 1
    ;;
  esac
done

# ----------------------------------------
# Functions
# ----------------------------------------

print_info() {
  echo -e "\033[0;32m[INFO]\033[0m $1"
}

print_error() {
  echo -e "\033[0;31m[ERROR]\033[0m $1"

  exit 1
}

preflight_check() {
  print_info "Running preflight checks..."

  if ! command -v tar >/dev/null; then
    print_error "tar is required."
  fi
}

setup_python() {
  print_info "Setting up Python..."

  if ! command -v python3 >/dev/null; then
    print_error "Python 3 is required."
  fi

  _python_version="$(python3 --version | cut -d' ' -f2)"
  _minor_version="$(echo $_python_version | cut -d'.' -f2)"

  if [ $_minor_version -lt $MIN_PYTHON_MINOR_VERSION ] || [ $_minor_version -gt $MAX_PYTHON_MINOR_VERSION ]; then
    print_error "Python version must be >= 3.$MIN_PYTHON_MINOR_VERSION and <= 3.$MAX_PYTHON_MINOR_VERSION"
  fi

  local python_path=$(which python3)
  print_info "Python version: $_python_version ($python_path)"
}

setup_venv() {
  print_info "Setting up Python virtual environment..."

  if ! [ -d "${WORK_DIR}/${VENV_DIRNAME}" ]; then
    python3 -m venv ${VENV_DIRNAME}
  fi

  source ${VENV_DIRNAME}/bin/activate
}

install_requirements() {
  print_info "Installing requirements..."

  pip install pyinstaller || print_error "Failed to install pyinstaller."

  # install package - cloudlift
  pip install . || print_error "Failed to install package."
}

clear_build() {
  print_info "Clearing build..."
  rm -rf dist build
  rm -f ./*.spec
}

build_package() {
  print_info "Building package..."

  # build the executable
  #  note: --onefile drastically slows down the runtime speed of the executable

  if [ "${OS}" == "linux" ]; then
    pyinstaller \
      --onedir \
      --clean \
      --nowindow \
      --name "${OUT_PACKAGE_NAME}" \
      --paths cloudlift \
      --add-data LICENSE:. \
      --add-data README.md:. \
      --add-binary /usr/lib64/libcrypt.so.1:. \
      --add-binary /lib/ld-musl-x86_64.so.1:. \
      bin/cloudlift
  else
    pyinstaller \
      --onedir \
      --clean \
      --nowindow \
      --name "${OUT_PACKAGE_NAME}" \
      --paths cloudlift \
      --add-data LICENSE:. \
      --add-data README.md:. \
      bin/cloudlift
  fi

  # change the package name (binary) to the cloudlift package name
  mv "dist/${OUT_PACKAGE_NAME}/${OUT_PACKAGE_NAME}" "dist/${OUT_PACKAGE_NAME}/cloudlift"
}

package() {
  print_info "Packaging..."

  # check if tar is installed
  if ! command -v tar >/dev/null; then
    print_error "tar is required."
  fi

  # create archive
  tar -czf "dist/${OUT_PACKAGE_NAME}.tar.gz" -C dist "${OUT_PACKAGE_NAME}"
}

test_package() {
  print_info "Testing package..."

  # test the package
  _version=$("dist/${OUT_PACKAGE_NAME}/cloudlift" --version)
  _version=$(echo $_version | cut -d' ' -f3)

  if [ "$_version" != "$PACKAGE_VERSION" ]; then
    print_error "Package version mismatch. Expected: $PACKAGE_VERSION, Got: $_version"
  fi

}

success_message() {
  rc=$1

  if [ $rc -eq 0 ]; then
    _version=$("dist/${OUT_PACKAGE_NAME}/cloudlift" --version)
    _package_size=$(du -sh "dist/${OUT_PACKAGE_NAME}.tar.gz" | cut -f1)

    echo ""
    print_info "Build successful."
    print_info "Cloudlift package version: $_version"
    print_info "Cloudlift package size: $_package_size"
  else
    print_error "Build failed."
  fi
}

# ----------------------------------------
# Main
# ----------------------------------------

main() {
  print_info "Building Cloudlift package for os: ${OS}, arch: ${ARCH}"
  print_info "Package version: ${PACKAGE_VERSION}"

  preflight_check
  setup_python
  setup_venv
  install_requirements
  clear_build
  build_package
  package
  test_package
}

main
success_message $?
