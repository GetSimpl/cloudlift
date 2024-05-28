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
TEMP_DIR="/tmp/cloudlift"
PACKAGE_NAME="cloudlift"
PACKAGE_DEST_DIR="/usr/local"
PACKAGE_BIN_DIR="/usr/local/bin"

OS_TYPE=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH_TYPE=$(uname -m)
PACKAGE_VERSION="latest"

ARCHIVE_NAME=""

REPO_OWNER="tasnimzotder"
DOWNLOAD_BASE_URL="https://github.com/${REPO_OWNER}/cloudlift/releases/download"
RELEASES_URL="https://api.github.com/repos/${REPO_OWNER}/cloudlift/releases"
LATEST_RELEASE_URL="${RELEASES_URL}/latest"

IS_UNINSTALL=false
AUTO_APPROVE=false # todo: implement auto-approve (default: false)
SKIP_CHECKSUM=false

# important functions
print_info() {
  echo -e "\033[0;32m[INFO]\033[0m $1"
}

print_warning() {
  echo -e "\033[0;33m[WARN]\033[0m $1"
}

print_error() {
  echo -e "\033[0;31m[ERROR]\033[0m $1"

  exit 1
}

fail() {
  print_error "Failed to install Cloudlift."
}

usage() {
  echo "
  Usage: $0 [options]

  Options:
    -h, --help          Display this help message
    -v, --version       Install specific version of Cloudlift package
    -u, --uninstall     Uninstall Cloudlift package
    -b, --local-build   Install local build of Cloudlift package
    -c, --skip-checksum Skip checksum verification
  "
}

while :; do
  case $1 in
  -h | --help)
    usage
    exit 0
    ;;
  -v | --version)
    if [ -z "$2" ]; then
      print_error "Version number is required."
    fi
    #    remove 'v' (prefix) from version if present
    PACKAGE_VERSION=$(echo "$2" | sed 's/^v//')
    shift 2
    ;;
  -b | --local-build)
    print_error "Local build is not supported yet."
    shift 1
    ;;
  -u | --uninstall)
    IS_UNINSTALL=true
    shift 1
    ;;
  -y | --auto-approve)
    AUTO_APPROVE=true
    shift 1
    ;;
  -c | --skip-checksum)
    SKIP_CHECKSUM=true
    shift 1
    ;;
  *)
    [ -z "$1" ] && break
    print_error "Invalid option: $1"
    ;;
  esac
done

echo "PACKAGE_VERSION: ${PACKAGE_VERSION}"

# ----------------------------------------
# Functions
# ----------------------------------------

check_sudo() {
  print_info "Checking if running as root..."

  if [ "$EUID" -ne 0 ]; then
    print_error "Please run as root."
  fi
}

confirm_message() {
  if [ "${AUTO_APPROVE}" = true ]; then
    print_info "Auto-approving..."
  else
    local confirm
    read -p "$1 [y/N]: " confirm

    if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
      print_warning "Exiting..."
      exit 0
    fi
  fi
}

get_latest_release() {
  print_info "Getting latest release version..."

  local latest_release=$(curl -sL "${LATEST_RELEASE_URL}" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')

  if [ -z "${latest_release}" ]; then
    print_error "Failed to get latest release version."
  fi

  # remove 'v' (prefix) from version
  latest_release=$(echo "${latest_release}" | cut -c 2-)
  PACKAGE_VERSION="${latest_release}"

  print_info "Latest release version: v${PACKAGE_VERSION}"
}

release_check() {
  # select tag_name, select version, remove 'v' prefix
  all_releases_details=$(curl -sL "${RELEASES_URL}")
  local all_releases=$(echo "${all_releases_details}" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' | cut -c 2- | sort -V)

  #tag check
  # if VERSION is not in all_releases, then print error
  if ! echo "${all_releases[@]}" | grep -q "${PACKAGE_VERSION}"; then
    print_error "Could not find Cloudlift release with version: v${PACKAGE_VERSION}
        Available versions:
          ${all_releases}
    "
  fi

  #  archive check
  #  if the ARCHIVE_NAME is not in the releases, then print error
  if ! echo "${all_releases_details}" | grep -q "${ARCHIVE_NAME}"; then
    print_error "Could not find Cloudlift release with archive: ${ARCHIVE_NAME}"
  fi
}

download_cloudlift() {
  print_info "Downloading Cloudlift package..."

  ARCHIVE_NAME="${PACKAGE_NAME}-${OS_TYPE}-${ARCH_TYPE}-v${PACKAGE_VERSION}"

  # check if the releases have the version (as a tag) and the archive
  release_check

  local supported_archives=("linux-x86_64" "darwin-arm64")
  local supported_os_arch="${OS_TYPE}-${ARCH_TYPE}"
  local is_supported=false

  for archive in "${supported_archives[@]}"; do
    if [[ "$archive" == "$supported_os_arch" ]]; then
      is_supported=true
      break
    fi
  done

  if [[ "$is_supported" == false ]]; then
    print_error "Unsupported OS type; ${OS_TYPE}-${ARCH_TYPE}. Cloudlift package is not available for this OS type yet."
  fi

  local download_url="${DOWNLOAD_BASE_URL}/v${PACKAGE_VERSION}/${ARCHIVE_NAME}.tar.gz"
  print_info "Downloading from: ${download_url}"

  # download archive to /tmp/cloudlift
  mkdir -p ${TEMP_DIR}
  curl -L -o "${TEMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${download_url}" || {
    print_error "Failed to download Cloudlift package."
  }
}

download_checksum() {
  print_info "Downloading checksum..."

  local checksum_url="${DOWNLOAD_BASE_URL}/v${PACKAGE_VERSION}/checksums.txt"
  print_info "Downloading from: ${checksum_url}"

  #  remove checksum file if exists
  if [ -f "${TEMP_DIR}/checksums.txt" ]; then
    rm "${TEMP_DIR}/checksums.txt"
  fi

  # download checksum to /tmp/cloudlift
  mkdir -p ${TEMP_DIR}
  curl -L -o "${TEMP_DIR}/checksums.txt" "${checksum_url}" || {
    print_error "Failed to download checksum."
  }
}

perform_checksum() {
  print_info "Checking checksum..."

  # download checksum file
  download_checksum

  local checksum=$(grep "${ARCHIVE_NAME}.tar.gz" "${TEMP_DIR}/checksums.txt" | cut -d' ' -f2)
  echo "Checksum: ${checksum}"

  #  check if the checksum is correct
  if [ "${OS_TYPE}" == "darwin" ]; then
    shasum -a 256 "${TEMP_DIR}/${ARCHIVE_NAME}.tar.gz" | grep "${checksum}" || {
      print_error "Checksum mismatch."
    }
  elif [ "${OS_TYPE}" == "linux" ]; then
    sha256sum "${TEMP_DIR}/${ARCHIVE_NAME}.tar.gz" | grep "${checksum}" || {
      print_error "Checksum mismatch."
    }
  fi
}

unarchive_cloudlift() {
  print_info "Unarchiving Cloudlift package..."

  if [ -d "${TEMP_DIR}/${ARCHIVE_NAME}" ]; then
    print_info "Removing existing Cloudlift package"
    rm -rf "${TEMP_DIR}/${ARCHIVE_NAME}"
  fi

  print_info "Unarchiving Cloudlift package to ${TEMP_DIR}/${ARCHIVE_NAME}"
  tar -xzf "${TEMP_DIR}/${ARCHIVE_NAME}.tar.gz" -C "${TEMP_DIR}" >/dev/null

  if [ $? -ne 0 ]; then
    print_error "Failed to unarchive Cloudlift package."
  fi
}

install() {
  #  todo: handle upgrade or reinstall
  print_info "Installing Cloudlift package..."

  #  remove existing cloudlift package
  if [ -d "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}" ]; then
    print_info "Removing existing Cloudlift package"
    rm -rf ${PACKAGE_DEST_DIR}/${PACKAGE_NAME}
  fi

  #  remove existing symlink
  if [ -L "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}" ]; then
    print_info "Removing existing symlink"
    rm ${PACKAGE_BIN_DIR}/${PACKAGE_NAME}
  fi

  #  install cloudlift package
  print_info "Installing Cloudlift package to ${PACKAGE_DEST_DIR}/${PACKAGE_NAME}..."
  cp -r "${TEMP_DIR}/${ARCHIVE_NAME}" "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}" || {
    print_error "Failed to copy Cloudlift package."
  }

  #  create symlink
  print_info "Creating symlink..."
  ln -s "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}/cloudlift" "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}" || {
    print_error "Failed to create symlink."
  }
}

test_installation() {
  print_info "Testing Cloudlift installation..."

  if ! command -v "cloudlift" >/dev/null; then
    print_error "Failed to install Cloudlift package."
  fi

  # note: the initial run of the package (after installation) is slow. subsequent runs are faster.
  # to avoid this, the package is executed during the installation process.
  cloudlift --help >/dev/null || {
    print_error "Failed to run Cloudlift package."
  }

  _version=$(cloudlift --version | cut -d' ' -f3) || {
    print_error "Failed to get Cloudlift package version."
  }

  if [ "$_version" != "$PACKAGE_VERSION" ]; then
    print_error "Cloudlift package version mismatch."
  fi

  print_info "Cloudlift package installation test passed."
}

status_message() {
  rc=$1

  if [ "${rc}" -eq 0 ]; then
    _version=$(cloudlift --version)
    echo '''
            _                    _  _  _   __  _
       ___ | |  ___   _   _   __| || |(_) / _|| |_
      / __|| | / _ \ | | | | / _` || || || |_ | __|
     | (__ | || (_) || |_| || (_| || || ||  _|| |_
      \___||_| \___/  \__,_| \__,_||_||_||_|   \__|

    '''
    print_info "Cloudlift package installed successfully; version: ${_version}"
    print_info "Run 'cloudlift --help' to know more."
  else
    print_error "Failed to install Cloudlift package."
  fi
}

uninstall() {
  #  todo: confirmation message
  print_info "Uninstalling Cloudlift package..."

  #  check if the package exists (command
  if ! command -v "cloudlift" >/dev/null; then
    print_info "Cloudlift package not found. Exiting..."
    exit 0
  fi

  local current_version=$(cloudlift --version | cut -d' ' -f3)
  print_info "Current Cloudlift package version: ${current_version}"

  confirm_message "Do you want to uninstall Cloudlift package?"

  # remove cloudlift package
  if [ -d "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}" ]; then
    print_info "Removing Cloudlift package..."
    rm -rf "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}"
  fi

  # remove symlink
  if [ -L "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}" ]; then
    print_info "Removing symlink..."
    rm "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}"
  fi

  # the cloudlift command should be thrown an error
  if command -v "cloudlift" >/dev/null; then
    print_error "Failed to uninstall Cloudlift package."
  fi

  print_info "Cloudlift package uninstalled successfully."
}

preflight_check() {
  print_info "Running preflight checks..."

  #  if running like curl <url> | sudo bash, then set auto-approve
  if [ -z "${TERM}" ]; then
    AUTO_APPROVE=true
  fi

  if ! command -v curl >/dev/null; then
    print_error "curl is required."
  fi

  if ! command -v tar >/dev/null; then
    print_error "tar is required."
  fi

  if ! command -v gzip >/dev/null; then
    print_error "gzip is required."
  fi

  # check if the package version is latest
  if [ "${PACKAGE_VERSION}" = "latest" ]; then
    get_latest_release
  fi

  #  check if the package is already installed
  if command -v "cloudlift" >/dev/null; then

    local current_version=$(cloudlift --version | cut -d' ' -f3)
    if [ -z "${current_version}" ]; then
      print_warning "The current Cloudlift did not install properly or is corrupted."
    fi

    print_info "Cloudlift package already installed; version: v${current_version}"

    confirm_message "Do you want to reinstall Cloudlift with version v${PACKAGE_VERSION}?"
  fi
}

# ----------------------------------------
# Main
# ----------------------------------------

main() {
  if [ "${IS_UNINSTALL}" = true ]; then
    check_sudo
    uninstall

    exit 0
  fi

  print_info "${ARCHIVE_NAME}"

  check_sudo
  preflight_check
  download_cloudlift

  if [ "${SKIP_CHECKSUM}" = false ]; then
    perform_checksum
  else
    print_warning "Skipping checksum verification..."
  fi

  unarchive_cloudlift
  install
  test_installation
}

main
status_message $?
