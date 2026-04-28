# build pytorch


```
 uv pip install -e . -v --no-build-isolation
python3 -c "
import torch
print('PyTorch version:', torch.__version__)
print('CUDA archs:', torch.cuda.get_arch_list())
print('Device:', torch.cuda.get_device_name(0))
print('Capability:', torch.cuda.get_device_capability(0))
"
[sglang] 0:bash*                                             
```

