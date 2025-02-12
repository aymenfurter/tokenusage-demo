import os
import requests
import uuid
import time
import logging
import json

from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

#####################################
# CONTENT UNDERSTANDING SERVICE
#####################################
class ContentUnderstandingService:
    """
    Service for interacting with Azure AI Content Understanding.
    """

    def __init__(self, endpoint: str, api_key: str, api_version: str = "2024-12-01-preview"):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.api_version = api_version

    def create_or_update_analyzer(self, schema_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or update an analyzer with the given schema_data (fields, etc.).
        """
        analyzer_id = schema_data["name"]
        url = f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_id}?api-version={self.api_version}"

        analyzer_config = {
            "analyzerId": analyzer_id,
            "description": schema_data.get("description", f"Analyzer for {analyzer_id}"),
            "scenario": schema_data.get("scenario", "document"),
            "fieldSchema": {"fields": {}, "definitions": {}},
            "tags": {
                "projectId": str(uuid.uuid4()),
                "templateId": f"{analyzer_id}-{self.api_version}",
            },
            "config": {"locales": [], "returnDetails": False},
        }

        # Build the fields
        fields = {}
        for field in schema_data["fields"]:
            field_name = field["name"]
            field_type = field["type"]
            description = field.get("description", "")

            # For "document" scenario, we typically use method="extract"
            method = "extract"

            if field_type == "array":
                fields[field_name] = {
                    "type": "array",
                    "method": method,
                    "description": description,
                    "items": {"type": "string", "method": method},
                }
            else:
                fields[field_name] = {
                    "type": field_type,
                    "method": method,
                    "description": description,
                }

        analyzer_config["fieldSchema"]["fields"] = fields

        # Create or update
        try:
            response = requests.put(url, headers=self._get_headers(), json=analyzer_config)

            if response.status_code == 409:
                logger.info(f"Analyzer {analyzer_id} already exists.")
                return {"analyzerId": analyzer_id, "status": "existing"}

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Error creating/updating analyzer: {str(e)}")
            raise

    def analyze_content(
        self,
        analyzer_id: str,
        content: bytes,
        max_retries: int = 120,
        retry_delay: int = 2,
    ) -> Dict[str, Any]:
        """
        Analyze binary content (PDF) using a specific analyzer.
        """
        url = f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze?_overload=analyzeBinary&api-version={self.api_version}"

        try:
            headers = self._get_headers(binary_content=True)
            response = requests.post(url, headers=headers, data=content)
            response.raise_for_status()

            if response.status_code == 202:
                return self._poll_analysis_result(
                    operation_url=response.headers.get("Operation-Location"),
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
            else:
                return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error analyzing content: {str(e)}")
            raise

    def _poll_analysis_result(self, operation_url: Optional[str], max_retries: int, retry_delay: int) -> Dict[str, Any]:
        """
        Poll for the asynchronous operation result.
        """
        if not operation_url:
            raise ValueError("No Operation-Location header in the initial response")

        for attempt in range(max_retries):
            logger.info(f"Polling attempt {attempt + 1}/{max_retries}")
            response = requests.get(operation_url, headers=self._get_headers())
            response.raise_for_status()

            result = response.json()
            status = result.get("status", "").lower()

            if status == "succeeded":
                return result.get("result", {})
            elif status in ["failed", "canceled"]:
                raise Exception(f"Analysis failed: {result.get('error', {}).get('message', 'Unknown error')}")
            elif status in ["notstarted", "running"]:
                time.sleep(retry_delay)
                continue
            else:
                raise Exception(f"Unknown status: {status}")

        raise TimeoutError("Analysis timed out")

    def _get_headers(self, binary_content: bool = False) -> Dict[str, str]:
        """
        Prepare headers for Azure requests.
        """
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Operation-Id": str(uuid.uuid4()),
            "x-ms-client-request-id": str(uuid.uuid4()),
        }
        if binary_content:
            headers["Content-Type"] = "application/octet-stream"
        else:
            headers["Content-Type"] = "application/json"
        return headers


#####################################
# DOCUMENT INTELLIGENCE CLASSIFICATION
#####################################
from openai import OpenAI, AzureOpenAI, BadRequestError

def classify_document(
    filename: str
) -> str:
    """
    Simulated document classification based on text content.
    For demo purposes, we just look for keywords in the text.
    """
    text = filename.lower()
    if "lohnausweis" in text or "salary" in text or "employer" in text:
        return "Lohnausweis"
    elif "kontoauszug" in text or "bankauszug" in text or "account" in text or "balance" in text:
        return "Bankauszug"
    return "Bankauszug"  # Default fallback


#####################################
# TOKEN CALCULATIONS
#####################################
def calculate_image_tokens(width: int, height: int, detail: str = "high") -> int:
    """
    Calculate the token cost of an image based on detail level and dimensions.
    """
    from math import ceil
    detail = detail.lower()
    if detail == "low":
        return 85

    # detail=high logic
    if width > 2048 or height > 2048:
        scale_factor = min(2048 / width, 2048 / height)
        width = int(width * scale_factor)
        height = int(height * scale_factor)

    shortest_side = min(width, height)
    if shortest_side < 768:
        ratio = 768.0 / shortest_side
        width = int(width * ratio)
        height = int(height * ratio)

    tiles_x = ceil(width / 512)
    tiles_y = ceil(height / 512)
    tile_count = tiles_x * tiles_y

    cost = tile_count * 170 + 85
    return cost


def calculate_text_tokens(text: str, model: str = "gpt-4o") -> int:
    """
    Approximate token usage for text using tiktoken. 
    Default changed to "gpt-4o" for consistency, but adjust if needed.
    """
    import tiktoken
    try:
        encoding = tiktoken.encoding_for_model(model)
    except:
        encoding = tiktoken.get_encoding("cl100k_base")

    tokens = encoding.encode(text)
    return len(tokens)
