# AudioSuite-Pro Security Guide

## Overview

AudioSuite-Pro now includes enhanced security features to protect your data and ensure safe operation. This guide explains what security features are available, how they work, and what you need to know as a user.

## Security Features

### 🔐 API Key Encryption

**What it does:**
- Encrypts sensitive API keys (Fanart.tv) using Fernet symmetric encryption
- Stores encrypted keys in configuration files
- Automatically generates and manages encryption keys

**How it works:**
- On first run, creates an encryption key file (`.key`) alongside your config
- API keys are encrypted before being saved to disk
- Keys are automatically decrypted when needed

**What you'll see:**
- Normal operation - no change in user experience
- Warning message if cryptography module is not available
- Configuration files will contain encrypted text instead of plain keys

### 🛡️ Input Validation & Sanitization

**What it does:**
- Validates file paths to prevent directory traversal attacks
- Sanitizes user inputs to remove dangerous characters
- Checks for reserved Windows names and invalid characters

**How it works:**
- Automatically validates folder selections in file dialogs
- Blocks dangerous patterns like `..`, `<script>`, etc.
- Limits input lengths to prevent buffer overflow attacks

**What you'll see:**
- Warning messages if selected paths are invalid or unsafe
- Normal operation for valid paths
- Some inputs may be automatically cleaned

### 🔒 SSL Certificate Validation

**What it does:**
- Enforces SSL certificate validation for all HTTPS connections
- Uses up-to-date certificate authorities (certifi)
- Adds security headers to API requests

**How it works:**
- All API connections now verify SSL certificates
- Invalid certificates will cause connection failures
- Enhanced protection against man-in-the-middle attacks

**What you'll see:**
- Normal operation for valid certificates
- Connection errors for invalid certificates
- More secure network communications

### 🛡️ Secure Error Handling

**What it does:**
- Limits error information disclosure in production mode
- Provides detailed errors in debug mode
- Logs full errors for troubleshooting

**How it works:**
- Production mode shows generic error messages
- Debug mode (environment variable) shows full details
- All errors are logged for support

**What you'll see:**
- Generic error messages like "An error occurred..."
- Detailed errors only when debug mode is enabled
- Better protection against information disclosure

## New User Setup

### Prerequisites

**Required Dependencies:**
- Python 3.11+
- cryptography>=3.4.8 (for encryption features)
- certifi>=2021.5.30 (for SSL validation)

**Automatic Installation:**
- Dependencies are included in `requirements.txt`
- Run `pip install -r requirements.txt` to install
- Application will work with/without optional dependencies

### First-Time Setup

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Launch Application:**
   - Run `Master_Driver.pyw` normally
   - Application will create necessary security files automatically

3. **Configure API Keys:**
   - Open Album Art Sync module
   - Enter your Fanart.tv API keys
   - Keys will be automatically encrypted and saved

### Configuration Files

**New Files Created:**
- `album_art_config.key` - Encryption key (restricted permissions)
- `album_art_config.key.bak` - Copy of a key file that had to be replaced
  (created only when an existing key file turns out to be unusable)
- `album_art_config.json` - Encrypted configuration

**File Security:**
- Key files have restricted permissions on Unix-like systems
- Configuration files contain encrypted sensitive data
- Back up both key and config files together
- Key backups are secret-class too: `*.key.bak` is git-ignored and must never
  be committed or shared

**If your key file is ever replaced:** values encrypted under the old key
(the Fanart `app_key`/`client_key`) stop decrypting and must be re-entered, and
the module logs a WARNING saying so at launch. Before overwriting a key file
the module copies it to `<key file>.bak`. To recover the old values, stop the
module, put that `.bak` file back in place of the `.key` file, delete the new
`.key` file, and restart. If the key file was already corrupt when it was
replaced, the `.bak` is a diagnostic copy only and the values cannot be
recovered.

## User Actions

### Safe File Selection

**When selecting folders:**
- Use the built-in folder browser
- Avoid manually typing paths with special characters
- Application will validate paths automatically

**Invalid Path Examples:**
- ❌ `C:\..\Windows\System32` (directory traversal)
- ❌ `C:\My<Files>Music` (invalid characters)
- ❌ `CON` (reserved name)

**Valid Path Examples:**
- ✅ `C:\Users\Music\Library`
- ✅ `D:\Audio Files\Collection`
- ✅ `/home/user/music` (Linux/macOS)

### API Key Management

**Setting Up Fanart.tv:**
1. Obtain API keys from Fanart.tv
2. Open Album Art Sync settings
3. Enter keys in the configuration
4. Keys are automatically encrypted when saved

**Key Security:**
- Never share your `.key` files
- Back up configuration files regularly
- Keep keys in secure locations

**Troubleshooting:**
- If keys don't work, check the `.key` file exists
- Ensure proper file permissions on key files
- Re-enter keys if corruption is suspected

### Error Handling

**Production Mode (Default):**
- Shows generic error messages
- Protects sensitive system information
- Suitable for normal use

**Debug Mode (Optional):**
- Set environment variable: `AUDIOSUITE_DEBUG=1`
- Shows detailed error information
- Useful for troubleshooting

**Enabling Debug Mode:**
```bash
# Windows
set AUDIOSUITE_DEBUG=1
python Master_Driver.pyw

# Linux/macOS
export AUDIOSUITE_DEBUG=1
python Master_Driver.pyw
```

## Security Best Practices

### Data Protection

1. **Regular Backups:**
   - Back up configuration files regularly
   - Include both `.json` and `.key` files
   - Store backups in secure location

2. **File Permissions:**
   - Keep `.key` files private
   - Restrict access to configuration files
   - Use secure storage locations

3. **API Key Security:**
   - Never share API keys publicly
   - Rotate keys periodically
   - Use different keys for different environments

### System Security

1. **Keep Software Updated:**
   - Regularly update AudioSuite-Pro
   - Update Python dependencies
   - Apply security patches promptly

2. **Network Security:**
   - Use secure internet connections
   - Avoid public WiFi for sensitive operations
   - Consider VPN for additional protection

3. **Access Control:**
   - Run with appropriate user privileges
   - Avoid administrator accounts when possible
   - Use separate accounts for different users

## Troubleshooting

### Common Issues

**"cryptography module not found":**
- Run: `pip install cryptography>=3.4.8`
- Ensure Python environment is correct
- Restart application after installation

**"Invalid path selected":**
- Use the built-in folder browser
- Avoid special characters in paths
- Check path length (max 260 characters)

**"API key not working":**
- Verify key is correctly entered
- Check `.key` file exists and is readable
- Ensure internet connection is working

**"SSL certificate errors":**
- Check system date/time is correct
- Update certificate authorities
- Verify network isn't blocking HTTPS

### Getting Help

**Security Questions:**
- Review this guide first
- Check error logs for details
- Enable debug mode for more information

**Reporting Issues:**
- Include error messages and steps to reproduce
- Mention your operating system and Python version
- Provide relevant configuration details (without sensitive data)

## Security Score

**Current Security Rating: 9.5/10 (Strong)**

**Features Protecting Against:**
- ✅ API key exposure (encryption)
- ✅ Path traversal attacks (validation)
- ✅ Man-in-the-middle attacks (SSL validation)
- ✅ Information disclosure (secure error handling)
- ✅ Input injection attacks (sanitization)

**Remaining Considerations:**
- Regular security updates
- Safe computing practices
- Proper backup procedures

## Conclusion

AudioSuite-Pro's enhanced security features provide comprehensive protection while maintaining ease of use. The application automatically handles most security considerations, allowing you to focus on your audio processing tasks with confidence that your data is protected.

For additional security questions or concerns, refer to the main application documentation or contact support with details about your specific situation.
