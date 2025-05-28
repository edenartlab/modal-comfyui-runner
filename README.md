# modal-comfyui-runner
A standalone repo to run comfyui workflows on modal



TODO:

- fix custom_node installations (comfy-cli or git clone are both not working rn... )
- correctly parse all workflow outputs and stream them to client
- implement all custom arg injection types (folder, array, ...)
- move over all existing workflows to this new deploy system (should have faster boot due to memory-snapshot)