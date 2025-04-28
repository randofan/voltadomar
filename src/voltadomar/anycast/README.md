To modify the proto file, run the following command from this directory to generate the Python code:

```bash
python -m grpc_tools.protoc \
  -I. \
  --python_out=. \
  --grpc_python_out=. \
  anycast.proto
```

This will generate the `anycast_pb2.py` and `anycast_pb2_grpc.py` files in the current directory. In `anycast_pb2_grpc.py`, update the import statement for `anycast_pb2` to use the relative import style:

```python
from . import anycast_pb2 as anycast__pb2
```
