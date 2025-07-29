#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""RTVI messaging utilities for real estate bot."""

import asyncio
import time
import uuid
from typing import Dict, Any, Optional
from loguru import logger

from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from src.config.settings import RTVI_MESSAGE_TIMEOUT, RTVI_ERROR_TIMEOUT


async def send_property_search_results(
    rtvi_instance: Optional[Any],
    search_data: Dict[str, Any],
    text_query: str,
) -> None:
    """Send property search results via RTVI message.
    
    Args:
        rtvi_instance: The RTVI processor instance
        search_data: Search results data
        text_query: Original search query
    """
    try:
        if not rtvi_instance:
            logger.warning("⚠️ RTVI processor not available")
            return

        if search_data.get("search_completed") and search_data.get("properties"):
            # Create structured message for successful search
            rtvi_message_data = {
                "type": "property_search_results",
                "timestamp": time.time(),
                "search_id": str(uuid.uuid4()),
                "query": text_query,
                "summary": {
                    "total_found": search_data.get("results_found", 0),
                    "showing": len(search_data["properties"]),
                    "execution_time": search_data.get("execution_time_seconds", 0),
                    "search_type": search_data.get("search_type", "hybrid"),
                },
                "filters_applied": search_data.get("filters_applied", {}),
                "properties": [
                    {
                        "id": prop["property_id"],
                        "url": prop["url"],
                        "images": {
                            "primary": prop["primary_image"],
                            "all": prop["image_urls"],
                        },
                        "details": {
                            "address": prop["address"],
                            "price": prop["price"],
                            "currency": prop["currency"],
                            "bedrooms": prop["bedrooms"],
                            "bathrooms": prop["bathrooms"],
                            "type": prop["property_type"],
                            "description": prop["description"],
                        },
                        "metadata": {
                            "search_score": prop["search_score"],
                            "mls_genuine": prop["mls_genuine"],
                            "status": prop["status"],
                        },
                    }
                    for prop in search_data["properties"]
                ],
            }

            # Send RTVI message with timeout
            server_message_frame = RTVIServerMessageFrame(data=rtvi_message_data)

            try:
                await asyncio.wait_for(
                    rtvi_instance.push_frame(server_message_frame), 
                    timeout=RTVI_MESSAGE_TIMEOUT
                )
                logger.info(
                    f"✅ RTVI message sent - {len(search_data['properties'])} properties"
                )
            except asyncio.TimeoutError:
                logger.warning("⚠️ RTVI message send timed out")

        else:
            # Send error message for failed search
            await send_property_search_error(rtvi_instance, search_data, text_query)

    except Exception as e:
        logger.error(f"❌ Error sending RTVI search results: {e}")


async def send_property_search_error(
    rtvi_instance: Optional[Any],
    search_data: Dict[str, Any],
    text_query: str,
) -> None:
    """Send property search error via RTVI message.
    
    Args:
        rtvi_instance: The RTVI processor instance
        search_data: Search error data
        text_query: Original search query
    """
    try:
        if not rtvi_instance:
            logger.warning("⚠️ RTVI processor not available for error message")
            return

        rtvi_message_data = {
            "type": "property_search_error",
            "timestamp": time.time(),
            "search_id": str(uuid.uuid4()),
            "query": text_query,
            "error": search_data.get("error", "No properties found"),
            "failure_point": search_data.get("failure_point", "unknown"),
        }

        server_message_frame = RTVIServerMessageFrame(data=rtvi_message_data)
        
        try:
            await asyncio.wait_for(
                rtvi_instance.push_frame(server_message_frame), 
                timeout=RTVI_ERROR_TIMEOUT
            )
            logger.info("✅ RTVI error message sent")
        except asyncio.TimeoutError:
            logger.warning("⚠️ RTVI error message send timed out")

    except Exception as e:
        logger.error(f"❌ Error sending RTVI error message: {e}")


def schedule_rtvi_message(
    event_loop: Optional[asyncio.AbstractEventLoop],
    rtvi_instance: Optional[Any],
    search_data: Dict[str, Any],
    text_query: str,
) -> None:
    """Schedule RTVI message to be sent in the event loop.
    
    Args:
        event_loop: The asyncio event loop
        rtvi_instance: The RTVI processor instance
        search_data: Search results or error data
        text_query: Original search query
    """
    if not event_loop or not rtvi_instance:
        logger.warning("⚠️ Event loop or RTVI instance not available")
        return

    try:
        future = asyncio.run_coroutine_threadsafe(
            send_property_search_results(rtvi_instance, search_data, text_query),
            event_loop
        )
        logger.info("🚀 RTVI message scheduled")
    except Exception as e:
        logger.error(f"❌ Error scheduling RTVI message: {e}")
