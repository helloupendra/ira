"""Connections: each person's own links to other services, through MCP servers.

A person connects a remote MCP server (a URL and their token) or one of the
local MCP servers the operator allows in ``ira.yaml`` (with their own
secrets). Each server's tools become that person's tools, with tiers from
the tools' annotations, output that is never trusted, and secrets sealed at
rest. Needs the ``connectors`` extra: ``pip install "ira-assistant[connectors]"``.
"""
