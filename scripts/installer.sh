#!/bin/sh

set -e

# ----------------------------------------
# Configuration
# ----------------------------------------

WORK_DIR=$(pwd)
TEMP_DIR="/tmp/cloudlift"
PACKAGE_NAME="cloudlift"
PACKAGE_DEST_DIR="/usr/local"
PACKAGE_BIN_DIR="/usr/local/bin"

PACKAGE_VERSION="latest"
ARCH_TYPE=$(uname -m)
OS_TYPE=$(uname -s | tr '[:upper:]' '[:lower:]')

if [ "${OS_TYPE}" = "linux" ]; then
  # check if the OS is Alpine Linux
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [ "${ID}" = "alpine" ]; then
      OS_TYPE="alpine"
    fi
  fi
fi

REPO_OWNER="GetSimpl"
DOWNLOAD_BASE_URL="https://github.com/${REPO_OWNER}/cloudlift/releases/download"
RELEASES_URL="https://api.github.com/repos/${REPO_OWNER}/cloudlift/releases"
LATEST_RELEASE_URL="${RELEASES_URL}/latest"

IS_UNINSTALL=false
AUTO_APPROVE=false

SUPPORTED_TYPES="linux-x86_64 alpine-x86_64 darwin-arm64"

# ----------------------------------------
# Helper Functions
# ----------------------------------------

print_message() {
  # Using printf for better compatibility
  printf "\033[0;%sm[%s]\033[0m %s\n" "$1" "$2" "$3"
}

print_info() { print_message "32" "INFO" "$1"; }
print_warning() { print_message "33" "WARN" "$1"; }
print_error() {
  print_message "31" "ERROR" "$1"
  exit 1
}

confirm_message() {
  if [ "${AUTO_APPROVE}" = true ]; then
    print_info "Auto-approving..."
    return 0
  fi
  printf "%s [y/N]: " "$1"
  read -r confirm
  case "$confirm" in
  [Yy]*) return 0 ;;
  *)
    print_warning "Exiting..."
    exit 0
    ;;
  esac
}

# ----------------------------------------
# Core Functions
# ----------------------------------------

check_sudo() {
  print_info "Checking if running as root..."
  if [ "$(id -u)" -ne 0 ]; then
    print_error "Please run as root or with sudo."
  fi
}

get_latest_release() {
  print_info "Getting latest release version..."
  latest_release=$(curl -sL "${LATEST_RELEASE_URL}" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p')
  [ -z "${latest_release}" ] && print_error "Failed to get latest release version."
  PACKAGE_VERSION=$(echo "${latest_release}" | sed 's/^v//')
  print_info "Latest release version: v${PACKAGE_VERSION}"
}

validate_release() {
  all_releases_details=$(curl -sL "${RELEASES_URL}")
  all_releases=$(echo "${all_releases_details}" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | sed 's/^v//' | sort -V)

  if ! echo "${all_releases}" | grep -q "${PACKAGE_VERSION}"; then
    print_error "Could not find Cloudlift release with version: v${PACKAGE_VERSION}\nAvailable versions:\n${all_releases}"
  fi

  if ! echo "${all_releases_details}" | grep -q "${ARCHIVE_NAME}"; then
    print_error "Could not find Cloudlift release with archive: ${ARCHIVE_NAME}"
  fi
}

download_cloudlift() {
  ARCHIVE_NAME="${PACKAGE_NAME}-${OS_TYPE}-${ARCH_TYPE}-v${PACKAGE_VERSION}"
  print_info "Downloading Cloudlift package for: ${ARCHIVE_NAME}"
  validate_release

  supported_os_arch="${OS_TYPE}-${ARCH_TYPE}"
  if ! echo "${SUPPORTED_TYPES}" | grep -q "${supported_os_arch}"; then
    print_error "Unsupported OS type: ${OS_TYPE}-${ARCH_TYPE}. Cloudlift package is not available for this OS type yet."
  fi

  download_url="${DOWNLOAD_BASE_URL}/v${PACKAGE_VERSION}/${ARCHIVE_NAME}.tar.gz"
  print_info "Downloading from: ${download_url}"
  mkdir -p "${TEMP_DIR}"
  if ! curl -L -o "${TEMP_DIR}/${ARCHIVE_NAME}.tar.gz" "${download_url}"; then
    print_error "Failed to download Cloudlift package."
  fi
}

verify_checksum() {
  print_info "Verifying checksum..."
  checksum_url="${DOWNLOAD_BASE_URL}/v${PACKAGE_VERSION}/checksums.txt"
  if ! curl -L -o "${TEMP_DIR}/checksums.txt" "${checksum_url}"; then
    print_error "Failed to download checksum."
  fi

  checksum=$(grep "${ARCHIVE_NAME}.tar.gz" "${TEMP_DIR}/checksums.txt" | cut -d' ' -f2)
  if [ "${OS_TYPE}" = "darwin" ]; then
    verify_cmd="shasum -a 256"
  else
    verify_cmd="sha256sum"
  fi

  if ! ${verify_cmd} "${TEMP_DIR}/${ARCHIVE_NAME}.tar.gz" | grep -q "${checksum}"; then
    print_error "Checksum mismatch. Installation aborted for security reasons."
  fi
}

unarchive_cloudlift() {
  print_info "Unarchiving Cloudlift package..."
  [ -d "${TEMP_DIR}/${ARCHIVE_NAME}" ] && rm -rf "${TEMP_DIR}/${ARCHIVE_NAME}"
  if ! tar -xzf "${TEMP_DIR}/${ARCHIVE_NAME}.tar.gz" -C "${TEMP_DIR}" >/dev/null; then
    print_error "Failed to unarchive Cloudlift package."
  fi
}

install_cloudlift() {
  print_info "Installing Cloudlift package..."
  [ -d "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}" ] && rm -rf "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}"
  [ -L "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}" ] && rm "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}"

  if ! cp -r "${TEMP_DIR}/${ARCHIVE_NAME}" "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}"; then
    print_error "Failed to copy Cloudlift package."
  fi
  if ! ln -s "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}/cloudlift" "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}"; then
    print_error "Failed to create symlink."
  fi
}

test_installation() {
  print_info "Testing Cloudlift installation..."
  if ! command -v "cloudlift" >/dev/null; then
    print_error "Failed to install Cloudlift package."
  fi
  if ! cloudlift --help >/dev/null; then
    print_error "Failed to run Cloudlift package."
  fi
  installed_version=$(cloudlift --version | cut -d' ' -f3)
  if [ "${installed_version}" != "${PACKAGE_VERSION}" ]; then
    print_error "Cloudlift package version mismatch."
  fi
  print_info "Cloudlift package installation test passed."
}

uninstall_cloudlift() {
  print_info "Uninstalling Cloudlift package..."
  if ! command -v "cloudlift" >/dev/null; then
    print_info "Cloudlift package not found. Exiting..."
    exit 0
  fi
  current_version=$(cloudlift --version | cut -d' ' -f3)
  print_info "Current Cloudlift package version: ${current_version}"
  confirm_message "Do you want to uninstall Cloudlift package?"

  [ -d "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}" ] && rm -rf "${PACKAGE_DEST_DIR}/${PACKAGE_NAME}"
  [ -L "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}" ] && rm "${PACKAGE_BIN_DIR}/${PACKAGE_NAME}"

  if command -v "cloudlift" >/dev/null; then
    print_error "Failed to uninstall Cloudlift package."
  fi
  print_info "Cloudlift package uninstalled successfully."
}

preflight_check() {
  print_info "Running preflight checks..."
  [ -z "${TERM}" ] && AUTO_APPROVE=true
  for cmd in curl tar gzip; do
    if ! command -v "$cmd" >/dev/null; then
      print_error "$cmd is required."
    fi
  done

  [ "${PACKAGE_VERSION}" = "latest" ] && get_latest_release

  if command -v "cloudlift" >/dev/null; then
    current_version=$(cloudlift --version | cut -d' ' -f3)
    [ -z "${current_version}" ] && print_warning "The current Cloudlift did not install properly or is corrupted."
    print_info "Cloudlift package already installed; version: v${current_version}"
    confirm_message "Do you want to reinstall Cloudlift with version v${PACKAGE_VERSION}?"
  fi
}

# ----------------------------------------
# Main Execution
# ----------------------------------------

parse_arguments() {
  while [ $# -gt 0 ]; do
    case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    -v | --version)
      shift
      PACKAGE_VERSION=$(echo "$1" | sed 's/^v//')
      ;;
    -u | --uninstall)
      IS_UNINSTALL=true
      ;;
    -y | --auto-approve)
      AUTO_APPROVE=true
      ;;
    *)
      print_error "Invalid argument: $1"
      ;;
    esac
    shift
  done
}

main() {
  parse_arguments "$@"

  print_info "Cloudlift installation started..."
  print_info "For OS: ${OS_TYPE}, Arch: ${ARCH_TYPE}, Version: ${PACKAGE_VERSION}"

  check_sudo

  if [ "${IS_UNINSTALL}" = true ]; then
    uninstall_cloudlift
  else
    preflight_check
    download_cloudlift
    verify_checksum
    unarchive_cloudlift
    install_cloudlift
    test_installation
  fi
}

status_message() {
  if [ $1 -eq 0 ]; then
    version=$(cloudlift --version)
    printf '
            _                    _  _  _   __  _
       ___ | |  ___   _   _   __| || |(_) / _|| |_
      / __|| | / _ \ | | | | / _` || || || |_ | __|
     | (__ | || (_) || |_| || (_| || || ||  _|| |_
      \___||_| \___/  \__,_| \__,_||_||_||_|   \__|

        \n'
    print_info "Cloudlift package installed successfully; version: ${version}"
    print_info "Run 'cloudlift --help' to know more."
  else
    print_error "Failed to install Cloudlift package."
  fi
}

main "$@"
status_message $?
