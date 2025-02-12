import streamlit as st
from services import (
    ContentUnderstandingService,
    classify_document,
    calculate_text_tokens,
    calculate_image_tokens,
)
from schemas import get_analyzer_schema
from openai import OpenAI, BadRequestError

import io
import pdfplumber
import json
from pdf2image import convert_from_bytes
from PIL import Image

import openai
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

#####################################
# Config / Setup
#####################################
CONTENT_UNDERSTANDING_ENDPOINT = os.getenv("CONTENT_UNDERSTANDING_AI_ENDPOINT")
CONTENT_UNDERSTANDING_API_KEY = os.getenv("CONTENT_UNDERSTANDING_AI_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_BASE_URL = os.getenv("GITHUB_BASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Validate required environment variables
if not CONTENT_UNDERSTANDING_ENDPOINT or not CONTENT_UNDERSTANDING_API_KEY:
    st.error("Missing required Azure Content Understanding configuration. Please check your .env file.")
    st.stop()

# Determine LLM provider
if GITHUB_BASE_URL and GITHUB_TOKEN:
    LLM_PROVIDER = "github"
    st.info("Using GitHub-hosted LLM for classification and prompts.")
elif OPENAI_API_KEY:
    LLM_PROVIDER = "openai"
    st.info("Using OpenAI for classification and prompts.")
else:
    st.error("No LLM provider configured. Please set either GitHub or OpenAI credentials.")
    st.stop()

content_service = ContentUnderstandingService(
    endpoint=CONTENT_UNDERSTANDING_ENDPOINT,
    api_key=CONTENT_UNDERSTANDING_API_KEY,
)

# Make sure session state is initialized
if "documents_context" not in st.session_state:
    # We'll store a list of dicts, each describing a doc:
    #   {
    #       "file_name": str,
    #       "classification": str,
    #       "markdown": str,
    #       "extracted_fields": dict
    #   }
    st.session_state["documents_context"] = []

if "context_options" not in st.session_state:
    st.session_state["context_options"] = {
        "include_extracted_text": False,
        "include_image_tokens": False,
        "include_extracted_fields": True
    }

def get_filtered_context(docs, options) -> list:
    """Get context messages based on selected options."""
    messages = []
    
    # First add all image messages if enabled
    if options["include_image_tokens"]:
        for i, doc in enumerate(docs):
            messages.append({
                "role": "user",
                "content": f"[Image from Document #{i+1}: {doc['file_name']}]"
            })
    
    # Then add text context
    context = ""
    for i, doc in enumerate(docs):
        context += f"\nDocument #{i+1}: {doc['file_name']}\n"
        context += f"Type: {doc['classification']}\n"
        
        if options["include_extracted_fields"]:
            fields_str = json.dumps(doc["extracted_fields"], ensure_ascii=False, indent=2)
            context += f"Key Information:\n{fields_str}\n"
        
        if options["include_extracted_text"]:
            preview_text = doc['markdown'][:250] + "..." if len(doc['markdown']) > 250 else doc['markdown']
            context += f"Full Context: {preview_text}\n"
    
    if context:
        messages.append({
            "role": "user",
            "content": f"Context from documents:\n{context}"
        })
    
    return messages

def get_token_color(tokens: int, max_tokens: int) -> str:
    """Return a color based on token count relative to max."""
    if max_tokens == 0:
        return "white"
    ratio = tokens / max_tokens
    if ratio < 0.3:
        return "green"
    elif ratio < 0.6:
        return "orange"
    else:
        return "red"

def format_token_display(tokens: int, baseline_tokens: int) -> str:
    """
    Format token display with reduction percentage relative to image baseline.
    A positive percentage means an increase, negative means reduction.
    """
    if baseline_tokens == 0:
        return f"{tokens:,} tokens"
    change = ((tokens - baseline_tokens) / baseline_tokens) * 100
    if change > 0:
        return f"{tokens:,} tokens (+{change:.1f}%)"
    else:
        return f"{tokens:,} tokens ({change:.1f}%)"

st.title("Context-Building For Reasoning Models - Demo")

tabs = st.tabs(["Upload & Analysis", "Document Context", "Custom Prompt"])
with tabs[0]:
    uploaded_file = st.file_uploader("Upload a PDF (one at a time)", type=["pdf"])
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()

        # 1) Extract minimal text for classification
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            classification_text = []
            max_pages_for_classification = 2
            for i, page in enumerate(pdf.pages):
                if i >= max_pages_for_classification:
                    break
                classification_text.append(page.extract_text() or "")
            classification_text = "\n".join(classification_text)

        # 2) Classify the PDF (Bankauszug or Lohnausweis) - Simulated (Later will be done using Document Intelligence)
        doc_type = classify_document(
            filename=uploaded_file.name.lower(),
        )
        st.write(f"**Classification Result (Simulated)**: `{doc_type}`")

        # 3) Create or update appropriate analyzer
        try:
            schema_data = get_analyzer_schema(doc_type)
            analyzer_resp = content_service.create_or_update_analyzer(schema_data)
            st.write("Analyzer creation/update status:", analyzer_resp)
        except Exception as e:
            st.error(f"Failed to create/update analyzer: {e}")
            st.stop()

        # 4) Analyze content with Azure
        try:
            analysis_result = content_service.analyze_content(schema_data["name"], file_bytes)
            if "contents" in analysis_result and len(analysis_result["contents"]) > 0:
                content_result = analysis_result["contents"][0]
                markdown_output = content_result.get("markdown", "")
                fields_output = content_result.get("fields", {})
            else:
                markdown_output = ""
                fields_output = {}
        except Exception as e:
            st.error(f"Analysis failed: {e}")
            st.stop()

        # 5) Convert PDF pages to images + calculate image tokens
        pdf_images = convert_from_bytes(file_bytes, dpi=200)
        total_image_tokens = 0
        page_previews = []
        for idx, page_img in enumerate(pdf_images):
            width, height = page_img.size
            page_tokens = calculate_image_tokens(width, height, detail="high")
            total_image_tokens += page_tokens
            page_previews.append((idx+1, page_img, page_tokens))

        # 6) Summarize fields
        extracted_dict = {}
        for field_name, field_data in fields_output.items():
            ftype = field_data.get("type", "")
            if ftype == "string":
                extracted_dict[field_name] = field_data.get("valueString", "")
            elif ftype == "array":
                arr = field_data.get("valueArray", [])
                extracted_dict[field_name] = [x.get("valueString", "") for x in arr]
            else:
                extracted_dict[field_name] = "?"

        # 7) Store in session state
        new_doc_context = {
            "file_name": uploaded_file.name,
            "classification": doc_type,
            "markdown": markdown_output,
            "extracted_fields": extracted_dict,
            "image_tokens_total": total_image_tokens,
        }
        st.session_state["documents_context"].append(new_doc_context)
        st.success(f"Added {uploaded_file.name} to context.")

with tabs[1]:
    if len(st.session_state["documents_context"]) > 0:
        for i, doc in enumerate(st.session_state["documents_context"]):
            with st.expander(f"Document #{i+1}: {doc['file_name']}", expanded=True):
                # Calculate all tokens first to determine max
                markdown_tokens = calculate_text_tokens(doc['markdown'])
                fields_json = json.dumps(doc["extracted_fields"], ensure_ascii=False, indent=2)
                fields_tokens = calculate_text_tokens(fields_json)
                image_tokens = doc['image_tokens_total']  # This is our baseline
                total_doc_tokens = image_tokens + markdown_tokens + fields_tokens
                
                # Find max for color coding
                max_tokens = max(image_tokens, markdown_tokens, fields_tokens)
                
                cols = st.columns(3)
                
                # Column 1: Image & Image Tokens (Baseline)
                with cols[0]:
                    token_color = get_token_color(image_tokens, max_tokens)
                    st.markdown(f"<p style='color: {token_color}'><b>{image_tokens:,} tokens (baseline)</b></p>", unsafe_allow_html=True)
                    st.markdown("### Image Analysis")
                    st.write(f"**Classification**: {doc['classification']}")
                    st.write("Includes all pages at high detail.")
                
                # Column 2: Markdown & Text Tokens (Compare to baseline)
                with cols[1]:
                    token_color = get_token_color(markdown_tokens, max_tokens)
                    st.markdown(f"<p style='color: {token_color}'><b>{format_token_display(markdown_tokens, image_tokens)}</b></p>", unsafe_allow_html=True)
                    st.markdown("### Extracted Text")
                    markdown_snippet = doc['markdown'][:250] + "..." if doc['markdown'] else "No text extracted"
                    st.write("**Text Preview:**")
                    st.write(markdown_snippet)
                
                # Column 3: Extracted Fields & Their Tokens (Compare to baseline)
                with cols[2]:
                    token_color = get_token_color(fields_tokens, max_tokens)
                    st.markdown(f"<p style='color: {token_color}'><b>{format_token_display(fields_tokens, image_tokens)}</b></p>", unsafe_allow_html=True)
                    st.markdown("### Extracted Fields")
                    st.json(doc["extracted_fields"])
                
                # Total tokens for this document
                st.markdown("---")
                st.markdown(f"**Total Document Tokens**: {total_doc_tokens:,}")
    else:
        st.info("No documents uploaded yet. Use the Upload tab to add documents.")

with tabs[2]:
    st.header("Custom Prompt with Document Context")
    
    st.info("""
    **Best Practices for Context Management**
    
    Provide necessary context, omit the rest. Include domain information the model needs, 
    but avoid overloading the prompt with unrelated text or excessive examples that could 
    dilute the model's focus.
    See: https://techcommunity.microsoft.com/blog/azure-ai-services-blog/prompt-engineering-for-openai%E2%80%99s-o1-and-o3-mini-reasoning-models/4374010
    """)
    
    # Context selection with session state
    st.markdown("#### Context Management")
    col1, col2, col3 = st.columns(3)
    with col1:
        include_extracted_text = st.checkbox(
            "Include Extracted Text",
            value=st.session_state["context_options"]["include_extracted_text"],
            help="Full text content from documents",
            key="extracted_text_checkbox"
        )
    with col2:
        include_image_tokens = st.checkbox(
            "Include Image Tokens",
            value=st.session_state["context_options"]["include_image_tokens"],
            help="Add images as separate messages",
            key="image_tokens_checkbox"
        )
    with col3:
        include_extracted_fields = st.checkbox(
            "Include Extracted Fields",
            value=st.session_state["context_options"]["include_extracted_fields"],
            help="Include structured data",
            key="extracted_fields_checkbox"
        )

    # Update context options in session state
    st.session_state["context_options"].update({
        "include_extracted_text": include_extracted_text,
        "include_image_tokens": include_image_tokens,
        "include_extracted_fields": include_extracted_fields
    })

    # Get context messages
    context_messages = get_filtered_context(
        st.session_state["documents_context"],
        st.session_state["context_options"]
    )

    # Prompt configuration
    st.markdown("#### Question")
    user_prompt = st.text_area(
        "What would you like to know about these documents?",
        value="Based on these financial documents, what investment strategy would you recommend?",
        help="Ask specific questions about the provided context",
        height=100,
    )

    # Construct final messages array
    messages = context_messages + [{"role": "user", "content": user_prompt}]

    # Preview tokens and content
    preview_tokens = sum(calculate_text_tokens(msg["content"]) for msg in messages)
    
    with st.expander("Review Prompt Structure", expanded=True):
        st.markdown(f"**Total Tokens**: {preview_tokens:,}")
        if len(st.session_state["documents_context"]) > 0:
            total_possible = sum(
                doc['image_tokens_total'] + 
                calculate_text_tokens(doc['markdown']) + 
                calculate_text_tokens(json.dumps(doc["extracted_fields"]))
                for doc in st.session_state["documents_context"]
            )
            reduction = (total_possible - preview_tokens) / total_possible * 100
        
        st.markdown("**Final Messages Structure:**")
        for i, msg in enumerate(messages):
            st.markdown(f"**Message {i+1} ({msg['role']}):**")
            st.text(msg["content"])

    if st.button("Send Prompt"):
        if LLM_PROVIDER == "github":
            try:
                client = OpenAI(
                    base_url=GITHUB_BASE_URL,
                    api_key=GITHUB_TOKEN,
                )
                response = client.chat.completions.create(
                    model="o1",
                    messages=messages,
                    temperature=0,
                )
                llm_answer = response.choices[0].message.content
            except BadRequestError as e:
                st.error(f"GitHub LLM call failed: {str(e)}")
                if "unauthorized" in str(e).lower() or "401" in str(e):
                    st.error("Authentication failed. Please check your GitHub token and base URL.")
                st.stop()
        else:
            try:
                client = OpenAI(
                    api_key=OPENAI_API_KEY,
                )
                response = client.chat.completions.create(
                    model="o1",
                    messages=messages,
                    temperature=1,
                )
                llm_answer = response.choices[0].message.content
            except BadRequestError as e:
                st.error(f"GitHub LLM call failed: {str(e)}")
                if "unauthorized" in str(e).lower() or "401" in str(e):
                    st.error("Authentication failed. Please check your GitHub token and base URL.")
                st.stop()

        st.write("### AI Analysis")
        st.markdown(llm_answer)
