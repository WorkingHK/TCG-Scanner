# Creating a GitHub Release for TCG Scanner

Follow these steps to create a downloadable release that anyone can install:

---

## Step 1: Prepare the Release

```bash
cd "/Users/anthony/Documents/Axonex/TCG Scanner"

# Make sure all scripts are executable
chmod +x install.sh setup.sh run_app.sh

# Commit the installer
git add install.sh setup.sh run_app.sh INSTALL.md
git commit -m "Add automated installer for releases"
git push origin main
```

---

## Step 2: Create a Git Tag

```bash
# Tag the current version
git tag -a v0.1.3 -m "Release v0.1.3 - Automated installer"

# Push the tag
git push origin v0.1.3
```

---

## Step 3: Create GitHub Release

### Option A: Using GitHub Web Interface

1. Go to your repository on GitHub
2. Click **Releases** (right sidebar)
3. Click **Draft a new release**
4. Fill in:
   - **Tag:** `v0.1.3` (select existing tag)
   - **Release title:** `TCG Scanner v0.1.3 - One-Click Installer`
   - **Description:**
     ```markdown
     # TCG Scanner v0.1.3
     
     AI-powered Pokemon card grading system with automated installer.
     
     ## Installation (For Non-Technical Users)
     
     1. Download `install.sh` below
     2. Open Terminal (Applications → Utilities → Terminal)
     3. Drag `install.sh` into Terminal and press Enter
     4. Follow the prompts
     5. Double-click "TCG Scanner.command" on your Desktop when done
     
     **Full guide:** See [INSTALL.md](https://github.com/YOUR_USERNAME/tcg-scanner/blob/main/INSTALL.md)
     
     ## What's New
     
     - ✅ One-click automated installer
     - ✅ Auto-installs Miniforge + all dependencies
     - ✅ Creates desktop launcher
     - ✅ CV-driven grading with VLM validation
     - ✅ Corner radius measurement (3mm standard)
     - ✅ Black frame support
     
     ## System Requirements
     
     - macOS 10.15+ (Catalina or newer)
     - 4GB free disk space
     - Internet connection
     - Camera (USB or built-in)
     
     ## Files
     
     - `install.sh` - Automated installer (download this)
     - `Source code (zip)` - For developers
     ```

5. **Attach files:**
   - Upload `install.sh` as a release asset
   - GitHub auto-generates source code archives

6. Click **Publish release**

### Option B: Using GitHub CLI

```bash
# Install gh CLI if needed
brew install gh

# Authenticate
gh auth login

# Create release
gh release create v0.1.3 \
  --title "TCG Scanner v0.1.3 - One-Click Installer" \
  --notes "One-click installer for non-technical users. See INSTALL.md for instructions." \
  install.sh
```

---

## Step 4: Test the Release

1. Go to the Releases page
2. Download `install.sh`
3. Run it in a clean environment (or ask someone else to test)
4. Verify:
   - Miniforge installs correctly
   - Environment creates successfully
   - Desktop launcher appears
   - App runs without errors

---

## Step 5: Update README

Add a prominent download link at the top of README.md:

```markdown
## 📦 Download & Install

**Latest Release:** [v0.1.3 - One-Click Installer](https://github.com/YOUR_USERNAME/tcg-scanner/releases/latest)

**For non-technical users:** Download `install.sh` from the release page and follow [INSTALL.md](INSTALL.md)

**For developers:** See [Setup](#setup) below
```

---

## Distribution Options

### Option 1: Public GitHub Release (Easiest)
- ✅ Free hosting
- ✅ Automatic downloads
- ✅ Version tracking
- ❌ Repository must be public

### Option 2: Private Release with Access Control
- Use GitHub private repo with invited collaborators
- Or host `install.sh` on your own server/Dropbox

### Option 3: macOS App Bundle (Advanced)
- Package as a standalone `.app` using PyInstaller or py2app
- Larger download (~500MB) but truly one-click
- Requires code signing for distribution

---

## User Experience

After you create the release, users can:

1. **Visit your releases page**
2. **Download `install.sh`**
3. **Run one command:**
   ```bash
   bash ~/Downloads/install.sh
   ```
4. **Double-click the desktop launcher**

No coding knowledge required!

---

## Maintenance

For future releases:

```bash
# Update version
git tag -a v0.1.4 -m "Release v0.1.4 - Bug fixes"
git push origin v0.1.4

# Create new release with updated install.sh
gh release create v0.1.4 --title "..." --notes "..." install.sh
```
