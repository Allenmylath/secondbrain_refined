#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Property search tool for the real estate bot."""

import time
import traceback
from typing import Dict, Any, Optional
import openai
from loguru import logger
from strands import tool

from src.config.settings import OPENAI_API_KEY, DEFAULT_SEARCH_LIMIT, DEFAULT_VECTOR_INDEX
from src.database import PropertyDatabase
from src.tools.rtvi_messaging import schedule_rtvi_message


# Set up OpenAI client for embeddings
openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Initialize database client
db_client = PropertyDatabase()


@tool
def execute_hybrid_search(
    text_query: str,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    bedrooms: Optional[str] = None,
    bathrooms: Optional[str] = None,
    property_type: Optional[str] = None,
    location_keywords: Optional[str] = None,
    mls_genuine: Optional[bool] = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    vector_search_index: str = DEFAULT_VECTOR_INDEX,
    event_loop: Optional[Any] = None,
    rtvi_instance: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Execute hybrid search combining vector similarity with traditional filters.
    
    Args:
        text_query: Natural language search query
        min_price: Minimum price filter
        max_price: Maximum price filter
        bedrooms: Number of bedrooms (as string)
        bathrooms: Number of bathrooms (as string)
        property_type: Type of property (house, condo, etc.)
        location_keywords: Location-based keywords
        mls_genuine: Filter for MLS genuine properties
        limit: Maximum number of results to return
        vector_search_index: Name of the vector search index
        event_loop: Event loop for RTVI messaging
        rtvi_instance: RTVI processor instance
    
    Returns:
        Dict containing search results or error information
    """
    debug_log = []
    start_time = time.time()

    def log_debug(message: str, data: Any = None):
        """Helper function to log debug information"""
        timestamp = time.time() - start_time
        log_entry = f"[{timestamp:.2f}s] {message}"
        if data is not None:
            log_entry += f" | Data: {str(data)[:200]}..."
        debug_log.append(log_entry)
        logger.debug(f"🔍 SEARCH: {log_entry}")

    log_debug("=== HYBRID SEARCH DEBUG SESSION STARTED ===")

    try:
        # ====== STEP 1: VALIDATE INPUT ======
        if not text_query or not text_query.strip():
            error_result = _create_error_result(
                "Text query is empty or None",
                debug_log,
                "input_validation",
                text_query
            )
            _schedule_error_message(event_loop, rtvi_instance, error_result, text_query)
            return error_result

        # ====== STEP 2: GENERATE EMBEDDING ======
        try:
            embedding_vector = _generate_embedding(text_query.strip())
            log_debug(f"✅ Embedding generated. Dimensions: {len(embedding_vector)}")
        except Exception as openai_error:
            error_result = _create_error_result(
                f"OpenAI API error: {str(openai_error)}",
                debug_log,
                "openai_api_call",
                text_query
            )
            _schedule_error_message(event_loop, rtvi_instance, error_result, text_query)
            return error_result

        # ====== STEP 3: DATABASE SEARCH ======
        try:
            # Build filters
            match_conditions = db_client.build_match_conditions(
                min_price=min_price,
                max_price=max_price,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                property_type=property_type,
                location_keywords=location_keywords,
                mls_genuine=mls_genuine,
            )
            log_debug(f"Match conditions: {match_conditions}")

            # Build and execute search pipeline
            pipeline = db_client.build_search_pipeline(
                embedding_vector=embedding_vector,
                match_conditions=match_conditions,
                limit=limit,
                vector_search_index=vector_search_index,
            )
            log_debug(f"Pipeline stages: {len(pipeline)}")

            results = db_client.execute_search_query(pipeline)
            log_debug(f"Found {len(results)} results")

        except Exception as mongo_error:
            error_result = _create_error_result(
                f"MongoDB error: {str(mongo_error)}",
                debug_log,
                "mongodb_operation",
                text_query
            )
            _schedule_error_message(event_loop, rtvi_instance, error_result, text_query)
            return error_result

        # ====== STEP 4: FORMAT RESULTS ======
        formatted_results = db_client.format_search_results(results)
        similarity_scores = [prop["search_score"] for prop in formatted_results]

        total_time = time.time() - start_time
        log_debug(f"=== HYBRID SEARCH COMPLETED SUCCESSFULLY in {total_time:.2f}s ===")

        search_result = {
            "search_completed": True,
            "search_type": "hybrid_vector_traditional",
            "query": text_query,
            "embedding_dimensions": len(embedding_vector),
            "filters_applied": {
                "min_price": min_price,
                "max_price": max_price,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "property_type": property_type,
                "location_keywords": location_keywords,
                "mls_genuine": mls_genuine,
            },
            "results_found": len(results),
            "top_similarity_scores": similarity_scores,
            "properties": formatted_results,
            "search_method": "MongoDB vector search + traditional filters",
            "execution_time_seconds": round(total_time, 2),
            "debug_log": debug_log,
            "note": "Hybrid search combining semantic similarity with structured filters",
        }

        # Send RTVI message
        schedule_rtvi_message(event_loop, rtvi_instance, search_result, text_query)

        return search_result

    except Exception as e:
        error_result = _create_error_result(
            f"Unexpected error in hybrid search: {str(e)}",
            debug_log,
            "unexpected_error",
            text_query,
            full_traceback=traceback.format_exc()
        )
        _schedule_error_message(event_loop, rtvi_instance, error_result, text_query)
        return error_result


def _generate_embedding(text: str) -> list:
    """Generate embedding for the given text using OpenAI API."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not found")
    
    response = openai_client.embeddings.create(
        model="text-embedding-3-large", 
        input=text
    )
    return response.data[0].embedding


def _create_error_result(
    error_msg: str,
    debug_log: list,
    failure_point: str,
    text_query: str,
    full_traceback: Optional[str] = None
) -> Dict[str, Any]:
    """Create standardized error result dictionary."""
    error_result = {
        "error": error_msg,
        "debug_log": debug_log,
        "failure_point": failure_point,
        "query": text_query,
    }
    
    if full_traceback:
        error_result["full_traceback"] = full_traceback
    
    return error_result


def _schedule_error_message(
    event_loop: Optional[Any],
    rtvi_instance: Optional[Any],
    error_result: Dict[str, Any],
    text_query: str
) -> None:
    """Schedule RTVI error message if possible."""
    if event_loop and rtvi_instance:
        try:
            schedule_rtvi_message(event_loop, rtvi_instance, error_result, text_query)
        except Exception as rtvi_error:
            logger.error(f"❌ Error scheduling RTVI error: {rtvi_error}")
