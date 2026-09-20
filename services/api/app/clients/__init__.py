"""Clients for the internal services this API fronts.

Every base URL comes from settings and none is ever taken from a request. The rule is not
defensive style — a URL accepted from a caller would turn this service, which sits on the internal
network and holds a service credential, into an SSRF proxy for everything behind the firewall.
"""
