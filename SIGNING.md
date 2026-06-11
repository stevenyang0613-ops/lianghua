# Apple Code Signing Setup

## Prerequisites

1. **Apple Developer Account** - Enroll in the [Apple Developer Program](https://developer.apple.com/programs/) ($99/year).
2. **Xcode** - Install from the Mac App Store.
3. **App-specific password** - Generate at [appleid.apple.com](https://appleid.apple.com) under "App-Specific Passwords".

## Local Development (Ad-Hoc Signing)

For development and testing, macOS automatically uses ad-hoc signing. No configuration needed.

## Production Signing

### Step 1: Create Certificates in Xcode

1. Open Xcode > Settings > Accounts
2. Add your Apple ID
3. Click "Manage Certificates"
4. Click "+" and select "Apple Development" and "Apple Distribution"

### Step 2: Export Certificates (for CI)

```bash
security find-identity -p basic -v
security export -k login.keychain -t identities -f pkcs12 -o /tmp/developer.p12
```

### Step 3: Configure GitHub Secrets

In your GitHub repo settings (Settings > Secrets and variables > Actions), add:

| Secret | Value |
|--------|-------|
| `APPLE_ID` | your@apple.id |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password |
| `APPLE_TEAM_ID` | Your Team ID |

### Step 4: Build for Release

Push a version tag:

```bash
npm version patch
git push --follow-tags
```

Or manually:

```bash
cd electron
APPLE_ID=your@apple.id APPLE_APP_SPECIFIC_PASSWORD=your-password APPLE_TEAM_ID=your-team-id \
  npx electron-builder --mac --publish=never
```

## Verification Commands

### 1. Verify Code Signing

```bash
# Check signing identity and entitlements
codesign -dv --verbose=4 /Applications/量化启动端.app

# Extract the signing certificate details
codesign -d --extract-certificates /tmp/signing.cer /Applications/量化启动端.app
openssl x509 -inform DER -in /tmp/signing.cer.0 -noout -text | grep -A 2 'Subject:'
```

Expected output includes:
- `Authority: Apple Distribution: Your Company (TEAMID)`
- `Authority: Apple Worldwide Developer Relations Certification Authority`
- All required entitlements are present

### 2. Verify Notarization

```bash
# Check notarization status (from outside the app)
spctl -a -t exec -vv /Applications/量化启动端.app

# Check using stapled ticket
xcrun stapler validate /Applications/量化启动端.app
```

Expected notarization output:
- `source=Notarized`
- `origin=Apple Distribution: Your Company (TEAMID)`

### 3. Check Embedded Backend Binary

```bash
# Verify the PyInstaller binary inside the .app is also signed
codesign -dv --verbose=4 /Applications/量化启动端.app/Contents/Resources/backend/lianghua-backend

# Check if it's an Apple Silicon binary
file /Applications/量化启动端.app/Contents/Resources/backend/lianghua-backend
```

Expected:
- PyInstaller binary should be signed with same certificate
- Architecture should be `arm64` (Apple Silicon) or `x86_64` (Intel)

## Troubleshooting

### Signing Failures

| Error | Cause | Fix |
|-------|-------|-----|
| `code object is not signed at all` | PyInstaller binary not signed | Add `--extra-resources` signing to electron-builder config, or manually sign with `codesign --force --sign "Developer ID Application" --options runtime --entitlements entitlements.mac.plist <binary>` |
| `The executable does not have the hardened runtime` | Missing `--options runtime` on sign | Ensure `hardenedRuntime: true` in package.json |
| `Library not loaded: @rpath/...` | Disable library validation needed | Check `com.apple.security.cs.disable-library-validation` in entitlements |
| `No matching provisioning profiles found` | Team ID mismatch | Verify `APPLE_TEAM_ID` secret is correct |
| `Notarization: Invalid` | Binary has issues found by Apple | Run `xcrun notarytool log --apple-id ... --password ... --team-id ... <submission-id>` to see details |

### CI-Specific Issues

- **Missing secrets**: Without `APPLE_ID` and `APPLE_APP_SPECIFIC_PASSWORD`, the build falls back to ad-hoc signing. The resulting `.app` will not run on other Macs.
- **PyInstaller binary size**: If the `lianghua-backend` binary is very large (>500MB), signing may time out. Use `--exclude-module` to slim it down.
- **GitHub Actions runner**: The `macos-latest` runner produces `arm64` binaries by default. For `x86_64` builds, target `macos-13` (Intel).</｜DSML｜parameter>

- [electron-builder code signing docs](https://www.electron.build/code-signing)
- [Apple Notarization docs](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution)
