#!/bin/bash
# TCG Scanner - Simple App Launcher
# Double-click this file in Finder to run the app

set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "🎴 TCG Scanner - Starting..."
echo ""

# Check if conda is installed
if ! command -v conda &> /dev/null; then
    echo "❌ Error: conda not found!"
    echo ""
    echo "Please run setup.sh first to install the environment."
    echo "Or install Miniforge from: https://github.com/conda-forge/miniforge"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

# Get environment name
ENV_NAME=$(grep "^name:" environment.yml | awk '{print $2}')

# Check if environment exists
if ! conda env list | grep -q "^${ENV_NAME} "; then
    echo "❌ Environment '${ENV_NAME}' not found!"
    echo ""
    echo "Please run setup.sh first:"
    echo "  bash setup.sh"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

echo "✓ Found environment: ${ENV_NAME}"
echo "✓ Launching TCG Scanner..."
echo ""

# Initialize conda for this shell
eval "$(conda shell.bash hook)"

# Activate environment and run app
conda activate "${ENV_NAME}"
PYTHONPATH=. python desktop/main_window.py
