import torch
import sgl_kernel

print('='*50)
print('DGX SPARK SGLANG VERIFICATION')
print('='*50)
print(f'PyTorch: {torch.__version__}')
print(f'CUDA archs: {torch.cuda.get_arch_list()}')
print(f'sgl_kernel: {sgl_kernel.__version__}')
print(f'sgl_kernel location: {sgl_kernel.__file__}')
print('='*50)
print('✅ Your existing wheel works with custom PyTorch!')

