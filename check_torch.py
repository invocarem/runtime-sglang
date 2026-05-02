import torch
import sys

# Test 1: Basic symbol resolution
try:
    import torchvision
    # Check if torchvision's C++ extensions link to your PyTorch
    test_tensor = torch.randn(2, 3, 224, 224).cuda()
    from torchvision import models
    resnet = models.resnet18().cuda()
    output = resnet(test_tensor)
    print('✓ torchvision forward pass successful')
    print(f'  torchvision version: {torchvision.__version__}')
except Exception as e:
    print(f'✗ torchvision FAILED: {e}')
    sys.exit(1)

try:
    import torchaudio
    # Test a CUDA operation in torchaudio
    waveform = torch.randn(1, 16000).cuda()
    spec = torchaudio.transforms.Spectrogram()(waveform)
    print('✓ torchaudio CUDA operation successful')
    print(f'  torchaudio version: {torchaudio.__version__}')
except Exception as e:
    print(f'✗ torchaudio FAILED: {e}')
    sys.exit(1)
