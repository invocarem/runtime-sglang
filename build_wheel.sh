# install sglang

export TORCH_CUDA_ARCH_LIST="12.1a"
export MAX_JOBS=4
export TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
echo "$TRITON_PTXAS_PATH"

cd sglang/sgl-kernal


TORCH_CUDA_ARCH_LIST="12.1a" MAX_JOBS=4 CMAKE_BUILD_PARALLEL_LEVEL=1  python -m build --wheel --no-isolation
