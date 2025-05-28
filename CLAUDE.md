# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Modal-based ComfyUI runner that deploys ComfyUI workflows as serverless web APIs. The system supports different workspaces with their own custom nodes, models, and workflows.

## Key Architecture

**Core Components:**
- `modal_comfy.py`: Main deployment script that creates Modal apps with ComfyUI
- `comfyclient.py`: Client script for testing deployed workflows
- `deploy_utils.py`: Utility functions for workflow injection, downloads, and custom node installation
- `deploy_constants.py`: Configuration constants for GPU types, timeouts, and resource limits

**Workspace Structure:**
- `workspaces/{workspace_name}/`: Contains workspace-specific configurations
- `workspaces/{workspace_name}/workflows/{workflow_name}/`: Individual workflow definitions
- `workflow.json`: ComfyUI workflow definition
- `workflow_api.json`: API-ready workflow version  
- `api.yaml`: Parameter mapping configuration for workflow inputs
- `test.json`: Test parameters for the workflow
- `downloads.json`: URLs/git repos for models and assets to download
- `snapshot.json`: Custom nodes and their git commit hashes to install

## Common Commands

**Deploy a workspace to Modal:**
```bash
WORKSPACE=slow_new modal deploy modal_comfy.py
```

**Test a deployed workflow:**
```bash
python comfyclient.py --modal-workspace edenartlab --test-json workspaces/slow_new/workflows/txt2img/test.json --workflow txt2img --workspace_name slow-new-stage
```

**Serve for development:**
```bash
WORKSPACE=slow_new modal serve modal_comfy.py
```

## Configuration Details

**Environment Variables:**
- `WORKSPACE`: Required - workspace name from `workspaces/` directory
- `WORKFLOWS`: Optional - comma-separated list of specific workflows to deploy
- `DB`: Optional - "STAGE" (default) or "PROD" for environment selection

**Workflow Parameter Injection:**
The system uses `api.yaml` files to map external parameters to ComfyUI workflow nodes. Parameters are injected via the `inject_args_into_workflow()` function which:
- Maps parameters to specific workflow nodes using node_id, field, and subfield
- Supports parameter remapping for different workflow variations

## Memory Snapshots
The deployment uses Modal's memory snapshot feature for faster cold starts. The `memory_snapshot_helper/` directory contains patches for ComfyUI to properly restore GPU state after snapshot restoration.