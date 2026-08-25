# TCG Scanner - Installation Guide

## For Complete Beginners (Non-Technical Users)

### Quick Install (Recommended)

1. **Download the installer:**
   - Go to the [GitHub Releases page](https://github.com/YOUR_USERNAME/tcg-scanner/releases)
   - Download `install.sh` from the latest release

2. **Run the installer:**
   - Open **Terminal** (Applications → Utilities → Terminal)
   - Drag the `install.sh` file into the Terminal window
   - Press Enter
   - Type `y` when asked to continue

3. **Wait 5-10 minutes** while it installs everything

4. **Double-click "TCG Scanner.command"** on your Desktop to run the app

That's it! The installer handles everything automatically.

---

## What Gets Installed?

- **Miniforge** (Python package manager) → `~/miniforge3/`
- **TCG Scanner** (the app + all dependencies) → `~/TCGScanner/`
- **Desktop launcher** → `~/Desktop/TCG Scanner.command`

Total size: ~2GB

---

## First-Time App Setup

After launching the app:

1. Click **⚙ Settings**
2. Paste your **Anthropic API key** (get one at https://console.anthropic.com)
3. Select your **camera** from the dropdown
4. Fill in **card metadata** (name, set, cert number)
5. Click **Save**

Now you're ready to grade cards!

---

## Uninstalling

To completely remove TCG Scanner:

```bash
# Remove the app
rm -rf ~/TCGScanner

# Remove desktop launcher
rm ~/Desktop/TCG\ Scanner.command

# (Optional) Remove Miniforge if you don't need it for other projects
rm -rf ~/miniforge3
```

---

## System Requirements

- **macOS 10.15+** (Catalina or newer)
- **4GB free disk space**
- **Internet connection** (for AI grading)
- **Camera** (USB or built-in)

---

## Troubleshooting

### "Operation not permitted" error
- macOS blocked the script for security
- **Fix:** Right-click `install.sh` → Open With → Terminal

### Installation fails at "Downloading Miniforge"
- Check your internet connection
- Try again (the installer is resumable)

### "TCG Scanner.command" doesn't open
- Right-click it → Open (macOS will ask for permission)
- Or: Open Terminal and run: `bash ~/Desktop/TCG\ Scanner.command`

### App opens but grading fails
- API key not set
- **Fix:** Open Settings (⚙) and paste your Anthropic API key

---

## Getting Help

- **GitHub Issues:** https://github.com/YOUR_USERNAME/tcg-scanner/issues
- **Email:** support@example.com

When reporting issues, include:
- macOS version (About This Mac)
- Error message screenshot
- Last 20 lines from Terminal
