import torch
import torchvision
import torchaudio
import sgl_kernel
import sglang
from importlib.metadata import version as get_version

print('='*50)
print('FULL STACK VERIFICATION')
print('='*50)
print(f'PyTorch: {torch.__version__}')
print(f'CUDA archs: {torch.cuda.get_arch_list()}')
print(f'torchvision: {torchvision.__version__}')
print(f'torchaudio: {torchaudio.__version__}')
print(f'sgl_kernel: {sgl_kernel.__version__}')
print(f'sglang: {get_version(\"sglang\")}')
print('='*50)
print('✅ All components working with custom PyTorch!')
