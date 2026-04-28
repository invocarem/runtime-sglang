# install sglang

export TORCH_CUDA_ARCH_LIST="12.1a"
export MAX_JOBS=4
export TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

uv pip install torch==2.10.0 torchvision torchaudio  --force-reinstall   --index-url https://download.pytorch.org/whl/cu130
git clone https://github.com/sgl-project/sglang.git

cd sglang
uv pip install -e "python"

# build wheel
#TORCH_CUDA_ARCH_LIST="12.1a" MAX_JOBS=4 CMAKE_BUILD_PARALLEL_LEVEL=1  python -m build --wheel --no-isolation
