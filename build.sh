#!/bin/bash
# build.sh
# Packages Function Compute code with vendored dependencies

echo "=== Packaging Function Compute Deployment Package ==="

# Clean build directory
rm -rf infra/terraform/build
mkdir -p infra/terraform/build/dist

# Install python dependencies to package directory
echo "Installing pip dependencies to build directory..."
pip install -r src/requirements.txt --target=infra/terraform/build/dist --upgrade --only-binary=:all:

# Copy source code files (excluding static UI assets and database caches)
echo "Copying source code files..."
cp -R src/* infra/terraform/build/dist/
rm -rf infra/terraform/build/dist/static
rm -rf infra/terraform/build/dist/oss_mock_archive
rm -rf infra/terraform/build/dist/__pycache__
rm -f infra/terraform/build/dist/agent_ops.db

# Zip the payload
echo "Zipping payload package..."
cd infra/terraform/build/dist && zip -q -r ../function.zip . && cd -

echo "Build package completed at: infra/terraform/build/function.zip"
