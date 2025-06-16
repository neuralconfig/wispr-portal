**USER GUIDE** 

![](_page_0_Picture_1.jpeg)

# RUCKUS One Hotspot WISPr **API Reference**

© 2023 CommScope, Inc. All rights reserved.

No part of this content may be reproduced in any form or by any means or used to make any derivative work (such as translation, transformation, or adaptation) without written permission from CommScope, Inc. and/or its affiliates ("CommScope"). CommScope reserves the right to revise or change this content from time to time without obligation on the part of CommScope to provide notification of such revision or change.

# **Export Restrictions**

These products and associated technical data (in print or electronic form) may be subject to export control laws of the United States of America. It is your responsibility to determine the applicable regulations and to comply with them. The following notice is applicable for all products or technology subject to export control:

These items are controlled by the U.S. Government and authorized for export only to the country of ultimate destination for use by the ultimate consignee or end-user(s) herein identified. They may not be resold, transferred, or otherwise disposed of, to any other country or to any person other than the authorized ultimate consignee or end-user(s), either in their original form or after being incorporated into other items, without first obtaining approval from the U.S. government or as otherwise authorized by U.S. law and regulations.

### **Disclaimer**

THIS CONTENT AND ASSOCIATED PRODUCTS OR SERVICES ("MATERIALS"). ARE PROVIDED "AS IS" AND WITHOUT WARRANTIES OF ANY KIND. WHETHER EXPRESS OR IMPLIED. TO THE FULLEST EXTENT PERMISSIBLE PURSUANT TO APPLICABLE LAW, COMMSCOPE DISCLAIMS ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE, TITLE, NON-INFRINGEMENT, FREEDOM FROM COMPUTER VIRUS, AND WARRANTIES ARISING FROM COURSE OF DEALING OR COURSE OF PERFORMANCE. CommScope does not represent or warrant that the functions described or contained in the Materials will be uninterrupted or error-free, that defects will be corrected, or are free of viruses or other harmful components. CommScope does not make any warranties or representations regarding the use of the Materials in terms of their completeness, correctness, accuracy, adequacy, usefulness, timeliness, reliability or otherwise. As a condition of your use of the Materials, you warrant to CommScope that you will not make use thereof for any purpose that is unlawful or prohibited by their associated terms of use.

### **Limitation of Liability**

IN NO EVENT SHALL COMMSCOPE, COMMSCOPE AFFILIATES, OR THEIR OFFICERS, DIRECTORS, EMPLOYEES, AGENTS, SUPPLIERS, LICENSORS AND THIRD PARTY PARTNERS, BE LIABLE FOR ANY DIRECT, INDIRECT, SPECIAL, PUNITIVE, INCIDENTAL, EXEMPLARY OR CONSEQUENTIAL DAMAGES, OR ANY DAMAGES WHATSOEVER, EVEN IF COMMSCOPE HAS BEEN PREVIOUSLY ADVISED OF THE POSSIBILITY OF SUCH DAMAGES, WHETHER IN AN ACTION UNDER CONTRACT, TORT, OR ANY OTHER THEORY ARISING FROM YOUR ACCESS TO, OR USE OF, THE MATERIALS. Because some jurisdictions do not allow limitations on how long an implied warranty lasts, or the exclusion or limitation of liability for consequential or incidental damages, some of the above limitations may not apply to you.

### **Trademarks**

CommScope and the CommScope logo are registered trademarks of CommScope and/or its affiliates in the U.S. and other countries. For additional trademark information see https://www.commscope.com/trademarks. All product names, trademarks, and registered trademarks are the property of their respective owners.

### **Patent Marking Notice**

For applicable patents, see www.cs-pat.com.

# **Contents**

| Contact Information, Resources, and Conventions |
|-------------------------------------------------|
| Contacting RUCKUS Customer Services and Support |
| What Support Do I Need?                         |
| Open a Case                                     |
| Self-Service Resources                          |
| Document Feedback                               |
| RUCKUS Product Documentation Resources          |
| Online Training Resources                       |
| Document Conventions                            |
| Notes, Cautions, and Safety Warnings            |
| Command Syntax Conventions                      |
| About This Guide                                |
| Document Overview                               |
| Terminology                                     |
| RUCKUS One Northbound Interface                 |
| Northbound Interface Overview                   |
| Request Format                                  |
| JSON Commands: User Online Control              |
| Request and Re-Authentication Synchronous Login |
| JSON Responses Definitions                      |
| JSON Response Examples                          |
| Captive Portal Attributes                       |
| Redirection Attributes                          |
| Certificate Warning                             |

 $\overline{4}$ 

# **Contact Information, Resources, and Conventions**

| • Contacting RUCKUS Customer Services and Support                            |  |
|------------------------------------------------------------------------------|--|
| ● Document Feedback………………………………………………………………………………………………                      |  |
| ● RUCKUS Product Documentation Resources……………………………………………………………………………………………… |  |
| • Online Training Resources                                                  |  |
| ● Document Conventions………………………………………………………………………………………………                   |  |
| • Command Syntax Conventions                                                 |  |

## **Contacting RUCKUS Customer Services and Support**

The Customer Services and Support (CSS) organization is available to provide assistance to customers with active warranties on their RUCKUS products, and customers and partners with active support contracts.

For product support information and details on contacting the Support Team, go directly to the RUCKUS Support Portal using https:// support.ruckuswireless.com, or go to https://www.ruckusnetworks.com and select Support.

## **What Support Do I Need?**

Technical issues are usually described in terms of priority (or severity). To determine if you need to call and open a case or access the self-service resources, use the following criteria:

- Priority 1 (P1)-Critical. Network or service is down and business is impacted. No known workaround. Go to the Open a Case section.  $\bullet$
- Priority 2 (P2)—High. Network or service is impacted, but not down. Business impact may be high. Workaround may be available. Go to  $\bullet$ the Open a Case section.
- Priority 3 (P3)-Medium. Network or service is moderately impacted, but most business remains functional. Go to the Self-Service Resources section.
- Priority 4 (P4)-Low. Requests for information, product documentation, or product enhancements. Go to the Self-Service Resources section.

## **Open a Case**

When your entire network is down (P1), or severely impacted (P2), call the appropriate telephone number listed below to get help:

- Continental United States: 1-855-782-5871
- Canada: 1-855-782-5871
- Europe, Middle East, Africa, Central and South America, and Asia Pacific, toll-free numbers are available at https:// support.ruckuswireless.com/contact-us and Live Chat is also available.
- Worldwide toll number for our support organization. Phone charges will apply: +1-650-265-0903

We suggest that you keep a physical note of the appropriate support number in case you have an entire network outage.

## **Self-Service Resources**

The RUCKUS Support Portal at https://support.ruckuswireless.com offers a number of tools to help you to research and resolve problems with your RUCKUS products, including:

- Technical Documentation-https://support.ruckuswireless.com/documents  $\bullet$
- Community Forums-https://community.ruckuswireless.com
- Knowledge Base Articles-https://support.ruckuswireless.com/answers  $\bullet$
- Software Downloads and Release Notes-https://support.ruckuswireless.com/#products\_grid
- Security Bulletins-https://support.ruckuswireless.com/security  $\blacktriangle$

Using these resources will help you to resolve some issues, and will provide TAC with additional data from your troubleshooting analysis if you still require assistance through a support case or RMA. If you still require help, open and manage your case at https://support.ruckuswireless.com/ case\_management.

# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

RUCKUS is interested in improving its documentation and welcomes your comments and suggestions.

You can email your comments to RUCKUS at #Ruckus-Docs@commscope.com.

When contacting us, include the following information:

- Document title and release number  $\bullet$
- Document part number (on the cover page)  $\bullet$
- Page number (if appropriate)

For example:

- RUCKUS SmartZone Upgrade Guide, Release 5.0
- Part number: 800-71850-001 Rev A
- Page 7

# **RUCKUS Product Documentation Resources**

Visit the RUCKUS website to locate related documentation for your product and additional RUCKUS resources.

Release Notes and other user documentation are available at https://support.ruckuswireless.com/documents. You can locate the documentation by product or perform a text search. Access to Release Notes requires an active support contract and a RUCKUS Support Portal user account. Other technical documentation content is available without logging in to the RUCKUS Support Portal.

White papers, data sheets, and other product documentation are available at https://www.ruckusnetworks.com.

# **Online Training Resources**

To access a variety of online RUCKUS training modules, including free introductory courses to wireless networking essentials, site surveys, and products, visit the RUCKUS Training Portal at https://commscopeuniversity.myabsorb.com/. The registration is a two-step process described in this video. You create a CommScope account and then register for, and request access for, CommScope University.

## **Document Conventions**

The following table lists the text conventions that are used throughout this guide.

### **TABLE 1 Text Conventions**

| Convention | Description                                                                                                            | Example                                                            |
|------------|------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------|
| monospace  | Identifies command syntax examples                                                                                     | device (config)# interface ethernet 1/1/6                          |
| bold       | User interface (UI) components such<br>as screen or page names, keyboard<br>keys, software buttons, and field<br>names | On the Start menu, click All Programs.                             |
| italics    | Publication titles                                                                                                     | Refer to the RUCKUS Small Cell Release Notes for more information. |

## **Notes, Cautions, and Safety Warnings**

Notes, cautions, and warning statements may be used in this document. They are listed in the order of increasing severity of potential hazards.

### **NOTE**

A NOTE provides a tip, guidance, or advice, emphasizes important information, or provides a reference to related information.

### **ATTENTION**

An ATTENTION statement indicates some information that you must read before continuing with the current action or task.

![](_page_6_Picture_11.jpeg)

### **CAUTION**

A CAUTION statement alerts you to situations that can be potentially hazardous to you or cause damage to hardware, firmware, software, or data.

![](_page_6_Picture_14.jpeg)

#### **DANGER**

A DANGER statement indicates conditions or situations that can be potentially lethal or extremely hazardous to you. Safety labels are also attached directly to products to warn of these conditions or situations.

## **Command Syntax Conventions**

Bold and italic text identify command syntax components. Delimiters and operators define groupings of parameters and their logical relationships.

| Convention       | <b>Description</b>                                                                                                                                                         |
|------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| <b>bold</b> text | Identifies command names, keywords, and command options.                                                                                                                   |
| italic text      | Identifies a variable.                                                                                                                                                     |
| $\Box$           | Syntax components displayed within square brackets are optional.                                                                                                           |
|                  | Default responses to system prompts are enclosed in square brackets.                                                                                                       |
| ${x   y   z}$    | A choice of required parameters is enclosed in curly brackets separated by vertical bars. You must select one of the options.                                              |
| x∣y              | A vertical bar separates mutually exclusive elements.                                                                                                                      |
| $\langle$ >      | Nonprinting characters, for example, passwords, are enclosed in angle brackets.                                                                                            |
| $\cdots$         | Repeat the previous element, for example, member [member].                                                                                                                 |
|                  | Indicates a "soft" line break in command examples. If a backslash separates two lines of a command input, enter the entire command at<br>the prompt without the backslash. |

# **About This Guide**

Document Overview....................................  $\bullet$ 

## **Document Overview**

This document describes RUCKUS One RESTful-like/JSON interfaces for external web portal servers.

This guide is written for service operators and system administrators who are responsible for managing, configuring, and troubleshooting RUCKUS Network's devices. Consequently, it assumes a basic working knowledge of local area networks, wireless networking, and wireless devices.

#### **NOTE**

If release notes are shipped with this product and the information in it differs from the information in this guide, follow the instructions in the release notes.

Most user guidesand release notesare available in Adobe AcrobatReader Portable DocumentFormat (PDF) or HTML on the RUCKUS Wireless Support Web site at https://support.ruckuswireless.com/contact-us.

### **TABLE 2 Revision History**

| <b>Part Number</b>  | <b>Revision Date</b> | <b>Description</b> |
|---------------------|----------------------|--------------------|
| 800-73417-001 Rev A | 30 June 2023         | Initial release    |
| 800-73417-001 Rev B | 15 August 2023       | Minor updates      |

## **Terminology**

The table lists the terms used in this guide.

| Terminology | Description                   |
|-------------|-------------------------------|
| AP          | Access Point                  |
| CP          | Captive Portal                |
| NBI         | Northbound Interface          |
| SCG         | Smart Cell Gateway            |
| SSL         | Secure Socket Layer           |
| TCP         | Transmission Control Protocol |
| UDI         | User Defined Interface        |
| UE          | User Equipment                |
| UE-IP       | User Equipment - IP Address   |
| UE-MAC      | User Equipment - MAC Address  |

# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

| Northbound Interface Overview      | Page Number |
|------------------------------------|-------------|
| Request Format                     | 1           |
| JSON Commands: User Online Control | 1           |
| JSON Responses Definitions         | 1           |

# **Northbound Interface Overview**

RUCKUS One provides a third-party captive portal integration. RUCKUS One administrator sets up network options and chooses a captive portal provider.

A guest user joining the network sees a guest portal landing page hosted by the third-party service. Marketing messages, customized logos, and terms and conditions set up in the external web portal are displayed to the user. The user submitsprox login credentials that are 'proxied' to the third-party service for authentication and authorization. The login flow and message exchanges between various components are described in this guide. The JSON interface defined in this reference guide provides a standard way for an external web portal server to communicate with RUCKUS One for this type of usage.

This reference guide describes RUCKUS One RESTful-like/JSON interfaces for external web portal servers.

The following hotspot components are part of the hotspot portal:

- RUCKUS One northbound interface (NBI): Receives NBI requests forwarded from the access point and enriches the URL. RUCKUS One NBI  $\bullet$ is also responsible for redirecting the incoming URL request and passing user login credentials to the external AAA server.
- External subscriber portal: A web service. User sends login credentials (username and password) to this portal through the NBI. The  $\bullet$ external subscriber portal can reach the NBI through the API.
- External AAA server: Responsible for authenticating the UE through the UE's login credentials.

### FIGURE 1 RUCKUS One Integration with Third-Party Captive Portal

![](_page_11_Figure_2.jpeg)

## **Request Format**

As defined in JSON commands, each request issued from an external web portal server must be in the JSON format.

RUCKUS One NBI address is an important attribute that is learned during the message exchange when the third-party captive portal receives HTTP request from the user device. All messages destined to the NBI must use this IP and port 443.

### **NOTE**

### **HTTP Request**

#### For North America:

```
https://<tenantid>.wispr.ruckus.cloud:443/portalintf
```
#### For FU:

https://<tenantid>.wispr.eu.ruckus.cloud:443/portalintf

#### For Asia:

https://<tenantid>.wispr.asia.ruckus.cloud:443/portalintf

The above-mentioned URLs are examples and the real value should be taken from nbiIP/SIP URL parameter.

The following table lists the ports that must be opened on the network firewall to ensure that the external portal and NBI can communicate with each other successfully.

### **TABLE 3 Port Details**

| Port Number | Layer 7 Protocol | Source | Destination | Configurable form Web Interface | Purpose                                 |
|-------------|------------------|--------|-------------|---------------------------------|-----------------------------------------|
| 443         | HTTPS            | Any    | Cloud       | No                              | Northbound Portal Interface for Hotspot |

## **JSON Commands: User Online Control**

The NBI supports Login (sync) JSON commands.

These commands are used for user authentication, user status query, and verifying that the enrichment information has the same content. For each command (JSON POST), the UE-MAC is mandatory.

### **NOTE**

Although the NBI expects to receive an encrypted UE-MAC address (for example, ENC12bc24c4777703327f2e0aabbf6b9f9e) when the request category is User Online Control, unencrypted UE-MAC are also acceptable. However, the UE-MAC must exactly match the client\_mac in the query string that is sent to the external subscriber portal.

## **Request and Re-Authentication Synchronous Login**

RUCKUS One provides a synchronous login blocking command (RequestType=Login).

### **NOTE**

The MAC Auth bypass option helps user skipping reloging in.

During synchronous login, the external Web portal must wait for the authentication process to complete, which is usually processed by the authentication server. This could result in a delayed response if the controller is unable to get a response from the authentication server.

The following table lists the controller responses to the synchronous login command.

| Response Type   | Possible Responses                                                                                                                                                                                                                                                                                                                                                                                     |
|-----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Normal response | 101, Client authorized: Response if the user is already authorized.<br>201, Login succeeded: Response if the login is accepted.                                                                                                                                                                                                                                                                        |
| Service error   | 300, Not found: Response if the lookup fails with given UE-MAC address or UE-IP address.<br>301, Login failed: It will be replaced if the authentication reply message is returned.<br>400, Internal server error: Response when a controller internal error occurs.<br>401, Authentication server error: Response when an authentication connection error occurs or the connection request times out. |
| General error   | 302, Bad request: Response if the JSON request is not well-formed.<br>303, Version not supported: Response if there is a version mismatch.<br>304, Command not supported: Response if the request type is not supported.<br>305, Category not supported: Response if the request category not supported.<br>306, Wrong request password: Response if the request password is mismatched.               |

### **NOTE**

If an authentication process has a result (not pending), RUCKUS Cloud responds to it only once. For example, if RUCKUS Cloud replies 301, login failed, to the web portal server, and the web portal server sends the same query, the response will be 100, Unauthorized. If the controller replies 201, login was successful, and the web portal server queries again, the response will be 101, Authorized.

# **JSON Responses Definitions**

The following table lists the definitions of JSON responses from the NBI.

### **NOTE**

The following abbreviations are used in the table columns:

- UA: User Authenticate (Login)  $\bullet$
- GC: Get Config (Decrypt)  $\bullet$

| Category      | Code | Definition                  | UA | SQ | TU | EI | GC |
|---------------|------|-----------------------------|----|----|----|----|----|
| Informational | 100  | Client unauthorized         |    | x  | x  |    |    |
| Informational | 101  | Client authorized           | x  | x  |    |    |    |
| Informational | 102  | Enrichment Info             |    |    |    | x  |    |
| Success       | 200  | OK                          |    |    | x  |    | x  |
| Success       | 201  | Login succeeded             |    | x  |    |    |    |
| Success       | 202  | Authentication pending      | x  | x  |    |    |    |
| Client Error  | 300  | Not found                   | x  | x  | x  | x  |    |
| Client Error  | 301  | Login failed                | x  | x  |    |    |    |
| Client Error  | 302  | Bad request                 | x  | x  | x  | x  |    |
| Client Error  | 303  | Version not supported       | x  | x  | x  | x  |    |
| Client Error  | 304  | Command not supported       | x  | x  | x  | x  |    |
| Client Error  | 305  | Category not supported      | x  | x  | x  | x  |    |
| Client Error  | 306  | Wrong request password      | x  | x  | x  | x  |    |
| Server Error  | 400  | Internal server error       | x  | x  | x  | x  |    |
| Server Error  | 401  | Authentication server error | x  | x  |    |    |    |

## **JSON Response Examples**

There are only two API calls used by the captive portal for Ruckus Cloud. The IP address for the call needs to be extracted from the URL parameters received by the external portal. The tenant ID where the portal is configured is prefixed to the address as in: https:// ebb9ea66951549548de56a621aceb3a5.wispr.ruckus.cloud:443/portalintf. Therefore, the general format for the call is https:// {{tenantID}}.wispr.ruckus.cloud:443/portalintf.

This section provides the following examples of JSON responses defined in the JSON Response Definitions.

UserOnlineControl/Login request

The following example shows the UserOnlineControl/Login marked in Figure 1 as Login request/response.

```
POST https://<tenantid>.wispr.ruckus.cloud:443/portalintf
\{"Vendor": "Ruckus",
    "APIVersion": "1.0",
    "RequestUserName": "api",
    "RequestPassword": "sharedsecret",
    "RequestCategory": "UserOnlineControl",
    "RequestType": "Login",
    "UE-IP": "ENC93ee4456a0378b6e0c8df0ea83416f46",<br>"UE-MAC": "ENCb58960077a8dda598864608701fd73e1aaefa125bbcc857a",
    "UE-Username": "johndoe@myvendor.com",
    "UE-Password": "e329a4b6e264b200850e461a535469e8"
\}response example:
   "APIVersion": "1.0",
"Vendor": "Ruckus",
"ResponseCode": 201,<br>"ReplyMessage": "Login succeeded",
"AP-MAC": "33:9F:37:21:88:E0",
"SSID": "MyHomeWifi",
"GuestUser": "0",
"UE-IP": "ENCb3579628807a64f0e008793bd3623389",
"UE-Proxy": 0,
"UE-Username": "bc5faa30d6e24389b7777d0d6503c8fa-facebook@2702337dd673",
"UE-MAC": "ENC2e50f302e3cc0f79756121786ce8955e7a8dbb9754ddeba0",
"SmartClientMode": "none",
"SmartClientInfo": ""
\overline{\phantom{a}}
```
# **Captive Portal Attributes**

#### Redirection Attributes............................ . . . . . . . . . . . . . . . . . . . .  $\bullet$ . . . . . . . . . . . . . . . . . . . .

The UE-IP address and UE-MAC address parameters are decrypted at the beginning of each user online control request.

This is because the captive portal (CP) encrypts the IP address and MAC address parameters in each redirection to the subscriber portal. The controller decrypts the UE-IP address and UE-MAC address before returning the response, by using the Encrypt and Decrypt API.

RUCKUS One has an internal service decrypts MAC addresses and IP addresses. In RUCKUS One that is invoked with POST https://{{nbiIP}}:443/ portalintf, RequestCategory" = "GetConfig" and "RequestType" = "Decrypt" and "Data" containing the data to be decrypted.

When a client gets redirected by the AP or RUCKUS One to the external portal, the external portal receives the client MAC address and client IP address in the encrypted format. If the external portal needs to see the unencrypted addresses, it can use the API call above. Otherwise, when the external portal needs to send an authentication request to RUCKUS One(a login call), it sends the client MAC address and IP address in the encrypted format.

### **NOTE**

If the external portal is in HTTPS, Apple iOS Captive Network Assistant (CNA) will not work. It works only for HTTP redirect.

## **Redirection Attributes**

The following table lists the parameters provided by the controller's captive portal redirection.

| <b>Attributes</b> | <b>Description</b>                                                                                                                   |
|-------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| client_mac        | Encrypted UE-MAC address.                                                                                                            |
|                   | <b>NOTE</b><br>The format of the MAC address is defined at the Hotspot (WISPr)<br>Portal configuration.                              |
| mac               | AP MAC address.                                                                                                                      |
| proxy             | The UE browser if it is set to the Web proxy.                                                                                        |
| reason            | Reason for redirecting the WLAN. The value could be either of the following:                                                         |
|                   | Un-Auth-Captive: Regular unauthenticated UE redirected to Login<br>$\bullet$<br>Portal.                                              |
|                   | Un-Auth-SSL-Captive: In case of HTTPS, Captive Portal is performing a<br>"double redirect". Adding this value to identify this flow. |
| nbilP             | RUCKUS One subscriber management external IP.                                                                                        |
| ssid              | The broadcasted SSID name.                                                                                                           |
| startUrl          | The URL as per the hotspot configuration, which is to be redirected after<br>successful login.                                       |
| uip               | Encrypted UE-IP address.                                                                                                             |
| url               | Original URL which the customer tries browsing.                                                                                      |
| vlan              | VLAN which the customer is set to.                                                                                                   |
| wlan              | WLAN ID of the UE's associated the WLAN.                                                                                             |

# **Certificate Warning**

A certificate warning appear when end users are redirecting with an HTTPS request.

If end user enters an HTTPS URL through the browser manually, one certificate warning message will be expected to be seen in the UE browser.

The RUCKUS One portal uses a certificate of ruckuswireless.com. RUCKUS One needs to complete the SSL handshake before sending a 302 redirect response to the UE. Because the FQDN (common name) in the certificate is impossible to match to the URL that the UE tries to visit, the browser will display a certificate warning.

To avoid certificate warning messages, major operating systems already have built-in mechanisms to detect captive networks and sending HTTP requests (not HTTPS), so that users can be redirected to a portal page automatically without any certificate error.

- Apple iOS Captive Network Assistant (CNA) sends HTTP requests to some static URLs to detect the captive portal.
- Android devices detectes these issues by sending HTTP requests to http://clients3.google.com/generate\_204.
- Windows 10 sends HTTP requests to http://www.msftncsi.com/ncsi.txt to detect the captive portal.

### **NOTE**

URLs may vary based on different software releases.

In any case, user devices display a message and redirect users to the portal page with HTTP requests instead of HTTPS requests. No certificate warning will be shown if the UE is redirected automatically by the operating system.

![](_page_19_Picture_0.jpeg)

© 2023 CommScope, Inc. All rights reserved.<br>350 West Java Dr., Sunnyvale, CA 94089 USA<br>https://www.commscope.com