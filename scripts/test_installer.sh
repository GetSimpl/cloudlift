#!/bin/bash

set -euo pipefail

cleanup() {
    echo "Cleaning up..."
    kill $SERVER_PID 2>/dev/null || true
}

current_tag="$1"
if [ -z "$current_tag" ]; then
    echo "Error: No tag provided" >&2
    exit 1
fi
echo "Current tag: $current_tag"

# Get the current tag
# current_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "v1.0.0")

create_mock_files() {
    # Create JSON response to mock GitHub's release API endpoint
    echo "{\"tag_name\":\"$current_tag\"}" > release_api_res.json
}

start_server() {
    python3 -m http.server 3000 &
    SERVER_PID=$!
    echo "Server started with PID: $SERVER_PID"

    # Wait for the server to start
    while ! curl -s http://localhost:3000 > /dev/null; do
        sleep 1
    done
}

run_installer() {
    # Run installer with given arguments
    local input="$1"
    shift
    echo "$input" | sudo -E ./installer.sh "$@" 2>&1
}

test_fresh_install() {
    echo "Testing fresh installation..."
    run_installer "y"
    current_tag_without_v="${current_tag#v}" 
    cloudlift --version
    if cloudlift --version | grep -q $current_tag_without_v; then
        echo "Fresh install test passed"
    else
        echo "Fresh install test failed"
        return 1
    fi
}

test_reinstall() {
    echo "Testing reinstallation..."
    run_installer "y"
    current_tag_without_v="${current_tag#v}" 
    if sudo cloudlift --version | grep -q $current_tag_without_v; then
        echo "Reinstall test passed"
    else
        echo "Reinstall test failed"
        return 1
    fi
}

test_specific_version() {
    echo "Testing installation of specific version..."
    current_tag_without_v="${current_tag#v}"
    run_installer "y" "-v" $current_tag_without_v
    if cloudlift --version | grep -q $current_tag_without_v; then
        echo "Specific version install test passed"
    else
        echo "Specific version install test failed"
        return 1
    fi
}

test_uninstall() {
    echo "Testing uninstallation..."
    output=$(run_installer "y" "-u" 2>&1)
    # echo "$output" 
    if echo "$output" | grep -q "Cloudlift package uninstalled successfully"; then
        if which cloudlift &> /dev/null; then
            echo "Uninstall test failed: cloudlift command still exists"
            return 1
        else
            echo "Uninstall test passed"
        fi
    else
        echo "Uninstall test failed: uninstallation message not found"
        return 1
    fi
}

test_auto_approve() {
    echo "Testing auto-approve installation..."
    output=$(sudo -E ./installer.sh -y 2>&1)
    echo "Installer output:"
    echo "$output"
    
    if echo "$output" | grep -q "Cloudlift package installed successfully"; then
        installed_version=$(sudo cloudlift --version | cut -d' ' -f3)
        echo "Installed Cloudlift version: $installed_version"
        echo "Current tag: $current_tag"
        
        if [ -n "$installed_version" ]; then
            echo "Auto-approve install test passed"
        else
            echo "Auto-approve install test failed: Could not detect installed version"
            return 1
        fi
    else
        echo "Auto-approve install test failed: Installation was not successful"
        return 1
    fi
}

main() {
    create_mock_files
    start_server

    export CLOUDLIFT_LATEST_RELEASE_URL="http://localhost:3000/release_api_res.json"
    export CLOUDLIFT_DOWNLOAD_BASE_URL="http://localhost:3000"

    test_fresh_install
    test_reinstall
    test_specific_version
    test_uninstall
    test_auto_approve

    echo "All tests completed."
}

main