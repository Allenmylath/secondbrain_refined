#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""MongoDB client and query operations for real estate data."""

import re
import time
from typing import Dict, Any, List, Optional
from pymongo import MongoClient
from loguru import logger

from src.config.settings import MONGODB_CONNECTION_STRING


class PropertyDatabase:
    """Database client for property search operations."""
    
    def __init__(self):
        self.connection_string = MONGODB_CONNECTION_STRING
        self.db_name = "real_estate"
        self.collection_name = "properties"
    
    def get_client(self):
        """Create and return a MongoDB client."""
        return MongoClient(self.connection_string)
    
    def test_connection(self) -> bool:
        """Test MongoDB connection."""
        try:
            client = self.get_client()
            client.admin.command("ping")
            client.close()
            return True
        except Exception as e:
            logger.error(f"MongoDB connection test failed: {e}")
            return False
    
    def build_match_conditions(
        self,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        bedrooms: Optional[str] = None,
        bathrooms: Optional[str] = None,
        property_type: Optional[str] = None,
        location_keywords: Optional[str] = None,
        mls_genuine: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Build MongoDB match conditions for filtering."""
        match_conditions = {}
        
        # Price range filter
        if min_price is not None or max_price is not None:
            price_filter = {}
            if min_price is not None:
                price_filter["$gte"] = min_price
            if max_price is not None:
                price_filter["$lte"] = max_price
            match_conditions["property_details.listed_price"] = price_filter
        
        # Bedrooms filter
        if bedrooms is not None:
            match_conditions["property_details.bedrooms"] = bedrooms
        
        # Bathrooms filter
        if bathrooms is not None:
            match_conditions["property_details.bathrooms"] = bathrooms
        
        # Property type filter
        if property_type is not None:
            match_conditions["property_details.property_type"] = {
                "$regex": re.escape(property_type),
                "$options": "i",
            }
        
        # Location filter
        if location_keywords is not None:
            match_conditions["property_details.address"] = {
                "$regex": re.escape(location_keywords),
                "$options": "i",
            }
        
        # MLS genuine filter
        if mls_genuine is not None:
            match_conditions["property_details.mls_is_genuine"] = mls_genuine
        
        return match_conditions
    
    def build_search_pipeline(
        self,
        embedding_vector: List[float],
        match_conditions: Dict[str, Any],
        limit: int = 10,
        vector_search_index: str = "vector_index",
    ) -> List[Dict[str, Any]]:
        """Build MongoDB aggregation pipeline for hybrid search."""
        pipeline = [
            {
                "$vectorSearch": {
                    "index": vector_search_index,
                    "path": "embedding",
                    "queryVector": embedding_vector,
                    "numCandidates": min(100, limit * 10),
                    "limit": limit * 5,
                }
            },
            {"$addFields": {"search_score": {"$meta": "vectorSearchScore"}}},
        ]
        
        # Add match conditions if any
        if match_conditions:
            pipeline.append({"$match": match_conditions})
        
        # Add projection for nested structure
        pipeline.extend([
            {
                "$project": {
                    "_id": 1,
                    "property_url": 1,
                    "property_details.address": 1,
                    "property_details.listed_price": 1,
                    "property_details.currency": 1,
                    "property_details.bedrooms": 1,
                    "property_details.bathrooms": 1,
                    "property_details.property_type": 1,
                    "property_details.mls_description": 1,
                    "property_details.mls_number": 1,
                    "property_details.mls_is_genuine": 1,
                    "processing_info.images_analyzed": 1,
                    "processing_info.status": 1,
                    "ai_analysis_raw": 1,
                    "search_score": 1,
                }
            },
            {"$sort": {"search_score": -1}},
            {"$limit": limit},
        ])
        
        return pipeline
    
    def execute_search_query(
        self,
        pipeline: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Execute the search pipeline and return results."""
        try:
            client = self.get_client()
            db = client[self.db_name]
            collection = db[self.collection_name]
            
            results = list(collection.aggregate(pipeline))
            client.close()
            
            return results
            
        except Exception as e:
            logger.error(f"MongoDB search query failed: {e}")
            raise
    
    def format_search_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format raw MongoDB results into clean property data."""
        formatted_results = []
        
        for result in results:
            search_score = result.get("search_score", 0)
            property_details = result.get("property_details", {})
            processing_info = result.get("processing_info", {})
            
            # Extract image URLs from processing_info.images_analyzed
            image_urls = []
            images_analyzed = processing_info.get("images_analyzed", [])
            
            if images_analyzed and isinstance(images_analyzed, list):
                image_urls = images_analyzed[:3]  # Use first 3 images
            else:
                # Generate placeholder URLs if no images
                property_id = str(result.get("_id", ""))
                image_urls = [
                    f"https://images.realtor.com/property/{property_id}/main.jpg",
                    f"https://images.realtor.com/property/{property_id}/interior.jpg",
                    f"https://images.realtor.com/property/{property_id}/exterior.jpg",
                ]
            
            # Format property data
            formatted_property = {
                "property_id": str(result.get("_id", "")),
                "url": result.get("property_url", ""),
                "image_urls": image_urls,
                "primary_image": image_urls[0] if image_urls else "",
                "address": property_details.get("address", "N/A"),
                "price": property_details.get("listed_price", "N/A"),
                "currency": property_details.get("currency", "CAD"),
                "bedrooms": property_details.get("bedrooms", "N/A"),
                "bathrooms": property_details.get("bathrooms", "N/A"),
                "property_type": property_details.get("property_type", "N/A"),
                "mls_number": property_details.get("mls_number", "N/A"),
                "mls_genuine": property_details.get("mls_is_genuine", "N/A"),
                "search_score": round(search_score, 4),
                "status": processing_info.get("status", "N/A"),
                "description": (
                    property_details.get("mls_description", "")[:200] + "..."
                    if property_details.get("mls_description", "")
                    else ""
                ),
            }
            formatted_results.append(formatted_property)
        
        return formatted_results
