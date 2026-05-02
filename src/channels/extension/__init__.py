"""
Extension Channel — Channel 4 (replaces deprecated Browser Channel).

The user's own Chrome runs an extension that observes Upwork search pages
and POSTs new job tiles to this backend. There is no automation driver
attached to the browser — Cloudflare and Upwork see only the user's
real, manually-authenticated browsing session.
"""
from src.channels.extension.channel import ExtensionChannel

__all__ = ["ExtensionChannel"]
