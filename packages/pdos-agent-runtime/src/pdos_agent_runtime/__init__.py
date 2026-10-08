"""Shared execution machinery. No business imports, identities or policy grants."""

# Keep package import safe inside Temporal's deterministic workflow sandbox.
# Activities import graph/checkpoint/provider dependencies in their own modules.
