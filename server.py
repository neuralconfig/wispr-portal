from flask import Flask, request, jsonify, send_from_directory
import requests
import json
import os
import logging
from datetime import datetime

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.')

# In production, the integration key would be stored securely on the server
# For testing purposes, we'll accept it from the client

# Enable CORS for the API endpoint
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return response

# Serve the main HTML file
@app.route('/')
def index():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    client_ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Unknown')
    
    logger.info(f"\n{Colors.CYAN}{'='*80}{Colors.ENDC}")
    logger.info(f"{Colors.CYAN}[{timestamp}] CLIENT REQUEST - Homepage{Colors.ENDC}")
    logger.info(f"{Colors.CYAN}Client IP: {client_ip}{Colors.ENDC}")
    logger.info(f"{Colors.CYAN}User Agent: {user_agent}{Colors.ENDC}")
    logger.info(f"{Colors.CYAN}URL: {request.url}{Colors.ENDC}")
    
    # Log query parameters if any
    if request.args:
        logger.info(f"{Colors.CYAN}Query Parameters:{Colors.ENDC}")
        for key, value in request.args.items():
            logger.info(f"{Colors.CYAN}  - {key}: {value}{Colors.ENDC}")
    
    logger.info(f"{Colors.CYAN}{'='*80}{Colors.ENDC}\n")
    
    return send_from_directory('.', 'index.html')

# Proxy endpoint to handle authentication requests
@app.route('/api/authenticate', methods=['POST', 'OPTIONS'])
def authenticate():
    if request.method == 'OPTIONS':
        return '', 200
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    client_ip = request.remote_addr
    
    logger.info(f"\n{Colors.BLUE}{'='*80}{Colors.ENDC}")
    logger.info(f"{Colors.BLUE}{Colors.BOLD}[{timestamp}] CLIENT -> SERVER (Authentication Request){Colors.ENDC}")
    logger.info(f"{Colors.BLUE}Client IP: {client_ip}{Colors.ENDC}")
    
    try:
        data = request.get_json()
        
        # Extract parameters from client request
        integration_key = data.get('integrationKey')
        auth_mode = data.get('authMode')
        username = data.get('username')
        password = data.get('password')
        nbi_ip = data.get('nbiIP')
        client_mac = data.get('clientMac')
        client_ip = data.get('clientIP')
        
        # Log incoming request (hide sensitive data)
        logger.info(f"{Colors.BLUE}Integration Key: ***HIDDEN***{Colors.ENDC}")
        logger.info(f"{Colors.BLUE}Auth Mode: {auth_mode}{Colors.ENDC}")
        logger.info(f"{Colors.BLUE}Username: {username if auth_mode == 'credentials' else 'N/A'}{Colors.ENDC}")
        logger.info(f"{Colors.BLUE}NBI IP: {nbi_ip}{Colors.ENDC}")
        logger.info(f"{Colors.BLUE}Client MAC: {client_mac}{Colors.ENDC}")
        logger.info(f"{Colors.BLUE}Client IP: {client_ip}{Colors.ENDC}")
        logger.info(f"{Colors.BLUE}{'='*80}{Colors.ENDC}\n")
        
        # Validate required parameters
        if not integration_key:
            error_msg = 'Missing integration key'
            logger.error(f"{Colors.RED}ERROR: {error_msg}{Colors.ENDC}")
            return jsonify({'error': error_msg}), 400
            
        if not nbi_ip or not client_mac:
            error_msg = 'Missing required parameters: nbiIP or clientMac'
            logger.error(f"{Colors.RED}ERROR: {error_msg}{Colors.ENDC}")
            return jsonify({'error': error_msg}), 400
            
        if auth_mode == 'credentials' and (not username or not password):
            error_msg = 'Username and password required for credentials mode'
            logger.error(f"{Colors.RED}ERROR: {error_msg}{Colors.ENDC}")
            return jsonify({'error': error_msg}), 400
        
        # Build API URL
        api_url = nbi_ip
        if not api_url.startswith('http://') and not api_url.startswith('https://'):
            api_url = 'https://' + api_url
        if not api_url.endswith('/portalintf'):
            api_url = api_url + '/portalintf'
        
        # Build request body based on auth mode (SERVER-SIDE LOGIC)
        if auth_mode == 'always-accept':
            request_body = {
                "Vendor": "Ruckus",
                "APIVersion": "1.0",
                "RequestUserName": "api",
                "RequestPassword": integration_key,
                "RequestCategory": "UserOnlineControl",
                "RequestType": "Authorize",
                "UE-MAC": client_mac
            }
        else:  # credentials mode
            request_body = {
                "Vendor": "Ruckus",
                "APIVersion": "1.0",
                "RequestUserName": "api", 
                "RequestPassword": integration_key,
                "RequestCategory": "UserOnlineControl",
                "RequestType": "Login",
                "UE-MAC": client_mac,
                "UE-IP": client_ip,
                "UE-Username": username,
                "UE-Password": password
            }
        
        # Log outgoing API request
        logger.info(f"\n{Colors.YELLOW}{'='*80}{Colors.ENDC}")
        logger.info(f"{Colors.YELLOW}{Colors.BOLD}[{timestamp}] SERVER -> RUCKUS API{Colors.ENDC}")
        logger.info(f"{Colors.YELLOW}API Endpoint: {api_url}{Colors.ENDC}")
        logger.info(f"{Colors.YELLOW}Method: POST{Colors.ENDC}")
        logger.info(f"{Colors.YELLOW}Headers: Content-Type: application/json{Colors.ENDC}")
        
        # Log request body (hide integration key)
        log_request_body = request_body.copy()
        log_request_body['RequestPassword'] = '***HIDDEN***'
        if 'UE-Password' in log_request_body:
            log_request_body['UE-Password'] = '***HIDDEN***'
        logger.info(f"{Colors.YELLOW}Request Body:{Colors.ENDC}")
        logger.info(f"{Colors.YELLOW}{json.dumps(log_request_body, indent=2)}{Colors.ENDC}")
        logger.info(f"{Colors.YELLOW}{'='*80}{Colors.ENDC}\n")
        
        # Make the actual API call to RUCKUS One
        # Note: In production, you should verify SSL certificates
        response = requests.post(
            api_url,
            json=request_body,
            headers={'Content-Type': 'application/json'},
            verify=False  # In production, set verify=True and handle certificates properly
        )
        
        # Log API response
        response_data = response.json()
        logger.info(f"\n{Colors.GREEN}{'='*80}{Colors.ENDC}")
        logger.info(f"{Colors.GREEN}{Colors.BOLD}[{timestamp}] RUCKUS API -> SERVER (Response){Colors.ENDC}")
        logger.info(f"{Colors.GREEN}Status Code: {response.status_code}{Colors.ENDC}")
        logger.info(f"{Colors.GREEN}Response Body:{Colors.ENDC}")
        logger.info(f"{Colors.GREEN}{json.dumps(response_data, indent=2)}{Colors.ENDC}")
        
        # Log response interpretation
        if response_data.get('ResponseCode') == 201:
            logger.info(f"{Colors.GREEN}{Colors.BOLD}✓ LOGIN SUCCEEDED{Colors.ENDC}")
        elif response_data.get('ResponseCode') == 101:
            logger.info(f"{Colors.GREEN}{Colors.BOLD}✓ CLIENT ALREADY AUTHORIZED{Colors.ENDC}")
        elif response_data.get('ResponseCode') == 301:
            logger.info(f"{Colors.RED}{Colors.BOLD}✗ LOGIN FAILED{Colors.ENDC}")
        
        logger.info(f"{Colors.GREEN}{'='*80}{Colors.ENDC}\n")
        
        # Log server response to client
        logger.info(f"\n{Colors.HEADER}{'='*80}{Colors.ENDC}")
        logger.info(f"{Colors.HEADER}{Colors.BOLD}[{timestamp}] SERVER -> CLIENT (Response){Colors.ENDC}")
        logger.info(f"{Colors.HEADER}Status Code: {response.status_code}{Colors.ENDC}")
        logger.info(f"{Colors.HEADER}Response sent to client{Colors.ENDC}")
        logger.info(f"{Colors.HEADER}{'='*80}{Colors.ENDC}\n")
        
        # Return both the RUCKUS API response and the request that was sent
        # This helps with troubleshooting by showing exactly what was sent/received
        result = {
            "ruckusApiRequest": log_request_body,  # Already has passwords hidden
            "ruckusApiResponse": response_data
        }
        return jsonify(result), response.status_code
        
    except requests.exceptions.RequestException as e:
        error_msg = f'Failed to connect to RUCKUS One API: {str(e)}'
        logger.error(f"\n{Colors.RED}{Colors.BOLD}API CONNECTION ERROR:{Colors.ENDC}")
        logger.error(f"{Colors.RED}{error_msg}{Colors.ENDC}\n")
        return jsonify({'error': error_msg}), 500
    except Exception as e:
        error_msg = f'Server error: {str(e)}'
        logger.error(f"\n{Colors.RED}{Colors.BOLD}SERVER ERROR:{Colors.ENDC}")
        logger.error(f"{Colors.RED}{error_msg}{Colors.ENDC}\n")
        return jsonify({'error': error_msg}), 500

if __name__ == '__main__':
    # For Google Cloud Run, we need to use the PORT environment variable
    port = int(os.environ.get('PORT', 8080))
    
    # Startup message
    logger.info(f"\n{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.ENDC}")
    logger.info(f"{Colors.BOLD}{Colors.GREEN}WISPr Portal Troubleshooting Tool - Server Starting{Colors.ENDC}")
    logger.info(f"{Colors.BOLD}{Colors.GREEN}{'='*80}{Colors.ENDC}")
    logger.info(f"{Colors.GREEN}Server running on: http://0.0.0.0:{port}{Colors.ENDC}")
    logger.info(f"{Colors.GREEN}Access locally at: http://localhost:{port}{Colors.ENDC}")
    logger.info(f"{Colors.GREEN}Press Ctrl+C to stop the server{Colors.ENDC}")
    logger.info(f"{Colors.GREEN}{'='*80}{Colors.ENDC}\n")
    
    logger.info(f"{Colors.YELLOW}Color Legend:{Colors.ENDC}")
    logger.info(f"{Colors.CYAN}■ CYAN: Client homepage requests{Colors.ENDC}")
    logger.info(f"{Colors.BLUE}■ BLUE: Client -> Server API requests{Colors.ENDC}")
    logger.info(f"{Colors.YELLOW}■ YELLOW: Server -> RUCKUS API requests{Colors.ENDC}")
    logger.info(f"{Colors.GREEN}■ GREEN: RUCKUS API responses{Colors.ENDC}")
    logger.info(f"{Colors.HEADER}■ PURPLE: Server -> Client responses{Colors.ENDC}")
    logger.info(f"{Colors.RED}■ RED: Errors{Colors.ENDC}")
    logger.info(f"\n")
    
    # Disable Flask's default logging to avoid duplication
    import logging as flask_logging
    flask_logging.getLogger('werkzeug').setLevel(flask_logging.WARNING)
    
    app.run(host='0.0.0.0', port=port, debug=False)