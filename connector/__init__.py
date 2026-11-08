"""wispr-connector: the lab-side half of the hosted portal.

It dials out to the Cloudflare Worker over WSS, receives the NBI configuration from the cloud,
and runs only two operations against the SmartZone NBI: ``probe`` (Status for a fixed dummy UE)
and ``accept`` (the click-through authorization, via wispr.flow.Authorizer). A local policy
ceiling (environment on the host) limits what the cloud can ask for. See connector/PROTOCOL.md.
"""

VERSION = "0.1.0"
PROTOCOL = 1
