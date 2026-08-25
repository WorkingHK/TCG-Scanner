#!/bin/bash
# TCG Scanner - One-Click Environment Setup
# Run with: bash setup.sh

set -e  # Exit on error

echo "🎴 TCG Scanner - Environment Setup"
echo "=================================="
echo ""

# Check if conda is installed
if ! command -v conda &> /dev/null; then
    echo "❌ Error: conda not found!"
    echo "Please install Miniforge or Miniconda first:"
    echo "  https://github.com/conda-forge/miniforge"
    exit 1
fi

echo "✓ Conda found: $(conda --version)"
echo ""

# Get the conda env name from environment.yml
ENV_NAME=$(grep "^name:" environment.yml | awk '{print $2}')

# Check if environment already exists
if conda env list | grep -q "^${ENV_NAME} "; then
    echo "⚠️  Environment '${ENV_NAME}' already exists."
    read -p "Do you want to remove and recreate it? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing environment..."
        conda env remove -n "${ENV_NAME}" -y
    else
        echo "Updating existing environment..."
        conda env update -f environment.yml --prune
        echo ""
        echo "✓ Environment updated!"
        echo ""
        echo "To activate: conda activate ${ENV_NAME}"
        echo "To run app:  PYTHONPATH=. python desktop/main_window.py"
        exit 0
    fi
fi

# Create conda environment
echo "Creating conda environment from environment.yml..."
conda env create -f environment.yml

echo ""
echo "✅ Setup complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Next steps:"
echo ""
echo "1. Activate environment:"
echo "   conda activate ${ENV_NAME}"
echo ""
echo "2. Configure API key (choose one):"
echo "   • Via Settings UI (recommended)"
echo "   • Or: export ANTHROPIC_API_KEY=sk-ant-..."
echo ""
echo "3. Run desktop app:"
echo "   PYTHONPATH=. python desktop/main_window.py"
echo ""
echo "4. Run tests:"
echo "   pytest"
echo ""
echo "5. Check camera index:"
echo "   python -c 'from tcg_grading.capture import UVCCamera; UVCCamera.list_devices()'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
