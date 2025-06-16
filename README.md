# WISPr Portal Troubleshooting Tool

A web application for troubleshooting WISPr (Wireless Internet Service Provider roaming) portal redirection with RUCKUS One. This tool helps network administrators diagnose captive portal authentication issues by displaying URL parameters and testing API authentication flows.

## Overview

When users connect to a WISPr-enabled wireless network, they are redirected to a captive portal for authentication. This tool simulates that portal and provides detailed logging of the authentication process to help troubleshoot connectivity issues.

## Features

- **URL Parameter Display**: Shows all parameters passed during WISPr redirection in a clear table format
- **Authentication Testing**: Tests RUCKUS One WISPr API calls with real or simulated credentials
- **Detailed Logging**: Color-coded console output showing all client-server-API communications
- **Multiple Auth Modes**: Supports both "Always Accept" and "User Credentials" authentication modes
- **Captive Portal Integration**: Properly handles post-authentication redirects for device connectivity detection

## Tested Environment

- **Hardware**: RUCKUS R1 and R770 Access Points
- **Firmware**: Version 7.1.0.510.1041
- **Authentication Mode**: "Always Accept" mode (tested and working)
- **External AAA Mode**: Not yet tested

## WISPr URL Parameters

The application expects the following parameters from the WISPr redirection:

| Parameter | Description | Required |
|-----------|-------------|----------|
| `client_mac` | Encrypted UE-MAC address | Yes |
| `uip` | Encrypted UE-IP address | Yes |
| `nbiIP` | RUCKUS One northbound interface URL | Yes |
| `mac` | AP MAC address | No |
| `ssid` | The broadcasted SSID name | No |
| `proxy` | Whether UE browser is set to Web proxy | No |
| `reason` | Reason for redirecting (Un-Auth-Captive, etc.) | No |
| `startUrl` | URL to redirect after successful login | No |
| `url` | Original URL the customer tried browsing | No |
| `vlan` | VLAN the customer is set to | No |
| `wlan` | WLAN ID of the associated WLAN | No |

## Authentication Modes

### Always Accept Mode
- Uses `RequestType: "Authorize"` API call
- Only requires UE-MAC address
- Any user credentials are automatically accepted
- Ideal for guest networks and testing

### User Credentials Mode
- Uses `RequestType: "Login"` API call  
- Requires UE-MAC, UE-IP, username, and password
- Credentials are validated against external AAA server
- **Note**: This mode has not been tested yet

## Local Development

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Quick Start
```bash
# Clone the repository
git clone <repository-url>
cd wispr-portal

# Run the setup script (creates venv and installs dependencies)
./run_local.sh
```

### Manual Setup
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate     # On Windows

# Install dependencies
pip install -r requirements.txt

# Run the server
python server.py
```

### Testing Locally
1. Open your browser to: http://localhost:8080

2. To simulate WISPr parameters, add them to the URL:
   ```
   http://localhost:8080/?client_mac=ENCb58960077a8dda598864608701fd73e1&uip=ENC93ee4456a0378b6e0c8df0ea83416f46&nbiIP=yourtenant.wispr.ruckus.cloud&mac=33:9F:37:21:88:E0&ssid=TestWiFi
   ```

3. Enter your integration key and test authentication

### Console Logging
The server provides color-coded logging for easy troubleshooting:
- 🟦 **CYAN**: Client homepage requests
- 🟦 **BLUE**: Client → Server API requests  
- 🟨 **YELLOW**: Server → RUCKUS API requests
- 🟩 **GREEN**: RUCKUS API responses
- 🟪 **PURPLE**: Server → Client responses
- 🟥 **RED**: Errors

## Google Cloud Run Deployment

### Prerequisites
- Google Cloud SDK installed and configured
- Docker installed (for local building)
- Google Cloud project with billing enabled

### Deploy Steps

1. **Set environment variables**:
   ```bash
   export PROJECT_ID=your-google-cloud-project-id
   export SERVICE_NAME=wispr-portal
   export REGION=us-central1
   ```

2. **Build and deploy**:
   ```bash
   # Build the container image
   gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME

   # Deploy to Cloud Run
   gcloud run deploy $SERVICE_NAME \
     --image gcr.io/$PROJECT_ID/$SERVICE_NAME \
     --platform managed \
     --region $REGION \
     --allow-unauthenticated \
     --port 8080
   ```

3. **Map custom domain** (optional):
   ```bash
   gcloud run domain-mappings create \
     --service $SERVICE_NAME \
     --domain your-domain.com \
     --region $REGION
   ```

### Environment Variables (Production)
For production deployments, store the integration key securely:

```bash
# Using Google Secret Manager (recommended)
gcloud run deploy $SERVICE_NAME \
  --set-env-vars INTEGRATION_KEY_SECRET=projects/$PROJECT_ID/secrets/wispr-integration-key/versions/latest
```

## Architecture

```
Browser → Flask Server → RUCKUS One API
Browser ← Flask Server ← RUCKUS One API
```

The Flask server acts as a proxy to:
- Handle CORS restrictions
- Manage SSL certificate issues
- Keep integration keys secure server-side
- Provide detailed logging

## Security Considerations

- **Integration Keys**: Never commit integration keys to version control
- **Production Deployment**: Use environment variables or secret management services
- **SSL Verification**: Enable proper SSL verification in production (currently disabled for testing)
- **Rate Limiting**: Implement rate limiting for production use
- **Input Validation**: Additional validation should be added for production environments

## File Structure

```
wispr-portal/
├── index.html              # Main web interface
├── server.py               # Flask application server
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container configuration
├── run_local.sh           # Local development script
├── .gcloudignore          # Cloud deployment exclusions
├── .gitignore             # Git exclusions
└── README.md              # This documentation
```

## API Reference

### Authentication Endpoint
**POST** `/api/authenticate`

**Request Body**:
```json
{
  "integrationKey": "your-integration-key",
  "authMode": "always-accept|credentials", 
  "nbiIP": "tenant.wispr.ruckus.cloud",
  "clientMac": "encrypted-mac-address",
  "clientIP": "encrypted-ip-address",
  "username": "user@example.com",     // Only for credentials mode
  "password": "userpassword"          // Only for credentials mode
}
```

**Response**:
```json
{
  "Vendor": "Ruckus",
  "APIVersion": "1.0", 
  "ResponseCode": 201,
  "ReplyMessage": "Login succeeded",
  "AP-MAC": "33:9F:37:21:88:E0",
  "SSID": "MyWiFi"
}
```

## Troubleshooting

### Common Issues

1. **"Unable to extract tenant ID" error**
   - Ensure `nbiIP` parameter is present and valid
   - Check that the URL format matches: `tenant.wispr.ruckus.cloud`

2. **SSL Certificate errors**
   - This is expected in the current version (SSL verification disabled for testing)
   - Enable SSL verification for production use

3. **Integration key errors**
   - Verify the integration key is correct in RUCKUS One portal settings
   - Ensure the key matches the one configured in your portal

4. **Captive portal not showing "Done"**
   - The 30-second redirect timer should trigger connectivity detection
   - Try clicking "Redirect Now" to manually trigger the redirect

### Getting Help

- Check the console logs for detailed error information
- Verify all required URL parameters are present
- Test with a known working integration key first

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is provided as-is for educational and troubleshooting purposes.