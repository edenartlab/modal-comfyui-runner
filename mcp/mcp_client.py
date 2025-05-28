#!/usr/bin/env python3
"""
Simple MCP client for testing the ComfyUI Modal MCP server.

This client can connect to either a local MCP server or a remote Modal-deployed server.
"""

import asyncio
import base64
import json
import sys
from pathlib import Path
from typing import Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


async def save_image_from_b64(b64_data: str, filename: str) -> str:
    """Save base64 image data to a file."""
    # Remove data URL prefix if present
    if b64_data.startswith("data:image/png;base64,"):
        b64_data = b64_data[22:]
    
    image_bytes = base64.b64decode(b64_data)
    output_path = Path("mcp_outputs") / filename
    output_path.parent.mkdir(exist_ok=True)
    
    output_path.write_bytes(image_bytes)
    return str(output_path)


async def test_local_server():
    """Test the MCP server running locally via stdio."""
    print("🔗 Connecting to local MCP server...")
    
    # Configure server parameters for local connection
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server.py"],
        env=None,
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()
            print("✅ Connected to MCP server")
            
            # List available tools
            tools = await session.list_tools()
            print(f"📋 Available tools: {[tool.name for tool in tools.tools]}")
            
            # List available resources
            resources = await session.list_resources()
            print(f"📄 Available resources: {[resource.uri for resource in resources.resources]}")
            
            # Read workflow info resource
            if resources.resources:
                for resource in resources.resources:
                    if resource.uri == "workflow://txt2img":
                        content, mime_type = await session.read_resource(resource.uri)
                        print(f"📖 txt2img info:\n{content}")
                        break
            
            # Test the txt2img tool
            print("\n🎨 Testing txt2img tool...")
            result = await session.call_tool(
                "txt2img",
                arguments={
                    "prompt": "A beautiful sunset over a mountain landscape",
                    "seed": 42
                }
            )
            
            print(f"🖼️  Tool result type: {type(result.content)}")
            
            # Handle the result
            if result.content and len(result.content) > 0:
                content_item = result.content[0]
                if hasattr(content_item, 'text'):
                    result_text = content_item.text
                    if result_text.startswith("data:image/png;base64,"):
                        # Save the image
                        filename = "test_txt2img_local.png"
                        saved_path = await save_image_from_b64(result_text, filename)
                        print(f"💾 Image saved to: {saved_path}")
                    else:
                        print(f"❌ Error: {result_text}")
                else:
                    print(f"📝 Result: {content_item}")


async def test_remote_server(server_url: str):
    """Test the MCP server running on Modal via HTTP."""
    print(f"🌐 Connecting to remote MCP server at {server_url}...")
    
    try:
        async with streamablehttp_client(server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                # Initialize the connection
                await session.initialize()
                print("✅ Connected to remote MCP server")
                
                # List available tools
                tools = await session.list_tools()
                print(f"📋 Available tools: {[tool.name for tool in tools.tools]}")
                
                # Test the txt2img tool
                print("\n🎨 Testing txt2img tool...")
                result = await session.call_tool(
                    "txt2img",
                    arguments={
                        "prompt": "A futuristic robot in a cyberpunk city",
                        "seed": 123
                    }
                )
                
                print(f"🖼️  Tool result type: {type(result.content)}")
                
                # Handle the result
                if result.content and len(result.content) > 0:
                    content_item = result.content[0]
                    if hasattr(content_item, 'text'):
                        result_text = content_item.text
                        if result_text.startswith("data:image/png;base64,"):
                            # Save the image
                            filename = "test_txt2img_remote.png"
                            saved_path = await save_image_from_b64(result_text, filename)
                            print(f"💾 Image saved to: {saved_path}")
                        else:
                            print(f"❌ Error: {result_text}")
                    else:
                        print(f"📝 Result: {content_item}")
                        
    except Exception as e:
        print(f"❌ Failed to connect to remote server: {e}")


async def main():
    """Main function to run MCP client tests."""
    if len(sys.argv) > 1:
        if sys.argv[1] == "--remote":
            # Test remote Modal server
            if len(sys.argv) > 2:
                server_url = sys.argv[2]
            else:
                server_url = "https://edenartlab--mcp-comfyui-server.modal.run/mcp"
            await test_remote_server(server_url)
        elif sys.argv[1] == "--local":
            # Test local server
            await test_local_server()
        else:
            print("Usage:")
            print("  python mcp_client.py --local                    # Test local server")
            print("  python mcp_client.py --remote [URL]             # Test remote server")
            print("  python mcp_client.py --remote https://example.com/mcp")
    else:
        print("🧪 Running both local and remote tests...\n")
        print("=" * 50)
        print("LOCAL SERVER TEST")
        print("=" * 50)
        try:
            await test_local_server()
        except Exception as e:
            print(f"❌ Local test failed: {e}")
        
        print("\n" + "=" * 50)
        print("REMOTE SERVER TEST")
        print("=" * 50)
        # Default remote server URL
        remote_url = "https://edenartlab--mcp-comfyui-server.modal.run/mcp"
        await test_remote_server(remote_url)


if __name__ == "__main__":
    asyncio.run(main())