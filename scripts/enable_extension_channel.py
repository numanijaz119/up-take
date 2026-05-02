"""One-off seed script: enable extension_channel and disable browser_channel."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from src.database import AsyncSessionLocal
from src.models.channel import ChannelConfig


async def main():
    async with AsyncSessionLocal() as db:
        # Disable browser_channel if it exists
        result = await db.execute(
            select(ChannelConfig).where(ChannelConfig.channel_id == "browser_channel")
        )
        browser = result.scalar_one_or_none()
        if browser and browser.is_enabled:
            browser.is_enabled = False
            print("browser_channel disabled")

        # Enable extension_channel
        result = await db.execute(
            select(ChannelConfig).where(ChannelConfig.channel_id == "extension_channel")
        )
        existing = result.scalar_one_or_none()
        if existing:
            if not existing.is_enabled:
                existing.is_enabled = True
                print("extension_channel re-enabled")
            else:
                print("extension_channel already enabled")
        else:
            db.add(ChannelConfig(
                channel_id="extension_channel",
                display_name="Browser Extension",
                description=(
                    "User-controlled Chrome extension that observes Upwork search "
                    "pages in the user's own logged-in session."
                ),
                is_enabled=True,
            ))
            print("extension_channel created and enabled")

        await db.commit()


asyncio.run(main())
