# 1. Deploy ComfyUI behind a web endpoint:

# ```bash
# WORKSPACE=slow_new modal deploy comfyapp.py
# ```

# 2. In another terminal, run inference:

# ```bash
# python comfyclient.py --modal-workspace $(modal profile current) --prompt "Surreal dreamscape with floating islands, upside-down waterfalls, and impossible geometric structures, all bathed in a soft, ethereal light"
# ```

# We use [comfy-cli](https://github.com/Comfy-Org/comfy-cli) to install ComfyUI and its dependencies.

import json
import subprocess
import uuid
import os
from pathlib import Path
from typing import Dict

import modal
from deploy_utils import *
import deploy_constants as cfg 

# Get workspace configuration from environment
workspace_name = os.getenv("WORKSPACE")
workflows = os.getenv("WORKFLOWS", "")
db = os.getenv("DB", "STAGE").upper()

if not workspace_name:
    raise Exception("WORKSPACE environment variable is required")

print("========================================")
print(f"db: {db}")
print(f"workspace: {workspace_name}")
if workflows:
    print(f"Specific workflows: {workflows}")
print("========================================")

vol = modal.Volume.from_name(f"newcomfy-data-volume", create_if_missing=True)

image = (  # build up a Modal Image
    modal.Image.debian_slim(python_version="3.11")
    .env({"COMFYUI_PATH": cfg.root_comfy_dir})
    .env({"WORKSPACE": workspace_name})
    .env({"WORKFLOWS": workflows})

    .apt_install("git", "wget")
    .pip_install("fastapi[standard]==0.115.4")  # install web dependencies
    .pip_install("comfy-cli==1.3.9")  # install comfy-cli
    .run_commands(  # use comfy-cli to install ComfyUI and its dependencies
        "comfy --skip-prompt install --fast-deps --nvidia --version 0.3.10"
    )
    # Copy local files:
    .add_local_dir(
        local_path=Path(__file__).parent / "memory_snapshot_helper",
        remote_path=f"{cfg.root_comfy_dir}/custom_nodes/memory_snapshot_helper",
        copy=True,
    )
    .add_local_dir(
        local_path=Path(__file__).parent / "workspaces" / workspace_name,
        remote_path="/root/workspace",
        copy=True,
    )
    .run_function(
        download_files_from_workspace,
        volumes={"/data": vol}
    )
    .run_function(print_directory_structure,
        volumes={"/data": vol}
    )
    .run_function(
        install_custom_nodes_from_snapshot,
        volumes={"/data": vol}
    )   
    .run_function(print_directory_structure,
        volumes={"/data": vol}
    )
)

app_name = f"newcomfy-{workspace_name}-{db.lower()}"
app = modal.App(name=app_name, image=image)

# ## Running ComfyUI interactively
# Spin up an interactive ComfyUI server by wrapping the `comfy launch` command in a Modal Function
# and serving it as a [web server](https://modal.com/docs/guide/webhooks#non-asgi-web-servers).

@app.function( # Stateless / serve
    max_containers=1,  # limit interactive session to 1 container
    gpu=cfg.interactive_GPU,  # defined in deploy_constants.py
    volumes={"/data": vol},  # mounts our cached models
)
@modal.concurrent(
    max_inputs=cfg.max_inputs
)
@modal.web_server(8000, startup_timeout=cfg.startup_timeout)
def ui():
    subprocess.Popen("comfy launch -- --listen 0.0.0.0 --port 8000", shell=True)

# At this point you can run `modal serve comfyapp.py` and open the UI in your browser for the classic ComfyUI experience.

# Remember to **close your UI tab** when you are done developing.
# This will close the connection with the container serving ComfyUI and you will stop being charged.


########################################################
# ## Running ComfyUI as an API
########################################################
# To run a workflow as an API:
# 1. Stand up a "headless" ComfyUI server in the background when the app starts.
# 2. Define an `infer` method that takes in a workflow path and runs the workflow on the ComfyUI server.
# 3. Create a web handler `api` as a web endpoint, so that we can run our workflow as a service and accept inputs from clients.
# We group all these steps into a single Modal `cls` object, which we'll call `ComfyUI`.

@app.cls( # Stateful / deploy
    scaledown_window=cfg.scaledown_window,
    gpu=cfg.deploy_GPU,
    cpu=cfg.n_cpus,
    max_containers=cfg.max_containers,
    min_containers=cfg.min_containers,
    timeout=cfg.comfyui_timeout,
    volumes={"/data": vol},
    enable_memory_snapshot=True,  # snapshot container state for faster cold starts
)
@modal.concurrent(max_inputs=cfg.max_inputs)
class ComfyUI:
    port: int = 8000

    @modal.enter(snap=True)
    def launch_comfy_background(self):
        cmd = f"comfy launch --background -- --port {self.port}"
        subprocess.run(cmd, shell=True, check=True)

    @modal.enter(snap=False)
    def restore_snapshot(self):
        # initialize GPU for ComfyUI after snapshot restore
        # note: requires patching core ComfyUI, see the memory_snapshot_helper directory for more details
        import requests

        response = requests.post(f"http://127.0.0.1:{self.port}/cuda/set_device")
        if response.status_code != 200:
            print("Failed to set CUDA device")
        else:
            print("Successfully set CUDA device")

    @modal.method()
    def infer(self, workflow_path, workflow_name: str = None, comfyui_timeout: int = cfg.comfyui_timeout):
        # sometimes the ComfyUI server stops responding (we think because of memory leaks), so this makes sure it's still up
        self.poll_server_health()

        # runs the comfy run --workflow command as a subprocess
        cmd = f"comfy run --workflow {workflow_path} --wait --timeout {comfyui_timeout} --verbose"
        subprocess.run(cmd, shell=True, check=True)

        # completed workflows write output images to this directory
        output_dir = f"{cfg.root_comfy_dir}/output"

        # looks up the name of the output image file based on the workflow
        workflow = json.loads(Path(workflow_path).read_text())
        file_prefix = [
            node.get("inputs")
            for node in workflow.values()
            if node.get("class_type") == "SaveImage"
        ][0]["filename_prefix"]

        # returns the image as bytes
        for f in Path(output_dir).iterdir():
            if f.name.startswith(file_prefix):
                return f.read_bytes()
        
        # If no matching file found, return None or raise an error
        raise FileNotFoundError(f"No output file found with prefix: {file_prefix}")

    @modal.fastapi_endpoint(method="POST")
    def api(self, item: Dict):
        from fastapi import Response

        # Support workflow selection through request
        workflow_name = item.get("workflow", "workflow_api")
        
        # Try workspace-specific workflow first, fall back to default
        workspace_workflow_path = f"/root/workspace/workflows/{workflow_name}/workflow_api.json"
        default_workflow_path = "/root/workflow_api.json"
        
        if Path(workspace_workflow_path).exists():
            workflow_path = workspace_workflow_path
        else:
            workflow_path = default_workflow_path
            
        workflow_data = json.loads(Path(workflow_path).read_text())

        # insert the prompt (assuming node 6 exists, otherwise skip)
        if "6" in workflow_data and "inputs" in workflow_data["6"]:
            workflow_data["6"]["inputs"]["text"] = item.get("prompt", "")

        # give the output image a unique id per client request
        client_id = uuid.uuid4().hex
        
        # Find SaveImage node and update filename_prefix
        for node_id, node in workflow_data.items():
            if node.get("class_type") == "SaveImage":
                if "inputs" in node:
                    node["inputs"]["filename_prefix"] = client_id
                break

        # save this updated workflow to a new file
        new_workflow_file = f"{client_id}.json"
        json.dump(workflow_data, Path(new_workflow_file).open("w"))

        # run inference on the currently running container
        img_bytes = self.infer.local(new_workflow_file, workflow_name)

        return Response(img_bytes, media_type="image/jpeg")

    def poll_server_health(self) -> Dict:
        import socket
        import urllib

        try:
            # check if the server is up (response should be immediate)
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/system_stats")
            urllib.request.urlopen(req, timeout=5)
            print("ComfyUI server is healthy")
        except (socket.timeout, urllib.error.URLError) as e:
            # if no response in 5 seconds, stop the container
            print(f"Server health check failed: {str(e)}")
            modal.experimental.stop_fetching_inputs()

            # all queued inputs will be marked "Failed", so you need to catch these errors in your client and then retry
            raise Exception("ComfyUI server is not healthy, stopping container")


# ## More resources
# - [Alternative approach](https://modal.com/blog/comfyui-mem-snapshots) for deploying ComfyUI with memory snapshots
# - Run a ComfyUI workflow as a [Python script](https://modal.com/blog/comfyui-prototype-to-production)