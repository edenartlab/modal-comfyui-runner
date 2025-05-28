GPUs = {
    "L4": "L4", # cheap, slow gpu for deploy testing
    "A100": "A100-40GB",
    "A100-80GB": "A100-80GB" 
}

# GPU settings:
#deploy_GPU      = GPUs["A100"]
deploy_GPU      = GPUs["L4"]
interactive_GPU = GPUs["L4"]

# Deployed container settings:
n_cpus           = 4.0
min_containers   = 0
max_containers   = 1
max_inputs       = 3 # Max number of inputs to process concurrently (before scaling up)
scaledown_window = 180 # seconds (how long to keep a container alive after it's last input)

# Interactive server settings:
startup_timeout  = 60 # seconds (how long to wait for the server to start)

# ComfyUI settings:
root_comfy_dir  = "/root/ComfyUI"
comfyui_timeout = 5000 # seconds (how long to wait for ComfyUI to complete a workflow before timing out)

