#!/usr/bin/env python3
"""
MCP Server for ComfyUI Modal workflows.

This server exposes ComfyUI workflows deployed on Modal as MCP tools.
Can run locally for testing or be deployed on Modal.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from typing import Optional, Dict, Any

import modal
from mcp.server.fastmcp import FastMCP


# Configuration
MODAL_WORKSPACE = os.getenv("MODAL_WORKSPACE", "edenartlab")
WORKSPACE_NAME = os.getenv("WORKSPACE_NAME", "slow-new-stage")
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"

# Create MCP server
mcp = FastMCP("ComfyUI Modal Server")

def construct_modal_url(workflow: str) -> str:
    """Construct the Modal API URL for a given workflow."""
    dev_suffix = "-dev" if DEV_MODE else ""
    return f"https://{MODAL_WORKSPACE}--newcomfy-{WORKSPACE_NAME}-comfyui-api{dev_suffix}.modal.run/"


async def call_modal_workflow(workflow: str, parameters: Dict[str, Any]) -> bytes:
    """Call a Modal ComfyUI workflow with the given parameters."""
    url = construct_modal_url(workflow)
    
    payload = {
        "workflow": workflow,
        "args": parameters
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status}: {response.reason}")
            return response.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Exception(f"Workflow '{workflow}' not found at {url}")
        else:
            raise Exception(f"HTTP Error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise Exception(f"Failed to connect to Modal: {str(e)}")


@mcp.tool()
async def txt2img(
    prompt: str,
    seed: Optional[int] = None,
    save_path: Optional[str] = None
) -> str:
    """
    Generate an image from text using the txt2img ComfyUI workflow.
    
    Args:
        prompt: Text description of the image to generate
        seed: Random seed for reproducibility (optional, will be random if not provided)
        save_path: Local path to save the image, recommended for local usage (when None, returns base64 data)
    
    Returns:
        Base64 encoded PNG image data or local file path if save_path is provided
    """
    import base64
    
    # Prepare parameters for the workflow
    parameters = {"prompt": prompt}
    if seed is not None:
        parameters["seed"] = seed
    
    try:
        # Call the Modal workflow
        image_bytes = await call_modal_workflow("txt2img", parameters)
        
        if save_path is not None:
            with open(save_path, 'wb') as f:
                f.write(image_bytes)
            return save_path
        else:
            # Encode as base64 for MCP transport
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            return f"data:image/png;base64,{image_b64}"
        
    except Exception as e:
        return f"Error generating image: {str(e)}"


@mcp.resource("workflow://txt2img")
def get_txt2img_info() -> str:
    """Get information about the txt2img workflow."""
    return """
    txt2img workflow - Text to Image Generation
    
    This workflow generates images from text prompts using a Stable Diffusion 1.5 model.
    
    Parameters:
    - prompt (required): Text description of the image to generate
    - seed (optional): Random seed for reproducibility (0-2147483647)
    - save_path (optional): Local path to save the image (returns base64 data if not provided)
    
    Output: PNG image (base64 encoded or saved to local path)
    Base model: SD1.5
    """


# Modal deployment configuration
image = modal.Image.debian_slim(python_version="3.11").pip_install("mcp")

# Create Modal app for deployment
app = modal.App("mcp-comfyui-server")

@app.function(
    image=image,
    min_containers=1,
    timeout=600
)
@modal.web_server(8080)
def serve_mcp():
    """Serve the MCP server on Modal using streamable HTTP."""
    mcp.run(transport="streamable-http", port=8080)


if __name__ == "__main__":
    # Check if we should run on Modal or locally
    if len(sys.argv) > 1 and sys.argv[1] == "--modal":
        print("Deploying MCP server to Modal...")
        print("Use 'modal serve mcp_server.py' for development or 'modal deploy mcp_server.py' for production")
    else:
        print(f"Starting MCP server locally...")
        print(f"Modal workspace: {MODAL_WORKSPACE}")
        print(f"Workspace name: {WORKSPACE_NAME}")
        print(f"Dev mode: {DEV_MODE}")
        mcp.run()