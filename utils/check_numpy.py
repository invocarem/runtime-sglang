import torch
import numpy as np

# Verify conversion to NumPy
tensor = torch.ones(5)
try:
    arr = tensor.numpy()
    print("PyTorch built with NumPy support successfully.")
except Exception as e:
    print(f"Error: {e}")
