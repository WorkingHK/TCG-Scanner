#!/bin/bash
# TCG Scanner - Complete Installer
# This script installs everything needed to run TCG Scanner

set -e

INSTALL_DIR="$HOME/TCGScanner"
MINIFORGE_URL="https://github.com/conda-forge/miniforge/releases/latest/download"

echo "╔════════════════════════════════════════════════╗"
echo "║   TCG Scanner - Automated Installer           ║"
echo "║   AI-Powered Pokemon Card Grading System      ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# Detect architecture
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
    MINIFORGE_FILE="Miniforge3-MacOSX-arm64.sh"
elif [[ "$ARCH" == "x86_64" ]]; then
    MINIFORGE_FILE="Miniforge3-MacOSX-x86_64.sh"
else
    echo "❌ Unsupported architecture: $ARCH"
    exit 1
fi

echo "✓ Detected architecture: $ARCH"
echo ""

# Check if conda is already installed
if command -v conda &> /dev/null; then
    echo "✓ Conda already installed: $(conda --version)"
    CONDA_INSTALLED=true
else
    echo "⚠️  Conda not found. Will install Miniforge..."
    CONDA_INSTALLED=false
fi

echo ""
echo "Installation will:"
echo "  1. Install Miniforge (if needed)"
echo "  2. Create tcg-grading Python environment"
echo "  3. Install all dependencies"
echo "  4. Create desktop launcher"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Installation cancelled."
    exit 0
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1: Setting up Conda"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ "$CONDA_INSTALLED" = false ]; then
    echo "Downloading Miniforge..."
    cd /tmp
    curl -L -O "${MINIFORGE_URL}/${MINIFORGE_FILE}"

    echo "Installing Miniforge..."
    bash "${MINIFORGE_FILE}" -b -p "$HOME/miniforge3"

    echo "Initializing conda..."
    "$HOME/miniforge3/bin/conda" init bash zsh

    # Source conda for this script
    eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"

    echo "✓ Miniforge installed successfully"
    rm "${MINIFORGE_FILE}"
else
    # Initialize conda for this script
    if [ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniforge3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    else
        eval "$(conda shell.bash hook)"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: Installing TCG Scanner"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create installation directory
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Copy project files (assumes this script is run from the repo)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "Copying project files from: $SCRIPT_DIR"
rsync -av --exclude='.git' --exclude='captures' --exclude='__pycache__' --exclude='*.pyc' "$SCRIPT_DIR/" "$INSTALL_DIR/"

# Create conda environment
if conda env list | grep -q "^tcg-grading "; then
    echo "⚠️  Environment 'tcg-grading' already exists. Updating..."
    conda env update -f environment.yml --prune
else
    echo "Creating conda environment..."
    conda env create -f environment.yml
fi

echo "✓ Environment created successfully"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3: Creating Launcher"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Create launcher script in user's home directory
cat > "$HOME/Desktop/TCG Scanner.command" << 'LAUNCHER_EOF'
#!/bin/bash
# TCG Scanner Launcher

# Initialize conda
if [ -f "$HOME/miniforge3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniforge3/etc/profile.d/conda.sh"
elif [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
else
    eval "$(conda shell.bash hook)"
fi

# Navigate to install directory
cd "$HOME/TCGScanner"

# Activate environment
conda activate tcg-grading

# Run app
echo "🎴 Starting TCG Scanner..."
echo ""
PYTHONPATH=. python desktop/main_window.py
LAUNCHER_EOF

chmod +x "$HOME/Desktop/TCG Scanner.command"

echo "✓ Desktop launcher created: ~/Desktop/TCG Scanner.command"

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║          ✅ Installation Complete!             ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "Installation directory: $INSTALL_DIR"
echo ""
echo "How to run:"
echo "  • Double-click 'TCG Scanner.command' on your Desktop"
echo "  • Or run: bash '$HOME/Desktop/TCG Scanner.command'"
echo ""
echo "First-time setup:"
echo "  1. Click ⚙ Settings in the app"
echo "  2. Paste your Anthropic API key"
echo "  3. Select your camera"
echo "  4. Fill in card metadata"
echo ""
echo "⚠️  IMPORTANT: If this is your first time installing conda,"
echo "    please restart your Terminal or run:"
echo "    source ~/.zshrc  (or ~/.bashrc)"
echo ""
