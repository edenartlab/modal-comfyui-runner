# Modal ComfyUI Runner

⚠️ **Work in Progress** - This repository is under active development and not ready for production use.

A serverless ComfyUI deployment system that runs workflows on [Modal](https://modal.com) and exposes them via MCP (Model Context Protocol) servers for easy integration with AI assistants.

Includes:
- **Serverless ComfyUI**: Deploy workflows with automatic scaling and GPU optimization
- **Memory Snapshots**: Fast cold starts using Modal's memory snapshot feature
- **Workspace Management**: Organize workflows, models, and custom nodes by workspace
- **MCP Integration**: Expose workflows as tools for AI assistants
- **Parameter Injection**: Dynamic workflow customization via YAML configuration

## Architecture

### Core Components

- **`modal_comfy.py`**: Main deployment script creating Modal apps with ComfyUI
- **`comfyclient.py`**: Client for testing deployed workflows
- **`deploy_constants.py`**: GPU, timeout, and resource configuration
- **`mcp/`**: MCP server implementation for AI assistant integration

## Quick Start

### 1. Deploy a Workspace

```bash
# Set workspace and deploy to Modal
WORKSPACE=slow_new modal deploy modal_comfy.py
```

### 2. Test Deployment

```bash
# Test a specific workflow
python comfyclient.py \
  --modal-workspace edenartlab \
  --workspace_name slow-new-stage \
  --workflow txt2img \
  --test-json workspaces/slow_new/workflows/txt2img/test.json
```

### 3. Interactive Mode

```bash
# Serve ComfyUI as interactive endpoint accessible through browser:
WORKSPACE=slow_new modal serve modal_comfy.py
```


## MCP Server Integration

The MCP server exposes ComfyUI workflows as tools for AI assistants.

### Local Development

```bash
# Run MCP server locally
cd mcp/
python mcp_server.py

# Test with client
python mcp_client.py --local
```

### Deploy MCP Server

```bash
# Deploy to Modal
modal deploy mcp/mcp_server.py

# Test remote deployment
python mcp_client.py --remote https://your-modal-url/mcp
```

### Using with Claude Desktop

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "comfyui": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": {
        "MODAL_WORKSPACE": "your-workspace",
        "WORKSPACE_NAME": "your-workspace-name"
      }
    }
  }
}
```


## TODO:

- fix custom_node installations (comfy-cli vs git clone ... )
- correctly parse all workflow outputs and stream them to client
- implement all custom arg injection types (folder, array, ...)