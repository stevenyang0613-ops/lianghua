#!/bin/bash
set -e

echo "Building Electron main process..."

cd electron

# Clean dist directory
rm -rf dist

# Compile TypeScript
npx tsc

echo "Electron build complete!"
echo "Output: electron/dist/"
