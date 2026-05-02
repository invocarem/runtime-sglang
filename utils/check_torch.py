import torch
import torchvision
import torchaudio

# Check if all libraries see the same CUDA context
print(f'PyTorch CUDA version: {torch.version.cuda}')
print(f'PyTorch CUDA archs: {torch.cuda.get_arch_list()}')

# Create tensor in torch, process with torchvision, then with torchaudio
x = torch.randn(2, 3, 224, 224).cuda()
x_tv = torchvision.transforms.functional.rgb_to_grayscale(x)  # torchvision op
x_ta = torchaudio.functional.resample(x_tv.float(), 44100, 16000)  # torchaudio op

print('✓ Cross-library tensor operations work')
print(f'  Final tensor on device: {x_ta.device}')
